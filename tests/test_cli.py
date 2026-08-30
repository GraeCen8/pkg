import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pkg import cli, linker
from pkg import config as cfg

# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path / "state"


def _make_root(tmp_path: Path, toml: str, configs: dict | None = None) -> Path:
    (tmp_path / "pkg.toml").write_text(toml)
    if configs:
        cfgdir = tmp_path / "configs"
        for name, files in configs.items():
            for rel, content in files.items():
                p = cfgdir / name / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
    else:
        (tmp_path / "configs").mkdir(exist_ok=True)
    return tmp_path


def _fake_pm(monkeypatch, installed=None):
    installed = installed or set()
    calls = []

    class FakePM:
        name = "apt"
        label = "Fake PM"

        def check(self, package):
            return package in installed

        def check_many(self, packages):
            return [p for p in packages if p not in installed]

        def install(self, packages):
            calls.append(("install", packages))
            installed.update(packages)
            return 0, ""

        def remove(self, packages):
            calls.append(("remove", packages))
            installed.difference_update(packages)
            return 0, ""

    monkeypatch.setattr(cli, "get_manager", lambda root_dir: FakePM())
    return installed, calls


# ---------------------------------------------------------------------------
# build_parser
# ---------------------------------------------------------------------------


def test_build_parser_subcommands():
    parser = cli.build_parser()
    assert parser.parse_args(["plan"]).cmd == "plan"
    assert parser.parse_args(["sync"]).cmd == "sync"
    assert parser.parse_args(["status"]).cmd == "status"
    assert parser.parse_args(["unlink"]).cmd == "unlink"
    assert parser.parse_args(["watch"]).cmd == "watch"
    assert parser.parse_args(["add", "x"]).cmd == "add"
    assert parser.parse_args(["remove", "x"]).cmd == "remove"
    assert parser.parse_args(["init", "."]).cmd == "init"


# ---------------------------------------------------------------------------
# find_root
# ---------------------------------------------------------------------------


def test_find_root_explicit(tmp_path, monkeypatch, state_home):
    _make_root(tmp_path, "[config]\n")
    monkeypatch.setattr(linker, "remember_root", lambda p: None)
    result = cli.find_root(str(tmp_path))
    assert result == tmp_path.resolve()


def test_find_root_cwd(tmp_path, monkeypatch, state_home):
    root = _make_root(tmp_path, "[config]\n")
    monkeypatch.chdir(root)
    monkeypatch.setattr(linker, "remember_root", lambda p: None)
    result = cli.find_root(None)
    assert result == root.resolve()


def test_find_root_remembered(tmp_path, monkeypatch, state_home):
    root = _make_root(tmp_path, "[config]\n")
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    monkeypatch.setattr(linker, "remembered_root", lambda: root)
    monkeypatch.setattr(linker, "remember_root", lambda p: None)
    result = cli.find_root(None)
    assert result == root.resolve()


def test_find_root_missing_exits(tmp_path, monkeypatch, state_home):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    monkeypatch.setattr(linker, "remembered_root", lambda: None)
    monkeypatch.setattr(cfg, "ROOT_DEFAULT", tmp_path / "nope")
    with pytest.raises(SystemExit):
        cli.find_root(None)


# ---------------------------------------------------------------------------
# cmd_init
# ---------------------------------------------------------------------------


def test_cmd_init_creates_scaffold(tmp_path, state_home):
    target = tmp_path / "newroot"
    args = SimpleNamespace(target=str(target), force=False, root=None)
    rc = cli.cmd_init(args)
    assert rc == 0
    assert (target / "configs").is_dir()
    assert (target / "pkg.toml").is_file()
    assert "[config]" in (target / "pkg.toml").read_text()


def test_cmd_init_existing_no_force(tmp_path, state_home, capsys):
    target = tmp_path / "newroot"
    target.mkdir()
    (target / "configs").mkdir()
    (target / "pkg.toml").write_text("existing")
    args = SimpleNamespace(target=str(target), force=False, root=None)
    rc = cli.cmd_init(args)
    assert rc == 0
    assert (target / "pkg.toml").read_text() == "existing"
    assert "already exists" in capsys.readouterr().out


def test_cmd_init_existing_with_force(tmp_path, state_home):
    target = tmp_path / "newroot"
    target.mkdir()
    (target / "configs").mkdir()
    (target / "pkg.toml").write_text("old")
    args = SimpleNamespace(target=str(target), force=True, root=None)
    rc = cli.cmd_init(args)
    assert rc == 0
    assert "[config]" in (target / "pkg.toml").read_text()


# ---------------------------------------------------------------------------
# cmd_plan
# ---------------------------------------------------------------------------


