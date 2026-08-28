import shutil
from pathlib import Path

import pytest

from pkg import linker


@pytest.fixture
def state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path / "state"


def make_root(tmp_path: Path, toml: str, configs: dict[str, dict[str, str]]) -> Path:
    (tmp_path / "pkg.toml").write_text(toml)
    cfgdir = tmp_path / "configs"
    shutil.rmtree(cfgdir, ignore_errors=True)
    for name, files in configs.items():
        for rel, content in files.items():
            p = cfgdir / name / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
    return tmp_path


def test_pkg_mode_links_whole_dir(tmp_path):
    root = make_root(tmp_path, "[config]\n", {"nvim": {"init.lua": "x"}})
    home = tmp_path / "home"
    items = linker.plan(root, home)
    assert len(items) == 1
    item = items[0]
    assert item.kind == "dir"
    assert item.target == home / ".config" / "nvim"


def test_stow_mode_links_files_into_home(tmp_path):
    root = make_root(
        tmp_path,
        '[config]\nstow = ["zsh"]\n',
        {"zsh": {".zshrc": "x", ".config/zsh/zshrc": "y"}},
    )
    home = tmp_path / "home"
    items = linker.plan(root, home)
    assert {str(i.target) for i in items} == {
        str(home / ".zshrc"),
        str(home / ".config" / "zsh" / "zshrc"),
    }
    assert all(i.kind == "file" for i in items)


def test_global_stow_mode(tmp_path):
    root = make_root(
        tmp_path,
        '[config]\nmode = "stow"\n',
        {"a": {".a": "x"}, "b": {"b": "y"}},
    )
    home = tmp_path / "home"
    items = linker.plan(root, home)
    assert {i.target.name for i in items} == {".a", "b"}


def test_apply_and_idempotency(tmp_path, state_home):
    root = make_root(tmp_path, "[config]\n", {"nvim": {"init.lua": "x"}})
    home = tmp_path / "home"
    items = linker.plan(root, home)
    created = linker.apply(items, home)
    assert len(created) == 1
    target = home / ".config" / "nvim"
    assert target.is_symlink()
    assert linker.read_link(target) == str(root / "configs" / "nvim")
    assert linker.apply(linker.plan(root, home), home) == []
    assert linker.load_state_map() == {str(target): str(root / "configs" / "nvim")}


def test_unlink_removes_owned(tmp_path, state_home):
    root = make_root(tmp_path, "[config]\n", {"nvim": {"init.lua": "x"}})
    home = tmp_path / "home"
    linker.apply(linker.plan(root, home), home)
    assert linker.unlink(home) == 1
    assert not (home / ".config" / "nvim").exists()
    assert not (home / ".config").exists()
    assert linker.load_state_map() == {}


def test_template_renders_file(tmp_path, state_home):
    root = make_root(
        tmp_path,
        '[config]\nstow = ["zsh"]\n\n[config.vars]\neditor = "nvim"\n',
        {"zsh": {".zshrc.tmpl": "export EDITOR=$editor\n"}},
    )
    home = tmp_path / "home"
    items = linker.plan(root, home)
    assert len(items) == 1
    item = items[0]
    assert item.kind == "render"
    assert item.target == home / ".zshrc"
    linker.apply(items, home)
    assert not (home / ".zshrc.tmpl").exists()
    assert (home / ".zshrc").read_text() == "export EDITOR=nvim\n"


def test_template_rewrite_when_ours_but_changed(tmp_path, state_home):
    root = make_root(
        tmp_path,
        '[config]\nstow = ["zsh"]\n\n[config.vars]\neditor = "nvim"\n',
        {"zsh": {".zshrc.tmpl": "export EDITOR=$editor\n"}},
    )
    home = tmp_path / "home"
    linker.apply(linker.plan(root, home), home)
    make_root(
        tmp_path,
        '[config]\nstow = ["zsh"]\n\n[config.vars]\neditor = "vim"\n',
        {"zsh": {".zshrc.tmpl": "export EDITOR=$editor\n"}},
    )
    linker.apply(linker.plan(root, home), home)
    assert (home / ".zshrc").read_text() == "export EDITOR=vim\n"


def test_template_diverged_needs_force(tmp_path, state_home):
    root = make_root(
        tmp_path,
        '[config]\nstow = ["zsh"]\n\n[config.vars]\neditor = "nvim"\n',
        {"zsh": {".zshrc.tmpl": "export EDITOR=$editor\n"}},
    )
    home = tmp_path / "home"
    linker.apply(linker.plan(root, home), home)
    (home / ".zshrc").write_text("user changes\n")
    with pytest.raises(linker.ConflictError, match="diverged"):
        linker.apply(linker.plan(root, home), home)
    assert (home / ".zshrc").read_text() == "user changes\n"
    linker.apply(linker.plan(root, home), home, force=True)
    assert (home / ".zshrc").read_text() == "export EDITOR=nvim\n"


