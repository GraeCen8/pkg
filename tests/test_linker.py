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


def test_duplicate_target_conflict(tmp_path):
    root = make_root(tmp_path, "[config]\n", {"kitty": {"a": "1"}})
    (tmp_path / "mod").mkdir()
    (tmp_path / "mod" / "pkg.toml").write_text("[config]\n")
    (tmp_path / "mod" / "configs" / "kitty").mkdir(parents=True)
    (tmp_path / "mod" / "configs" / "kitty" / "a").write_text("2")
    (tmp_path / "pkg.toml").write_text('[modules]\non = ["mod"]\n[config]\n')
    home = tmp_path / "home"
    problems = linker.find_conflicts(linker.plan(root, home), home)
    assert any("duplicate target" in p for p in problems)


def test_existing_file_conflict(tmp_path):
    root = make_root(
        tmp_path,
        '[config]\nstow = ["zsh"]\n',
        {"zsh": {".zshrc": "x"}},
    )
    home = tmp_path / "home"
    home.mkdir()
    (home / ".zshrc").write_text("occupied")
    problems = linker.find_conflicts(linker.plan(root, home), home)
    assert any("existing" in p for p in problems)
    with pytest.raises(linker.ConflictError):
        linker.apply(linker.plan(root, home), home)


def test_force_replaces_and_backs_up(tmp_path, state_home):
    root = make_root(
        tmp_path,
        '[config]\nstow = ["zsh"]\n',
        {"zsh": {".zshrc": "x"}},
    )
    home = tmp_path / "home"
    home.mkdir()
    (home / ".zshrc").write_text("occupied")
    created = linker.apply(linker.plan(root, home), home, force=True)
    assert len(created) == 1
    assert str(home / ".zshrc") in linker.load_state_map()
    assert any((state_home / "pkg" / "backup").iterdir())


def test_force_refuses_nonempty_dir(tmp_path, state_home):
    root = make_root(tmp_path, "[config]\n", {"nvim": {"init.lua": "x"}})
    home = tmp_path / "home"
    target = home / ".config" / "nvim"
    target.mkdir(parents=True)
    (target / "real.txt").write_text("keep me")
    with pytest.raises(linker.ConflictError, match="non-empty"):
        linker.apply(linker.plan(root, home), home, force=True)


def test_parent_is_file_conflict(tmp_path):
    root = make_root(
        tmp_path,
        '[config]\nstow = ["zsh"]\n',
        {"zsh": {".config/zsh/zshrc": "x"}},
    )
    home = tmp_path / "home"
    home.mkdir()
    (home / ".config").write_text("file not dir")
    problems = linker.find_conflicts(linker.plan(root, home), home)
    assert any("not a directory" in p for p in problems)
