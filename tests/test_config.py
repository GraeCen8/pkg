import textwrap
from pathlib import Path

import pytest

from pkg import config as cfg


def write_root(tmp_path: Path, text: str, modules: dict[str, str] | None = None) -> Path:
    (tmp_path / "pkg.toml").write_text(textwrap.dedent(text).lstrip())
    (tmp_path / "configs").mkdir(exist_ok=True)
    for name, content in (modules or {}).items():
        module = tmp_path / name
        module.mkdir(exist_ok=True)
        (module / "pkg.toml").write_text(content)
        (module / "configs").mkdir(exist_ok=True)
    return tmp_path


def test_default_mode_is_pkg(tmp_path):
    d = write_root(tmp_path, "[config]\n")
    root = cfg.Root.load(d)
    assert root.mode == "pkg"
    assert root.stow == []


def test_invalid_mode_rejected(tmp_path):
    d = write_root(tmp_path, '[config]\nmode = "oops"\n')
    with pytest.raises(cfg.ConfigError):
        cfg.Root.load(d)


def test_manager_override(tmp_path):
    d = write_root(tmp_path, '[manager]\nname = "apt"\n')
    assert cfg.Root.load(d).manager == "apt"


def test_system_entries_and_hooks(tmp_path):
    text = """
    [[system]]
    name = "base"
    packages = ["zsh", "fd"]

    [hooks]
    post = ["echo hi"]
    """
    root = cfg.Root.load(write_root(tmp_path, text))
    assert [p for s in root.systems for p in s.packages] == ["zsh", "fd"]
    assert root.post_hooks == ["echo hi"]


def test_os_filter(monkeypatch, tmp_path):
    text = """
    [[system]]
    os = ["darwin"]
    packages = ["brew-only"]

    [[system]]
    os = ["linux"]
    packages = ["apt-only"]

    [[system]]
    packages = ["everywhere"]
    """
    cfg.Root.load(write_root(tmp_path, text))
    monkeypatch.setattr(cfg, "host_os", lambda: "linux")
    assert cfg.all_packages(tmp_path) == ["apt-only", "everywhere"]
    monkeypatch.setattr(cfg, "host_os", lambda: "darwin")
    assert cfg.all_packages(tmp_path) == ["brew-only", "everywhere"]


def test_modules_run_before_root(tmp_path):
    modules = {"nvim": "[config]\n", "kitty": "[config]\n"}
    d = write_root(tmp_path, '[modules]\non = ["nvim", "kitty"]\n', modules)
    order = cfg.roots_in_order(d)
    assert [r.dir.name for r in order] == ["nvim", "kitty", d.name]


def test_nested_modules_depth_first(tmp_path):
    modules = {
        "nvim": '[modules]\non = ["vim"]\n',
        "nvim/vim": "[config]\n",
    }
    d = write_root(tmp_path, '[modules]\non = ["nvim"]\n', modules)
    order = cfg.roots_in_order(d)
    assert [r.dir.name for r in order] == ["vim", "nvim", d.name]
    assert [r.top for r in order] == [False, False, True]


def test_enabled_missing_module_errors(tmp_path):
    d = write_root(tmp_path, '[modules]\non = ["ghost"]\n')
    with pytest.raises(cfg.ConfigError):
        cfg.roots_in_order(d)


def test_git_url_and_vars(tmp_path):
    text = """
    [git]
    url = "https://example.com/dots.git"

    [config]
    vars = { editor = "nvim" }
    """
    root = cfg.Root.load(write_root(tmp_path, text))
    assert root.git_url == "https://example.com/dots.git"
    assert root.template_vars == {"editor": "nvim"}


def test_top_only_manager_warns(tmp_path, capsys):
    modules = {"m": '[manager]\nname = "pacman"\n'}
    d = write_root(tmp_path, '[modules]\non = ["m"]\n', modules)
    cfg.roots_in_order(d)
    assert "applies only at the top root" in capsys.readouterr().err