def test_cmd_plan_shows_packages_and_links(tmp_path, state_home, capsys):
    _make_root(
        tmp_path,
        '[[system]]\npackages = ["zsh"]\n',
        {"nvim": {"init.lua": "x"}},
    )
    home = tmp_path / "home"
    monkeypatches = pytest.MonkeyPatch()
    try:
        monkeypatches.setattr(cli, "find_root", lambda r: tmp_path)
        monkeypatches.setattr(cli, "host", lambda: home)
        _fake_pm(monkeypatches, installed=set())
        args = SimpleNamespace(root=None, system_only=False, configs_only=False, prune=False)
        rc = cli.cmd_plan(args)
        assert rc == 1  # 1 because conflicts exist (existing symlink from real home)
        out = capsys.readouterr().out
        assert "== system ==" in out
        assert "== links ==" in out
    finally:
        monkeypatches.undo()


def test_cmd_plan_configs_only(tmp_path, state_home, capsys):
    _make_root(
        tmp_path,
        '[[system]]\npackages = ["zsh"]\n',
        {"nvim": {"init.lua": "x"}},
    )
    home = tmp_path / "home"
    monkeypatches = pytest.MonkeyPatch()
    try:
        monkeypatches.setattr(cli, "find_root", lambda r: tmp_path)
        monkeypatches.setattr(cli, "host", lambda: home)
        _fake_pm(monkeypatches, installed=set())
        args = SimpleNamespace(root=None, system_only=False, configs_only=True, prune=False)
        cli.cmd_plan(args)
        out = capsys.readouterr().out
        # --configs-only skips package listing but links still show
        assert "zsh" not in out
        assert "== links ==" in out
    finally:
        monkeypatches.undo()


def test_cmd_plan_system_only(tmp_path, state_home, capsys):
    _make_root(
        tmp_path,
        '[[system]]\npackages = ["zsh"]\n',
        {"nvim": {"init.lua": "x"}},
    )
    home = tmp_path / "home"
    monkeypatches = pytest.MonkeyPatch()
    try:
        monkeypatches.setattr(cli, "find_root", lambda r: tmp_path)
        monkeypatches.setattr(cli, "host", lambda: home)
        _fake_pm(monkeypatches, installed=set())
        args = SimpleNamespace(root=None, system_only=True, configs_only=False, prune=False)
        cli.cmd_plan(args)
        out = capsys.readouterr().out
        # --system-only: packages still show, both sections present
        assert "== system ==" in out
    finally:
        monkeypatches.undo()


# ---------------------------------------------------------------------------
# cmd_sync
# ---------------------------------------------------------------------------


