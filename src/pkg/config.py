from __future__ import annotations

import json
import platform
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DEFAULT = Path("~/dots").expanduser()


class ConfigError(Exception):
    pass


def host_os() -> str:
    return platform.system().lower()


@dataclass
class SystemEntry:
    name: str
    packages: list[str]
    os: list[str] = field(default_factory=list)

    def applies(self) -> bool:
        if not self.os:
            return True
        return host_os() in {o.lower() for o in self.os}


@dataclass
class Root:
    dir: Path
    manager: str | None
    modules: list[str]
    stow: list[str]
    mode: str
    systems: list[SystemEntry]
    post_hooks: list[str]
    git_url: str | None = None
    template_vars: dict = field(default_factory=dict)
    top: bool = True

    @classmethod
    def load(cls, root_dir: Path, top: bool = True) -> Root:
        pkg_toml = root_dir / "pkg.toml"
        if not pkg_toml.is_file():
            raise ConfigError(f"{root_dir}: no pkg.toml found")
        with open(pkg_toml, "rb") as fh:
            data = tomllib.load(fh)
        manager = (data.get("manager") or {}).get("name") or None
        modules = list((data.get("modules") or {}).get("on", []))
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
                os=[o for o in e.get("os", [])],
            )
            for e in data.get("system", [])
        ]
        hooks = [h for h in (data.get("hooks") or {}).get("post", [])]
        git_url = (data.get("git") or {}).get("url") or None
        return cls(
            dir=root_dir.resolve(),
            manager=manager,
            modules=modules,
            stow=stow,
            mode=mode,
            systems=systems,
            post_hooks=hooks,
            git_url=git_url,
            template_vars=template_vars,
            top=top,
        )


def roots_in_order(root_dir: Path) -> list[Root]:
    order: list[Root] = []

    def visit(d: Path, top: bool) -> None:
        root = Root.load(d, top)
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


def all_packages(root_dir: Path) -> list[str]:
    packages: list[str] = []
    for root in roots_in_order(root_dir):
        for entry in root.systems:
            if entry.applies():
                for pkg in entry.packages:
                    if pkg not in packages:
                        packages.append(pkg)
    return packages


def _system_block_ranges(lines: list[str]) -> list[tuple[int, int]]:
    starts = [i for i, line in enumerate(lines) if line.strip() == "[[system]]"]
    return [
        (start, starts[k + 1] if k + 1 < len(starts) else len(lines))
        for k, start in enumerate(starts)
    ]


def _unfiltered_block_index(data: dict) -> int | None:
    blocks = data.get("system")
    if not isinstance(blocks, list):
        return None
    for i, block in enumerate(blocks):
        if isinstance(block, dict) and "os" not in block:
            return i
    return None


def _os_matches(values: list[str]) -> bool:
    h = host_os()
    return any(h == v.lower() for v in values)


def _remove_block_index(data: dict, packages: list[str]) -> int | None:
    blocks = data.get("system")
    if not isinstance(blocks, list):
        return None
    for i, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        hits = any(p in block.get("packages", []) for p in packages)
        if hits and (not block.get("os") or _os_matches(block["os"])):
            return i
    return None


def _edit_packages(pkg_toml: Path, packages: list[str], add: bool) -> tuple[list[str], list[str]]:
    text = pkg_toml.read_text()
    had_newline = text.endswith("\n")
    lines = text.splitlines()
    with open(pkg_toml, "rb") as fh:
        data = tomllib.load(fh)

    idx = _unfiltered_block_index(data) if add else _remove_block_index(data, packages)
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
        lines += ["[[system]]", 'name = "base"', f"packages = {json.dumps(new)}"]
    else:
        start, end = _system_block_ranges(lines)[idx]
        payload = json.dumps(new)
        replaced = False
        for i in range(start, end):
            if lines[i].lstrip().startswith("packages"):
                j = i
                while "]" not in lines[j] and j + 1 < end:
                    j += 1
                lines[i : j + 1] = [f"packages = {payload}"]
                replaced = True
                break
        if not replaced:
            last = end - 1
            while last > start and lines[last].strip() == "":
                last -= 1
            lines.insert(last + 1, f"packages = {payload}")

    pkg_toml.write_text("\n".join(lines) + ("\n" if had_newline else ""))
    return current, new


def add_packages(pkg_toml: Path, packages: list[str]) -> tuple[list[str], list[str]]:
    return _edit_packages(pkg_toml, packages, add=True)


def remove_packages(pkg_toml: Path, packages: list[str]) -> tuple[list[str], list[str]]:
    return _edit_packages(pkg_toml, packages, add=False)
