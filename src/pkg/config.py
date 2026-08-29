"""Manifest parsing, root resolution, and package list aggregation."""

from __future__ import annotations

import json
import platform
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DEFAULT = Path("~/dots").expanduser()


class ConfigError(Exception):
    """Raised when the manifest or directory layout is invalid."""


def host_os() -> str:
    """Return the current OS name in lowercase (e.g. ``'linux'``, ``'darwin'``)."""
    return platform.system().lower()


@dataclass
class SystemEntry:
    """A single ``[[system]]`` block declaring packages, modules, and filters."""

    name: str
    packages: list[str]
    modules: list[str] = field(default_factory=list)
    os: list[str] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)

    def applies(self, active_profiles: list[str] | None = None) -> bool:
        """Return True if this entry matches the current OS and profiles."""
        if self.os and host_os() not in {o.lower() for o in self.os}:
            return False
        return not (
            self.profiles and not (set(active_profiles or []) & set(self.profiles))
        )


@dataclass
class Root:
    """Parsed representation of a root ``pkg.toml`` and its settings."""

    dir: Path
    manager: str | None
    modules: list[str]
    stow: list[str]
    mode: str
    systems: list[SystemEntry]
    post_hooks: list[str]
    git_url: str | None = None
    template_vars: dict = field(default_factory=dict)
    profiles: list[str] = field(default_factory=list)
    ignore: list[str] = field(default_factory=list)
    git_autocommit: bool = False
    top: bool = True
    pkgs_map: dict = field(default_factory=dict)

    @classmethod
    def load(cls, root_dir: Path, top: bool = True) -> Root:
        """Load and parse a ``pkg.toml`` from *root_dir*.

        Args:
            root_dir: Directory containing ``pkg.toml``.
            top: Whether this is the top-level root (only the top root
                may declare ``[manager]``).

        Returns:
            A populated Root dataclass.

        Raises:
            ConfigError: If the manifest is missing or has invalid fields.
        """
        pkg_toml = root_dir / "pkg.toml"
        if not pkg_toml.is_file():
            raise ConfigError(f"{root_dir}: no pkg.toml found")
        with open(pkg_toml, "rb") as fh:
            data = tomllib.load(fh)
        manager = (data.get("manager") or {}).get("name") or None
        cfg = data.get("config") or {}
        stow = [s for s in cfg.get("stow", [])]
        mode = cfg.get("mode", "pkg")
        if mode not in ("pkg", "stow"):
            raise ConfigError(f"{pkg_toml}: config.mode must be 'pkg' or 'stow', got {mode!r}")
        template_vars = dict(cfg.get("vars", {}))
        systems = [
            SystemEntry(
                name=e.get("name", "default"),
                packages=[p for p in e.get("packages", [])],
                modules=[m for m in e.get("modules", [])],
                os=[o for o in e.get("os", [])],
                profiles=[p for p in e.get("profiles", [])],
            )
            for e in data.get("system", [])
        ]
        hooks = [h for h in (data.get("hooks") or {}).get("post", [])]
        git = data.get("git") or {}
        git_url = git.get("url") or None
        git_autocommit = bool(git.get("autocommit"))
        pkgs_map = data.get("pkgs_map", {})
        return cls(
            dir=root_dir.resolve(),
            manager=manager,
            modules=[],
            stow=stow,
            mode=mode,
            systems=systems,
            post_hooks=hooks,
            git_url=git_url,
            template_vars=template_vars,
            profiles=list(cfg.get("profiles", [])),
            ignore=list(cfg.get("ignore", [])),
            git_autocommit=git_autocommit,
            top=top,
            pkgs_map=pkgs_map,
        )


def _active_modules(root: Root) -> list[str]:
    """Return the deduplicated list of module names enabled by applicable system blocks."""
    seen: set[str] = set()
    result: list[str] = []
    for entry in root.systems:
        if entry.applies(root.profiles):
            for m in entry.modules:
                if m not in seen:
                    seen.add(m)
                    result.append(m)
    return result


def roots_in_order(root_dir: Path) -> list[Root]:
    """Return all roots (including modules) in depth-first apply order.

    Modules are visited before their parent, so the returned list is safe
    to iterate in order for syncing.

    Args:
        root_dir: Path to the top-level root directory.

    Returns:
        List of Root objects in depth-first, modules-before-parent order.

    Raises:
        ConfigError: If a declared module directory or its ``pkg.toml`` is missing.
    """
    order: list[Root] = []

    def visit(d: Path, top: bool) -> None:
        root = Root.load(d, top)
        root.modules = _active_modules(root)
        if not root.top and root.manager:
            print(
                f"warning: {root.dir}/pkg.toml: [manager] applies only at the top root; ignored",
                file=sys.stderr,
            )
        for name in root.modules:
            module_dir = d / name
            if not module_dir.is_dir():
                raise ConfigError(f"{d}: enabled module {name!r} not found")
            visit(module_dir, top=False)
        order.append(root)

    visit(root_dir, top=True)
    return order


def resolve_package_name(pkg: str, manager: str, pkgs_map: dict) -> str:
    """Map a package name through ``[pkgs_map]`` for the given manager.

    If *pkg* has a mapping for *manager* in *pkgs_map*, return the
    mapped name; otherwise return *pkg* unchanged.
    """
    if pkg in pkgs_map:
        mapped = pkgs_map[pkg]
        if isinstance(mapped, dict) and manager in mapped:
            return mapped[manager]
    return pkg