def test_template_bad_var_is_error(tmp_path):
    root = make_root(
        tmp_path,
        '[config]\nstow = ["zsh"]\n',
        {"zsh": {".zshrc.tmpl": "x=$missing\n"}},
    )
    home = tmp_path / "home"
    with pytest.raises(Exception) as excinfo:
        linker.plan(root, home)
    assert "template" in str(excinfo.value)


def test_pkg_mode_with_tmpl_warns(tmp_path, capsys):
    root = make_root(tmp_path, "[config]\n", {"nvim": {"conf.tmpl": "x"}})
    linker.plan(root, tmp_path / "home")
    assert "pkg mode" in capsys.readouterr().out


def test_prune_removes_orphan(tmp_path, state_home):
    root = make_root(tmp_path, "[config]\n", {"nvim": {"init.lua": "x"}})
    home = tmp_path / "home"
    linker.apply(linker.plan(root, home), home)
    make_root(tmp_path, "[config]\n", {})
    removed, _ = linker.prune(linker.plan(root, home), home)
    assert removed == 1
    assert not (home / ".config" / "nvim").exists()


def test_prune_keeps_user_modified_render(tmp_path, state_home):
    root = make_root(
        tmp_path,
        '[config]\nstow = ["zsh"]\n',
        {"zsh": {".zshrc.tmpl": "a=b\n"}},
    )
    home = tmp_path / "home"
    linker.apply(linker.plan(root, home), home)
    (home / ".zshrc").write_text("mine now\n")
    make_root(tmp_path, "[config]\n", {})
    removed, notices = linker.prune(linker.plan(root, home), home)
    assert removed == 0
    assert (home / ".zshrc").read_text() == "mine now\n"
    assert any("user-modified" in n for n in notices)


def test_orphaned_preview(tmp_path, state_home):
    root = make_root(tmp_path, "[config]\n", {"nvim": {"init.lua": "x"}})
    home = tmp_path / "home"
    linker.apply(linker.plan(root, home), home)
    make_root(tmp_path, "[config]\n", {})
    expected = str(home / ".config" / "nvim")
    assert linker.orphaned(linker.plan(root, home)) == [expected]


def test_record_installed_roundtrip(tmp_path, state_home):
    linker.record_installed(["zsh", "fd"])
    assert linker.load_installed() == ["zsh", "fd"]
    linker.record_installed(["zsh"])
    assert linker.load_installed() == ["zsh"]


def test_duplicate_target_conflict(tmp_path, state_home):
    root = make_root(
        tmp_path,
        '[config]\nmode = "stow"\n',
        {"a": {"x": "1"}, "b": {"x": "2"}},
    )
    home = tmp_path / "home"
    problems = linker.find_conflicts(linker.plan(root, home), home)
    assert any("duplicate target" in p for p in problems)


def test_existing_file_conflict(tmp_path):
    root = make_root(tmp_path, "[config]\n", {"nvim": {"init.lua": "x"}})
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    (home / ".config" / "nvim").mkdir()
    (home / ".config" / "nvim" / "init.lua").write_text("mine")
    with pytest.raises(linker.ConflictError, match="exists"):
        linker.apply(linker.plan(root, home), home)
    assert (home / ".config" / "nvim" / "init.lua").read_text() == "mine"


def test_existing_parent_is_file_conflict(tmp_path):
    root = make_root(tmp_path, "[config]\n", {"nvim": {"init.lua": "x"}})
    home = tmp_path / "home"
    home.mkdir()
    (home / ".config").write_text("blocker")
    problems = linker.find_conflicts(linker.plan(root, home), home)
    assert any("not a directory" in p for p in problems)


def test_force_replaces_and_backs_up(tmp_path, state_home):
    root = make_root(
        tmp_path,
        '[config]\nstow = ["zsh"]\n',
        {"zsh": {".zshrc": "new-content"}},
    )
    home = tmp_path / "home"
    home.mkdir()
    (home / ".zshrc").write_text("existed")
    linker.apply(linker.plan(root, home), home, force=True)
    assert (home / ".zshrc").read_text() == "new-content"
    backup = tmp_path / "state" / "pkg" / "backup"
    assert any(backup.iterdir())  # the replaced file was backed up


def test_force_refuses_nonempty_dir(tmp_path):
    root = make_root(
        tmp_path,
        '[config]\nstow = ["zsh"]\n',
        {"zsh": {".config": "x", "keep": "y"}},
    )
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    (home / ".config" / "keep").write_text("mine")
    with pytest.raises(linker.ConflictError, match="non-empty"):
        linker.apply(linker.plan(root, home), home, force=True)
    assert (home / ".config" / "keep").read_text() == "mine"
