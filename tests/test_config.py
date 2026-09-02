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
    d = write_root(tmp_path, '[[system]]\nmodules = ["nvim", "kitty"]\n', modules)
    order = cfg.roots_in_order(d)
    assert [r.dir.name for r in order] == ["nvim", "kitty", d.name]


def test_nested_modules_depth_first(tmp_path):
    modules = {
        "nvim": '[[system]]\nmodules = ["vim"]\n',
        "nvim/vim": "[config]\n",
    }
    d = write_root(tmp_path, '[[system]]\nmodules = ["nvim"]\n', modules)
    order = cfg.roots_in_order(d)
    assert [r.dir.name for r in order] == ["vim", "nvim", d.name]
    assert [r.top for r in order] == [False, False, True]


def test_enabled_missing_module_errors(tmp_path):
    d = write_root(tmp_path, '[[system]]\nmodules = ["ghost"]\n')
    with pytest.raises(cfg.ConfigError):
        cfg.roots_in_order(d)


def test_modules_respect_profiles(tmp_path):
    text = """
    [config]
    profiles = ["work"]

    [[system]]
    profiles = ["work"]
    modules = ["work-mod"]

    [[system]]
    profiles = ["home"]
    modules = ["home-mod"]
    """
    modules = {"work-mod": "[config]\n", "home-mod": "[config]\n"}
    d = write_root(tmp_path, text, modules)
    order = cfg.roots_in_order(d)
    names = [r.dir.name for r in order]
    assert "work-mod" in names
    assert "home-mod" not in names


def test_modules_respect_os(monkeypatch, tmp_path):
    text = """
    [[system]]
    os = ["linux"]
    modules = ["linux-mod"]

    [[system]]
    os = ["darwin"]
    modules = ["mac-mod"]
    """
    modules = {"linux-mod": "[config]\n", "mac-mod": "[config]\n"}
    d = write_root(tmp_path, text, modules)
    monkeypatch.setattr(cfg, "host_os", lambda: "linux")
    order = cfg.roots_in_order(d)
    names = [r.dir.name for r in order]
    assert "linux-mod" in names
    assert "mac-mod" not in names


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
    d = write_root(tmp_path, '[[system]]\nmodules = ["m"]\n', modules)
    cfg.roots_in_order(d)
    assert "applies only at the top root" in capsys.readouterr().err


def test_profiles_and_other_fields(tmp_path):
    text = """
    [config]
    profiles = ["work"]
    ignore = ["**/*.swp", ".git"]

    [git]
    autocommit = true
    """
    root = cfg.Root.load(write_root(tmp_path, text))
    assert root.profiles == ["work"]
    assert root.ignore == ["**/*.swp", ".git"]
    assert root.git_autocommit is True


def test_profile_blocks_filter_packages(monkeypatch, tmp_path):
    text = """
    [[system]]
    profiles = ["work"]
    packages = ["docker"]

    [[system]]
    packages = ["everywhere"]
    """
    d = write_root(tmp_path, '[config]\nprofiles = ["work"]\n' + text)
    assert cfg.all_packages(d) == ["docker", "everywhere"]
    d2 = write_root(tmp_path, "[config]\n" + text)
    assert cfg.all_packages(d2) == ["everywhere"]


def test_remove_from_profile_matching_block(monkeypatch, tmp_path):
    text = """
    [config]
    profiles = ["work"]

    [[system]]
    profiles = ["work"]
    packages = ["rg", "fd"]
    """
    d = write_root(tmp_path, text)
    before, after = cfg.remove_packages(_toml(d), ["rg"])
    assert (before, after) == (["rg", "fd"], ["fd"])
    assert 'packages = ["fd"]' in _toml(d).read_text()


def test_remove_ignores_other_profile_blocks(monkeypatch, tmp_path):
    text = """
    [config]
    profiles = ["work"]

    [[system]]
    profiles = ["home"]
    packages = ["xps-only"]

    [[system]]
    packages = ["zsh"]
    """
    d = write_root(tmp_path, text)
    before, after = cfg.remove_packages(_toml(d), ["xps-only"])
    assert (before, after) == ([], [])
    assert "xps-only" in _toml(d).read_text()


def test_add_skips_profile_blocks(tmp_path):
    text = """
    [[system]]
    profiles = ["work"]
    packages = ["docker"]

    [[system]]
    packages = ["zsh"]
    """
    d = write_root(tmp_path, text)
    cfg.add_packages(_toml(d), ["fd"])
    content = _toml(d).read_text()
    assert 'name = "base"' not in content or 'packages = ["fd", "zsh"]' in content
    assert 'packages = ["docker"]' in content


def _toml(tmp_path) -> Path:
    return tmp_path / "pkg.toml"


def test_add_packages_creates_block(tmp_path):
    cfg.add_packages(_toml(write_root(tmp_path, "[config]\n")), ["fd", "zsh"])
    text = _toml(tmp_path).read_text()
    assert 'name = "base"' in text
    assert 'packages = ["fd", "zsh"]' in text


def test_add_packages_edits_existing(tmp_path):
    d = write_root(tmp_path, '[[system]]\nname = "base"\npackages = ["zsh"]\n')
    before, after = cfg.add_packages(_toml(d), ["fd"])
    assert (before, after) == (["zsh"], ["fd", "zsh"])
    assert 'name = "base"' in _toml(d).read_text()