def all_packages(root_dir: Path, manager: str | None = None) -> list[str]:
    """Collect the deduplicated, ordered list of all packages across all roots.

    Applies OS and profile filters, resolves ``[pkgs_map]`` mappings, and
    preserves insertion order.

    Args:
        root_dir: Path to the top-level root directory.
        manager: Package manager name for mapping. Auto-detected if None.

    Returns:
        List of unique package names in declaration order.
    """
    active = Root.load(root_dir, top=True).profiles
    roots = roots_in_order(root_dir)
    # find package manager (string) if not given
    if manager is None:
        from pkg import pms as pms_mod
        mgr = pms_mod.detect(Root.load(root_dir, top=True).manager)
        manager = mgr.name
    packages: list[str] = []
    for root in roots:
        pkgs_map = root.pkgs_map if hasattr(root, 'pkgs_map') else {}
        for entry in root.systems:
            if entry.applies(active):
                for pkg in entry.packages:
                    mapped_pkg = resolve_package_name(pkg, manager, pkgs_map)
                    if mapped_pkg not in packages:
                        packages.append(mapped_pkg)
    return packages


def _system_block_ranges(lines: list[str]) -> list[tuple[int, int]]:
    """Return (start, end) line ranges for each ``[[system]]`` block."""
    starts = [i for i, line in enumerate(lines) if line.strip() == "[[system]]"]
    return [
        (start, starts[k + 1] if k + 1 < len(starts) else len(lines))
        for k, start in enumerate(starts)
    ]


def _unfiltered_block_index(data: dict) -> int | None:
    """Return the index of the first ``[[system]]`` block with no OS or profile filters."""
    blocks = data.get("system")
    if not isinstance(blocks, list):
        return None
    for i, block in enumerate(blocks):
        if isinstance(block, dict) and "os" not in block and "profiles" not in block:
            return i
    return None


def _os_matches(values: list[str]) -> bool:
    """Return True if any value in *values* matches the current OS."""
    h = host_os()
    return any(h == v.lower() for v in values)


def _profiles_match(block_profiles: list[str], active: list[str]) -> bool:
    """Return True if *block_profiles* overlaps with *active* profiles (or block has none)."""
    if not block_profiles:
        return True
    return bool(set(active) & set(block_profiles))


def _remove_block_index(data: dict, packages: list[str], active_profiles: list[str]) -> int | None:
    """Return the index of the first ``[[system]]`` block containing any of *packages*."""
    blocks = data.get("system")
    if not isinstance(blocks, list):
        return None
    for i, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        hits = any(p in block.get("packages", []) for p in packages)
        os_ok = not block.get("os") or _os_matches(block["os"])
        profiles_ok = _profiles_match(list(block.get("profiles", [])), active_profiles)
        if hits and os_ok and profiles_ok:
            return i
    return None


def _extract_array_comments(lines: list[str], start: int, end: int) -> list[str]:
    """Extract comment lines from within a packages = [...] array range."""
    comments = []
    for i in range(start, end):
        stripped = lines[i].strip()
        if stripped.startswith("#"):
            comments.append(stripped)
    return comments


def _format_packages_array(packages: list[str], comments: list[str] | None = None) -> str:
    """Format a packages list as single-line or multi-line TOML array.

    Uses multi-line format when there are more than 3 items.
    Preserves comments from the original array.
    """
    if len(packages) <= 3:
        return f"packages = {json.dumps(packages)}"

    items = list(packages)
    if comments:
        items = items[:len(comments)] + comments + items[len(comments):]
    indent = "    "
    inner = "\n".join(f'{indent}"{p}",' for p in items)
    return f"packages = [\n{inner}\n]"


def _edit_packages(pkg_toml: Path, packages: list[str], add: bool) -> tuple[list[str], list[str]]:
    text = pkg_toml.read_text()
    had_newline = text.endswith("\n")
    lines = text.splitlines()
    with open(pkg_toml, "rb") as fh:
        data = tomllib.load(fh)

    active_profiles = list((data.get("config") or {}).get("profiles", []))
    idx = (
        _unfiltered_block_index(data)
        if add
        else _remove_block_index(data, packages, active_profiles)
    )
    current = [str(p) for p in data["system"][idx].get("packages", [])] if idx is not None else []
    if add:
        new = sorted(set(current) | set(packages))
    else:
        new = sorted(set(current) - set(packages))

    if idx is None:
        if not add or current == new:
            return current, new
        if had_newline and lines and lines[-1] != "":
            lines.append("")
        lines += ["[[system]]", 'name = "base"', _format_packages_array(new)]
    else:
        start, end = _system_block_ranges(lines)[idx]
        existing_comments = _extract_array_comments(lines, start, end)
        payload = _format_packages_array(new, existing_comments)
        replaced = False
        for i in range(start, end):
            if lines[i].lstrip().startswith("packages"):
                j = i
                while "]" not in lines[j] and j + 1 < end:
                    j += 1
                lines[i : j + 1] = payload.splitlines()
                replaced = True
                break
        if not replaced:
            last = end - 1
            while last > start and lines[last].strip() == "":
                last -= 1
            for k, line in enumerate(payload.splitlines()):
                lines.insert(last + 1 + k, line)

    pkg_toml.write_text("\n".join(lines) + ("\n" if had_newline else ""))
    return current, new


def add_packages(pkg_toml: Path, packages: list[str]) -> tuple[list[str], list[str]]:
    """Add *packages* to the unfiltered ``[[system]]`` block in *pkg_toml*.

    Returns:
        Tuple of (before, after) package lists for the affected block.
    """
    return _edit_packages(pkg_toml, packages, add=True)


def remove_packages(pkg_toml: Path, packages: list[str]) -> tuple[list[str], list[str]]:
    """Remove *packages* from the matching ``[[system]]`` block in *pkg_toml*.

    Returns:
        Tuple of (before, after) package lists for the affected block.
    """
    return _edit_packages(pkg_toml, packages, add=False)
