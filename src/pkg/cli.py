from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from pkg import __version__, linker
from pkg import config as cfg
from pkg import pms as pms_mod

TEMPLATE = """[config]
mode = "pkg"
# stow = ["zsh"]       # these configs mirror into $HOME (GNU stow style)
# mode = "stow"        # make every config stow-style

# [modules]
# on = ["nvim"]        # top-level dirs that are their own roots
#                      # (own pkg.toml + configs/)

# [[system]]
# name = "base"
# packages = []

# [hooks]
# post = []
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pkg",
        description="Declarative wraparound: system packages + symlinks",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="show what would change, no side effects")
    p.add_argument("--system-only", action="store_true")
    p.add_argument("--configs-only", action="store_true")

    s = sub.add_parser("sync", help="sync the machine to the manifest")
    s.add_argument("-y", "--yes", action="store_true")
    s.add_argument("--system-only", action="store_true")
    s.add_argument("--configs-only", action="store_true")
    s.add_argument("--force", action="store_true")

    sub.add_parser("status", help="show package and link state")
    sub.add_parser("unlink", help="remove only symlinks pkg created")

    i = sub.add_parser("init", help="scaffold a root: pkg.toml + configs/")
    i.add_argument("--force", action="store_true")

    for sp in sub.choices.values():
        sp.add_argument(
            "-R",
            "--root",
            default=None,
            help="root dir (default: cwd, else ~/dots)",
        )
    return parser


def find_root(explicit: str | None) -> Path:
    if explicit:
        d = Path(explicit).expanduser()
    elif Path("pkg.toml").is_file():
        d = Path.cwd()
    else:
        d = cfg.ROOT_DEFAULT
    d = d.resolve()
    if not (d / "pkg.toml").is_file():
        sys.exit(f"{d}: no pkg.toml found (run `pkg init` to create one)")
    return d


def get_manager(root_dir: Path) -> pms_mod.PackageManager:
    return pms_mod.detect(cfg.Root.load(root_dir, top=True).manager)


def host() -> Path:
    return Path.home()


def print_links(items: list[linker.LinkItem]) -> None:
    for item in items:
        marker = {"ok": "=", "new": "+", "conflict": "!", "broken": "?"}[linker.item_status(item)]
        print(f"  {marker} {item.target}")


def cmd_plan(args: argparse.Namespace) -> int:
    root_dir = find_root(args.root)
    home = host()
    manager = get_manager(root_dir)
    print(f"manager: {manager.label}")
    print("== system ==")
    problems: list[str] = []
    if not args.configs_only:
        for pkg in manager.check_many(cfg.all_packages(root_dir)):
            print(f"  + {pkg}")
        if manager.check_many(cfg.all_packages(root_dir)):
            problems.append("packages to install")
    print("== links ==")
    items = linker.plan(root_dir, home)
    print_links(items)
    problems.extend(linker.find_conflicts(items, home))
    for problem in problems:
        print(f"  ! {problem}", file=sys.stderr)
    return 1 if problems else 0


def cmd_sync(args: argparse.Namespace) -> int:
    root_dir = find_root(args.root)
    home = host()
    manager = get_manager(root_dir)

    if not args.configs_only:
        missing = manager.check_many(cfg.all_packages(root_dir))
        if missing:
            print(f"[system] {len(missing)} packages to install: {', '.join(missing)}")
            if args.yes:
                if manager.install(missing):
                    sys.exit("[system] install failed")
            elif sys.stdin.isatty():
                answer = input("Install these packages? [y/N] ")
                if answer.lower() not in ("y", "yes"):
                    print("aborted")
                    return 1
                if manager.install(missing):
                    sys.exit("[system] install failed")
            else:
                sys.exit("[system] packages missing: rerun with --yes")
        else:
            print("[system] all packages present")

    if not args.system_only:
        items = linker.plan(root_dir, home)
        problems = linker.find_conflicts(items, home)
        if problems and not args.force:
            print("conflicts:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            sys.exit("aborting; use --force to replace")
        try:
            created = linker.apply(items, home, force=args.force)
        except linker.ConflictError as exc:
            sys.exit(f"error: {exc}")
        for item in created:
            print(f"  + {item.target}")
        if not created:
            print("[links] all targets already linked")
        if problems:
            print(f"[links] replaced {len(problems)} existing target(s)")

    roots = cfg.roots_in_order(root_dir)
    for root in roots:
        for hook in root.post_hooks:
            print(f"[hook] {hook}")
            if subprocess.run(["sh", "-c", hook], check=False).returncode != 0:
                sys.exit(f"hook failed: {hook}")
    print("in sync")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root_dir = find_root(args.root)
    home = host()
    manager = get_manager(root_dir)
    print(f"manager: {manager.label}")
    print("== system ==")
    for pkg in cfg.all_packages(root_dir):
        state = "installed" if manager.check(pkg) else "missing"
        print(f"  {state:10} {pkg}")
    print("== links ==")
    items = linker.plan(root_dir, home)
    print_links(items)
    wanted = {str(item.target) for item in items}
    stale = [target for target in linker.load_state_map() if target not in wanted]
    for target in stale:
        print(f"  - {target} (not in manifest)")
    return 0


def cmd_unlink(args: argparse.Namespace) -> int:
    print(f"removed {linker.unlink(host())} symlink(s)")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    d = Path(args.root or cfg.ROOT_DEFAULT).expanduser().resolve()
    (d / "configs").mkdir(parents=True, exist_ok=True)
    pkg_toml = d / "pkg.toml"
    if pkg_toml.exists() and not args.force:
        print(f"{pkg_toml}: already exists (use --force to overwrite)")
    else:
        pkg_toml.write_text(TEMPLATE)
        print(f"wrote {pkg_toml}")
    print(f"layout: {d}")
    print("        configs/")
    print("drop configs into configs/, then run `pkg sync`")
    return 0


_COMMANDS = {
    "plan": cmd_plan,
    "sync": cmd_sync,
    "status": cmd_status,
    "unlink": cmd_unlink,
    "init": cmd_init,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _COMMANDS[args.cmd](args)
    except cfg.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
