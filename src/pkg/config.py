from __future__ import annotations

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