def test_add_packages_multiline_array(tmp_path):
    text = """
    [[system]]
    name = "base"
    packages = [
        "zsh",
        "fd",
    ]
    [hooks]
    post = ["echo hi"]
    """
    d = write_root(tmp_path, text)
    before, after = cfg.add_packages(_toml(d), ["rg"])
    assert (before, after) == (["zsh", "fd"], ["fd", "rg", "zsh"])
    content = _toml(d).read_text()
    assert 'packages = ["fd", "rg", "zsh"]' in content
    assert "echo hi" in content


def test_add_packages_keeps_os_filtered_untouched(tmp_path):
    text = """
    [[system]]
    os = ["darwin"]
    packages = ["brew-only"]

    [[system]]
    packages = ["zsh"]
    """
    d = write_root(tmp_path, text)
    cfg.add_packages(_toml(d), ["fd"])
    content = _toml(d).read_text()
    assert "brew-only" in content
    assert 'os = ["darwin"]' in content
    assert 'packages = ["fd", "zsh"]' in content


def test_add_packages_creates_unfiltered_when_only_os_blocks(tmp_path):
    text = """
    [[system]]
    os = ["linux"]
    packages = ["rg"]
    """
    d = write_root(tmp_path, text)
    before, after = cfg.add_packages(_toml(d), ["fd"])
    assert (before, after) == ([], ["fd"])
    content = _toml(d).read_text()
    assert content.count("[[system]]") == 2
    assert 'packages = ["fd"]' in content


def test_remove_packages_empties_list(tmp_path):
    text = '[[system]]\nname = "base"\npackages = ["zsh", "fd"]\n'
    d = write_root(tmp_path, text)
    before, after = cfg.remove_packages(_toml(d), ["zsh"])
    assert (before, after) == (["zsh", "fd"], ["fd"])
    before, after = cfg.remove_packages(_toml(d), ["fd"])
    assert (before, after) == (["fd"], [])
    assert "packages = []" in _toml(d).read_text()


def test_remove_from_os_matching_block(monkeypatch, tmp_path):
    text = """
    [[system]]
    os = ["linux"]
    packages = ["rg", "fd"]
    """
    d = write_root(tmp_path, text)
    monkeypatch.setattr(cfg, "host_os", lambda: "linux")
    before, after = cfg.remove_packages(_toml(d), ["rg"])
    assert (before, after) == (["rg", "fd"], ["fd"])
    assert 'packages = ["fd"]' in _toml(d).read_text()


def test_remove_untouched_when_not_declared(monkeypatch, tmp_path):
    text = '[[system]]\nname = "base"\npackages = ["zsh"]\n[config]\nmode = "pkg"\n'
    d = write_root(tmp_path, text)
    before, after = cfg.remove_packages(_toml(d), ["nope"])
    assert (before, after) == ([], [])
    assert _toml(d).read_text() == text


def test_add_packages_multiline_when_many(tmp_path):
    text = '[[system]]\npackages = ["a", "b", "c"]\n'
    d = write_root(tmp_path, text)
    cfg.add_packages(_toml(d), ["d"])
    content = _toml(d).read_text()
    assert 'packages = [\n    "a",\n    "b",\n    "c",\n    "d",\n]' in content


def test_add_packages_singleline_when_few(tmp_path):
    text = '[[system]]\npackages = ["a"]\n'
    d = write_root(tmp_path, text)
    cfg.add_packages(_toml(d), ["b", "c"])
    content = _toml(d).read_text()
    assert 'packages = ["a", "b", "c"]' in content


def test_remove_packages_collapses_to_singleline(tmp_path):
    text = '[[system]]\npackages = [\n    "a",\n    "b",\n    "c",\n    "d",\n]\n'
    d = write_root(tmp_path, text)
    cfg.remove_packages(_toml(d), ["a", "b"])
    content = _toml(d).read_text()
    assert 'packages = ["c", "d"]' in content


def test_add_packages_preserves_comments(tmp_path):
    text = '[[system]]\npackages = [\n    "a",\n    # tools\n    "b",\n]\n'
    d = write_root(tmp_path, text)
    cfg.add_packages(_toml(d), ["c", "d"])
    content = _toml(d).read_text()
    assert "# tools" in content
    assert '"a"' in content
    assert '"b"' in content
    assert '"c"' in content
    assert '"d"' in content


def test_remove_packages_preserves_comments(tmp_path):
    text = '[[system]]\npackages = [\n    "a",\n    # keep this\n    "b",\n    "c",\n    "d",\n    "e",\n]\n'
    d = write_root(tmp_path, text)
    cfg.remove_packages(_toml(d), ["a"])
    content = _toml(d).read_text()
    assert "# keep this" in content
    assert '"b"' in content
    assert '"c"' in content
    assert '"d"' in content
    assert '"e"' in content
    assert '"a"' not in content


def test_add_packages_preserves_section_comments(tmp_path):
    text = """\
[[system]]
packages = [
    "bat",
    # apps
    "kitty",
    # langs
    "python",
    "rustup",
    # lsps
    "pyright",
    "rust-analyzer",
]
"""
    d = write_root(tmp_path, text)
    cfg.add_packages(_toml(d), ["go", "zls"])
    content = _toml(d).read_text()
    assert "# apps" in content
    assert "# langs" in content
    assert "# lsps" in content
    assert '"go"' in content
    assert '"zls"' in content
    # Comments should still appear between their associated packages,
    # not be lumped together at the top
    apps_pos = content.index("# apps")
    langs_pos = content.index("# langs")
    lsps_pos = content.index("# lsps")
    assert apps_pos < langs_pos < lsps_pos