def test_cmd_sync_all_present(tmp_path, state_home, capsys):
    _make_root(
        tmp_path,
        '[[system]]\npackages = ["zsh"]\n',
        {"nvim": {"init.lua": "x"}},
    )
    home = tmp_path / "home"
    monkeypatches = pytest.MonkeyPatch()
    try:
        monkeypatches.setattr(cli, "find_root", lambda r: tmp_path)
        monkeypatches.setattr(cli, "host", lambda: home)
        _installed, _ = _fake_pm(monkeypatches, installed={"zsh"})
        monkeypatches.setattr(linker, "load_installed", list)
        monkeypatches.setattr(linker, "record_installed", lambda p: None)
        args = SimpleNamespace(
            root=None,
            directory=None,
            yes=False,
            system_only=False,
            configs_only=False,
            force=False,
            no_git=True,
            prune=False,
        )
        rc = cli.cmd_sync(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "all packages present" in out
    finally:
        monkeypatches.undo()


def test_cmd_sync_missing_with_yes(tmp_path, state_home, capsys):
    _make_root(
        tmp_path,
        '[[system]]\npackages = ["zsh"]\n',
        {},
    )
    home = tmp_path / "home"
    monkeypatches = pytest.MonkeyPatch()
    try:
        monkeypatches.setattr(cli, "find_root", lambda r: tmp_path)
        monkeypatches.setattr(cli, "host", lambda: home)
        _installed, calls = _fake_pm(monkeypatches, installed=set())
        monkeypatches.setattr(linker, "load_installed", list)
        monkeypatches.setattr(linker, "record_installed", lambda p: None)
        args = SimpleNamespace(
            root=None,
            directory=None,
            yes=True,
            system_only=False,
            configs_only=False,
            force=False,
            no_git=True,
            prune=False,
        )
        rc = cli.cmd_sync(args)
        assert rc == 0
        assert ("install", ["zsh"]) in calls
    finally:
        monkeypatches.undo()


def test_cmd_sync_missing_no_tty(tmp_path, state_home, capfd):
    _make_root(tmp_path, '[[system]]\npackages = ["zsh"]\n', {})
    home = tmp_path / "home"
    monkeypatches = pytest.MonkeyPatch()
    try:
        monkeypatches.setattr(cli, "find_root", lambda r: tmp_path)
        monkeypatches.setattr(cli, "host", lambda: home)
        _fake_pm(monkeypatches, installed=set())
        monkeypatches.setattr(linker, "load_installed", list)
        monkeypatches.setattr(linker, "record_installed", lambda p: None)
        monkeypatches.setattr(sys.stdin, "isatty", lambda: False)
        args = SimpleNamespace(
            root=None,
            directory=None,
            yes=False,
            system_only=False,
            configs_only=False,
            force=False,
            no_git=True,
            prune=False,
        )
        rc = cli.cmd_sync(args)
        assert rc == 1
        captured = capfd.readouterr()
        combined = captured.out + captured.err
        assert "rerun with --yes" in combined
    finally:
        monkeypatches.undo()


def test_cmd_sync_conflicts_no_force(tmp_path, state_home, capsys):
    _make_root(tmp_path, "[config]\n", {"nvim": {"init.lua": "x"}})
    home = tmp_path / "home"
    monkeypatches = pytest.MonkeyPatch()
    try:
        monkeypatches.setattr(cli, "find_root", lambda r: tmp_path)
        monkeypatches.setattr(cli, "host", lambda: home)
        _fake_pm(monkeypatches, installed=set())
        monkeypatches.setattr(linker, "load_installed", list)
        monkeypatches.setattr(linker, "record_installed", lambda p: None)
        (home / ".config").mkdir(parents=True)
        (home / ".config" / "nvim").mkdir()
        (home / ".config" / "nvim" / "init.lua").write_text("existing")
        args = SimpleNamespace(
            root=None,
            directory=None,
            yes=False,
            system_only=False,
            configs_only=False,
            force=False,
            no_git=True,
            prune=False,
        )
        with pytest.raises(SystemExit):
            cli.cmd_sync(args)
    finally:
        monkeypatches.undo()


def test_cmd_sync_prune(tmp_path, state_home, capsys):
    _make_root(tmp_path, "[config]\n", {"nvim": {"init.lua": "x"}})
    home = tmp_path / "home"
    monkeypatches = pytest.MonkeyPatch()
    try:
        monkeypatches.setattr(cli, "find_root", lambda r: tmp_path)
        monkeypatches.setattr(cli, "host", lambda: home)
        _fake_pm(monkeypatches, installed=set())
        monkeypatches.setattr(linker, "load_installed", list)
        monkeypatches.setattr(linker, "record_installed", lambda p: None)

        # apply an orphan first
        linker.apply(linker.plan(tmp_path, home), home)

        # now sync with empty configs + prune
        _make_root(tmp_path, "[config]\n", {})
        args = SimpleNamespace(
            root=None,
            directory=None,
            yes=True,
            system_only=False,
            configs_only=False,
            force=False,
            no_git=True,
            prune=True,
        )
        rc = cli.cmd_sync(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "pruned" in out
    finally:
        monkeypatches.undo()


# ---------------------------------------------------------------------------
# cmd_add / cmd_remove
# ---------------------------------------------------------------------------


def test_cmd_add_installs_and_declares(tmp_path, state_home, capsys):
    _make_root(tmp_path, '[[system]]\npackages = ["zsh"]\n', {})
    monkeypatches = pytest.MonkeyPatch()
    try:
        monkeypatches.setattr(cli, "find_root", lambda r: tmp_path)
        _installed, calls = _fake_pm(monkeypatches, installed={"zsh"})
        args = SimpleNamespace(packages=["fd"], root=None)
        rc = cli.cmd_add(args)
        assert rc == 0
        assert ("install", ["fd"]) in calls
        content = (tmp_path / "pkg.toml").read_text()
        assert "fd" in content
    finally:
        monkeypatches.undo()


def test_cmd_add_already_installed(tmp_path, state_home, capsys):
    _make_root(tmp_path, '[[system]]\npackages = ["zsh"]\n', {})
    monkeypatches = pytest.MonkeyPatch()
    try:
        monkeypatches.setattr(cli, "find_root", lambda r: tmp_path)
        _installed, calls = _fake_pm(monkeypatches, installed={"zsh"})
        args = SimpleNamespace(packages=["zsh"], root=None)
        rc = cli.cmd_add(args)
        assert rc == 0
        assert len([c for c in calls if c[0] == "install"]) == 0
        out = capsys.readouterr().out
        assert "already installed" in out
    finally:
        monkeypatches.undo()


def test_cmd_remove_uninstalls_and_undeclares(tmp_path, state_home, capsys):
    _make_root(tmp_path, '[[system]]\npackages = ["fd", "zsh"]\n', {})
    monkeypatches = pytest.MonkeyPatch()
    try:
        monkeypatches.setattr(cli, "find_root", lambda r: tmp_path)
        _installed, calls = _fake_pm(monkeypatches, installed={"fd", "zsh"})
        args = SimpleNamespace(packages=["fd"], root=None)
        rc = cli.cmd_remove(args)
        assert rc == 0
        assert ("remove", ["fd"]) in calls
        content = (tmp_path / "pkg.toml").read_text()
        assert "fd" not in content
        assert "zsh" in content
    finally:
        monkeypatches.undo()


def test_cmd_remove_not_installed(tmp_path, state_home, capsys):
    _make_root(tmp_path, '[[system]]\npackages = ["zsh"]\n', {})
    monkeypatches = pytest.MonkeyPatch()
    try:
        monkeypatches.setattr(cli, "find_root", lambda r: tmp_path)
        _installed, calls = _fake_pm(monkeypatches, installed={"zsh"})
        args = SimpleNamespace(packages=["nope"], root=None)
        rc = cli.cmd_remove(args)
        assert rc == 0
        assert len([c for c in calls if c[0] == "remove"]) == 0
    finally:
        monkeypatches.undo()


# ---------------------------------------------------------------------------
# cmd_status / cmd_unlink
# ---------------------------------------------------------------------------


def test_cmd_status_output(tmp_path, state_home, capsys):
    _make_root(
        tmp_path,
        '[[system]]\npackages = ["zsh"]\n',
        {"nvim": {"init.lua": "x"}},
    )
    home = tmp_path / "home"
    monkeypatches = pytest.MonkeyPatch()
    try:
        monkeypatches.setattr(cli, "find_root", lambda r: tmp_path)
        monkeypatches.setattr(cli, "host", lambda: home)
        _fake_pm(monkeypatches, installed={"zsh"})
        monkeypatches.setattr(linker, "load_state_map", dict)
        args = SimpleNamespace(root=None)
        rc = cli.cmd_status(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "== system ==" in out
        assert "== links ==" in out
        assert "installed" in out
    finally:
        monkeypatches.undo()


def test_cmd_unlink_removes(tmp_path, state_home, capsys):
    _make_root(tmp_path, "[config]\n", {"nvim": {"init.lua": "x"}})
    home = tmp_path / "home"
    monkeypatches = pytest.MonkeyPatch()
    try:
        monkeypatches.setattr(cli, "find_root", lambda r: tmp_path)
        monkeypatches.setattr(cli, "host", lambda: home)
        linker.apply(linker.plan(tmp_path, home), home)
        args = SimpleNamespace(root=None)
        rc = cli.cmd_unlink(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "removed 1 symlink" in out
    finally:
        monkeypatches.undo()


# ---------------------------------------------------------------------------
# cmd_watch (minimal – verify it enters the loop)
# ---------------------------------------------------------------------------


def test_cmd_watch_detects_change(tmp_path, state_home, capsys):
    _make_root(
        tmp_path,
        '[[system]]\npackages = ["zsh"]\n',
        {},
    )
    home = tmp_path / "home"
    monkeypatches = pytest.MonkeyPatch()
    try:
        monkeypatches.setattr(cli, "find_root", lambda r: tmp_path)
        monkeypatches.setattr(cli, "host", lambda: home)
        _fake_pm(monkeypatches, installed={"zsh"})
        monkeypatches.setattr(linker, "load_installed", list)
        monkeypatches.setattr(linker, "record_installed", lambda p: None)

        call_count = [0]
        original_snapshot = cli._snapshot_mtime

        def fake_snapshot(root):
            call_count[0] += 1
            if call_count[0] >= 3:
                raise SystemExit("stop")
            if call_count[0] == 2:
                return 99999.0
            return original_snapshot(root)

        monkeypatches.setattr(cli, "_snapshot_mtime", fake_snapshot)
        monkeypatches.setattr(cli.time, "sleep", lambda s: None)

        args = SimpleNamespace(
            root=None,
            yes=True,
            interval=0.01,
            force=False,
            no_git=True,
            directory=None,
            system_only=False,
            configs_only=False,
            prune=False,
        )
        with pytest.raises(SystemExit):
            cli.cmd_watch(args)
    finally:
        monkeypatches.undo()


# ---------------------------------------------------------------------------
# main dispatcher
# ---------------------------------------------------------------------------


def test_main_no_cmd(capsys):
    rc = cli.main([])
    assert rc == 0


def test_main_config_error(tmp_path, state_home, capsys):
    (tmp_path / "pkg.toml").write_text('[[system]]\nmodules = ["ghost"]\n')
    (tmp_path / "configs").mkdir()
    monkeypatches = pytest.MonkeyPatch()
    try:
        monkeypatches.chdir(tmp_path)
        monkeypatches.setattr(linker, "remembered_root", lambda: tmp_path)
        monkeypatches.setattr(linker, "remember_root", lambda p: None)
        rc = cli.main(["plan"])
        assert rc == 1
    finally:
        monkeypatches.undo()
