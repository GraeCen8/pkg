"""Command-line interface and command dispatch for pkg."""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from pathlib import Path

from pkg import __version__, colors, linker
from pkg import config as cfg
from pkg import pms as pms_mod
from pkg.colors import err, out

TEMPLATE = """[config]
mode = "pkg"
# stow = []       # these configs mirror into $HOME (GNU stow style)
# mode = "stow"        # make every config stow-style

# [[system]]
# name = "base"
# packages = []

# [hooks]
# post = []

# [git]
# url = "git@github.com:you/dots.git"
"""

_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_LINK_MARKS = {
    "ok": (out.green, "="),
    "new": (out.cyan, "+"),
    "conflict": (out.red, "!"),
    "broken": (out.yellow, "?"),
}


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser for the ``pkg`` CLI."""
    parser = argparse.ArgumentParser(
        prog="pkg",
        description="pkg tool which can it all: system packages & dotfiles",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("diff", aliases=["plan"], help="show what would change, no side effects")
    p.add_argument("--system-only", action="store_true")
    p.add_argument("--configs-only", action="store_true")
    p.add_argument("--prune", action="store_true", help="show orphaned links --prune would remove")

    s = sub.add_parser("sync", help="sync the machine to the manifest")
    s.add_argument("directory", nargs="?", default=None, help="root dir to sync")
    s.add_argument("-y", "--yes", action="store_true")
    s.add_argument("--system-only", action="store_true")
    s.add_argument("--configs-only", action="store_true")
    s.add_argument("--force", action="store_true")
    s.add_argument(
        "--no-git",
        action="store_true",
        help="skip git pulls for roots that declare [git] url",
    )
    s.add_argument("--prune", action="store_true", help="remove orphaned links / rendered files")

    sub.add_parser("status", help="show package and link state")
    sub.add_parser("unlink", help="remove only symlinks pkg created")

    w = sub.add_parser("watch", help="re-sync when pkg.toml or configs/ changes")
    w.add_argument("-y", "--yes", action="store_true")
    w.add_argument("--interval", type=float, default=2.0, help="poll interval in seconds")
    w.add_argument("--force", action="store_true")
    w.add_argument("--no-git", action="store_true")

    a = sub.add_parser("add", help="install packages and declare them in the manifest")
    a.add_argument("packages", nargs="+", metavar="NAME", help="package(s) to install + declare")

    r = sub.add_parser("remove", help="uninstall packages and undeclare them in the manifest")
    r.add_argument(
        "packages", nargs="+", metavar="NAME", help="package(s) to uninstall + undeclare"
    )

    i = sub.add_parser("init", help="scaffold a root at <dir>: pkg.toml + configs/")
    i.add_argument("target", help="dir to scaffold, e.g. ~/dots or .")
    i.add_argument("--force", action="store_true")

    for name, sp in sub.choices.items():
        if name in ("plan",):
            continue
        sp.add_argument(
            "-R",
            "--root",
            default=None,
            help="root dir (overrides the remembered root)",
        )
    return parser


def find_root(explicit: str | None) -> Path:
    """Resolve the root directory to use for a command.

    Priority: explicit ``-R``/argument > cwd if it has ``pkg.toml`` >
    remembered root > default ``~/dots``.
    """
    if explicit:
        d = Path(explicit).expanduser()
        remember = True
    elif Path("pkg.toml").is_file():
        d = Path.cwd()
        remember = True
    else:
        mem = linker.remembered_root()
        if mem and (mem / "pkg.toml").is_file():
            d = mem
            remember = True
        else:
            d = cfg.ROOT_DEFAULT
            remember = False
    d = d.resolve()
    if not (d / "pkg.toml").is_file():
        sys.exit(err.red(f"{d}: no pkg.toml found (run `pkg init <dir>` to create one)"))
    if remember:
        linker.remember_root(d)
    return d


def get_manager(root_dir: Path) -> pms_mod.PackageManager:
    """Detect the package manager for *root_dir*."""
    return pms_mod.detect(cfg.Root.load(root_dir, top=True).manager)


def host() -> Path:
    """Return the user's home directory."""
    return Path.home()


def pull_roots(root_dir: Path, root_filter: list[cfg.Root] | None = None) -> None:
    """Git-pull all roots that declare a ``[git] url``.

    Exits on failure.  If *root_filter* is provided, only those roots
    are checked.
    """
    for root in root_filter or cfg.roots_in_order(root_dir):
        if not root.git_url:
            continue
        if not (root.dir / ".git").exists():
            sys.exit(err.red(f"{root.dir}: declares [git] url but is not a git checkout"))
        print(f"  {out.cyan('~')} pull {out.dim(str(root.dir))}")
        if (
            subprocess.run(
                ["git", "-C", str(root.dir), "pull", "--ff-only"], check=False
            ).returncode
            != 0
        ):
            sys.exit(err.red(f"git pull failed for {root.dir}"))


def print_links(items: list[linker.LinkItem]) -> None:
    for item in items:
        color, mark = _LINK_MARKS[linker.item_status(item)]
        print(f"  {color(mark)} {item.target}")


def _spinner(message: str) -> threading.Event:
    stop = threading.Event()

    def spin() -> None:
        i = 0
        while not stop.is_set():
            sys.stdout.write(f"\r  {out.cyan(_SPINNER[i % len(_SPINNER)])} {message}")
            sys.stdout.flush()
            time.sleep(0.08)
            i += 1
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    threading.Thread(target=spin, daemon=True).start()
    return stop


def _spinner_run(verb: str, names: list[str], call) -> tuple[int, str]:
    """Run *call* with a spinner (interactive) or plain progress (non-interactive).

    Returns (returncode, error_message) tuple.
    """
    label = ", ".join(names)
    use_spinner = colors.enabled(sys.stdout)
    if use_spinner:
        stop = _spinner(f"{verb} {label}")
        rc, err = call()
        stop.set()
    else:
        print(f"  {verb} {label} ...", end="", flush=True)
        rc, err = call()
        if rc:
            print(f" {out.red('failed')}")
        else:
            print(f" {out.green('ok')}")
    return rc, err


def _consent(force_yes: bool, prompt: str) -> bool:
    if force_yes:
        return True
    if not sys.stdin.isatty():
        return False
    return input(f"  {prompt}").strip().lower() in ("y", "yes")


def _system_install(manager: pms_mod.PackageManager, missing: list[str]) -> int:
    rc = 0
    for pkg in missing:
        rci, err = _spinner_run("installing", [pkg], lambda p=pkg: manager.install([p]))
        if rci:
            if colors.enabled(sys.stdout):
                print(f"    {out.red('error')}: {pkg}")
            if err:
                for line in err.splitlines()[:5]:
                    print(f"      {line}")
            rc = rci
        elif colors.enabled(sys.stdout):
            print(f"  {out.green(chr(0x2713))} {pkg}")
    return rc


def _system_remove(manager: pms_mod.PackageManager, packages: list[str]) -> int:
    rc, err = _spinner_run("removing", packages, lambda: manager.remove(packages))
    if rc:
        still = [p for p in packages if manager.check(p)]
        if still:
            print(f"  {out.red('error')}: could not remove: {', '.join(still)}")
        else:
            print(out.red("  error: removal failed"))
        if err:
            for line in err.splitlines()[:5]:
                print(f"    {line}")
        return rc
    print(f"  {out.green('ok')} — removed {len(packages)} package(s)")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    """``pkg diff`` — show what sync would do without making changes."""
    root_dir = find_root(args.root)
    home = host()
    manager = get_manager(root_dir)
    print(out.dim(f"manager: {manager.label}"))
    if any(root.git_url for root in cfg.roots_in_order(root_dir)):
        print(out.section("== git =="))
        for root in cfg.roots_in_order(root_dir):
            if root.git_url:
                print(f"  {out.cyan('~')} pull {out.dim(str(root.dir))} ({root.git_url})")
    print(out.section("== system =="))
    problems: list[str] = []
    pkgs = cfg.all_packages(root_dir, manager.name)
    if not args.configs_only:
        missing = manager.check_many(pkgs)
        if missing:
            for pkg in missing:
                print(f"  {out.green('+')} {pkg}")
            problems.append("packages to install")
        else:
            print(f"  {out.green('all packages present')}")
    print(out.section("== links =="))
    items = linker.plan(root_dir, home)
    print_links(items)
    if args.prune:
        orphans = linker.orphaned(items)
        if orphans:
            for target in orphans:
                print(f"  {out.yellow('-')} {target} (pruned on `sync --prune`)")
        else:
            print(out.dim("  no orphans"))
    problems.extend(linker.find_conflicts(items, home))
    for problem in problems:
        print(f"  {out.red('!')} {problem}", file=sys.stderr)
    return 1 if problems else 0


def _sync_system(
    manager: pms_mod.PackageManager,
    root_dir: Path,
    force_yes: bool,
    system_only: bool,
) -> int:
    """Install missing system packages. Returns 0 on success."""
    if system_only:
        return 0
    print(out.section("== system =="))
    pkgs = cfg.all_packages(root_dir, manager.name)
    missing = manager.check_many(pkgs)
    if not missing:
        print(f"  {out.green('all packages present')}")
        return 0
    if _consent(force_yes, f"install these package(s)? {out.cyan('[y/N] ')}"):
        return _system_install(manager, missing)
    if sys.stdin.isatty():
        print(out.red("  aborted"))
        return 1
    print(err.red("[system] packages missing: rerun with --yes"))
    return 1


def _sync_links(
    root_dir: Path,
    home: Path,
    force: bool,
    prune: bool,
    configs_only: bool,
) -> int:
    """Apply symlinks and rendered files. Returns 0 on success."""
    if configs_only:
        return 0
    print(out.section("== links =="))
    items = linker.plan(root_dir, home)
    problems = linker.find_conflicts(items, home)
    if problems and not force:
        print(err.red("conflicts:"))
        for problem in problems:
            print(f"  {out.red('-')} {problem}", file=sys.stderr)
        sys.exit(err.red("aborting; use --force to replace"))
    try:
        created = linker.apply(items, home, force=force)
    except linker.ConflictError as exc:
        sys.exit(err.red(f"error: {exc}"))
    for item in created:
        print(f"  {out.green('+')} {item.target}")
    if not created:
        print(out.dim("  all targets already linked"))
    if problems:
        print(out.yellow(f"  replaced {len(problems)} existing target(s)"))
    if prune:
        removed, notices = linker.prune(items, home)
        for notice in notices:
            print(f"  {out.yellow('~')} {notice}")
        print(f"  {out.green(f'pruned {removed} orphan(s)')}")
    return 0


def _sync_dropped(
    manager: pms_mod.PackageManager,
    root_dir: Path,
    force_yes: bool,
) -> int:
    """Review and optionally uninstall dropped packages. Returns 0 on success."""
    declared = cfg.all_packages(root_dir, manager.name)
    previously = linker.load_installed()
    dropped = [pkg for pkg in previously if pkg not in declared]
    if not dropped:
        linker.record_installed(declared)
        return 0
    print(out.section("== dropped =="))
    print(out.yellow("  previously declared, now removed from manifest:"))
    for pkg in dropped:
        print(f"  {out.red('?')} {pkg}")
    if _consent(force_yes, f"uninstall these {len(dropped)} package(s)? {out.cyan('[y/N] ')}"):
        if _system_remove(manager, dropped):
            return 1
        linker.record_installed(declared)
    elif sys.stdin.isatty():
        print(out.dim("  keeping them installed (no longer tracked)"))
    return 0


def _sync_hooks(roots: list[cfg.Root]) -> int:
    """Run post-sync hooks. Returns 0 on success."""
    hooks = [(root, hook) for root in roots for hook in root.post_hooks]
    if not hooks:
        return 0
    print(out.section("== hooks =="))
    for root, hook in hooks:
        print(f"  {out.magenta('[hook]')} {hook}")
        if subprocess.run(["sh", "-c", hook], check=False).returncode != 0:
            sys.exit(err.red(f"hook failed: {hook}"))
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    """``pkg sync`` — sync the machine to the manifest.

    Runs: git pull → package install → symlink apply → hooks → dropped review.
    """
    root_dir = find_root(args.root or args.directory)
    home = host()
    manager = get_manager(root_dir)
    roots = cfg.roots_in_order(root_dir)

    if not args.no_git:
        pull_roots(root_dir, roots)

    if _sync_system(manager, root_dir, args.yes, args.configs_only):
        return 1
    if _sync_links(root_dir, home, args.force, args.prune, args.system_only):
        return 1
    if _sync_dropped(manager, root_dir, args.yes):
        return 1
    _sync_hooks(roots)

    print(out.green(out.bold("in sync")))
    return 0


def _snapshot_mtime(root_dir: Path) -> float:
    latest = (root_dir / "pkg.toml").stat().st_mtime
    configs = root_dir / "configs"
    if configs.is_dir():
        for p in configs.rglob("*"):
            if p.is_file():
                latest = max(latest, p.stat().st_mtime)
    return latest


def cmd_watch(args: argparse.Namespace) -> int:
    """``pkg watch`` — re-run sync when pkg.toml or configs/ changes."""
    root_dir = find_root(args.root or getattr(args, "directory", None))
    args.root = str(root_dir)
    args.yes = True
    args.prune = False
    print(out.dim(f"watching {root_dir} (Ctrl+C to stop)"))
    last = _snapshot_mtime(root_dir)
    while True:
        time.sleep(args.interval)
        try:
            now = _snapshot_mtime(root_dir)
        except FileNotFoundError:
            continue
        if now != last:
            last = now
            print(out.section("== change detected =="))
            try:
                cmd_sync(args)
            except SystemExit:
                pass


def cmd_status(args: argparse.Namespace) -> int:
    """``pkg status`` — show current package install state and link status."""
    root_dir = find_root(args.root)
    home = host()
    manager = get_manager(root_dir)
    print(out.dim(f"manager: {manager.label}"))
    for root in cfg.roots_in_order(root_dir):
        if root.git_url:
            print(f"{out.cyan('git')}: {root.dir}: {root.git_url}")
    print(out.section("== system =="))
    pkgs = cfg.all_packages(root_dir, manager.name)
    for pkg in pkgs:
        state = "installed" if manager.check(pkg) else "missing"
        color = out.green if state == "installed" else out.red
        print(f"  {color(state):10} {pkg}")
    print(out.section("== links =="))
    items = linker.plan(root_dir, home)
    print_links(items)
    wanted = {str(item.target) for item in items}
    stale = [target for target in linker.load_state_map() if target not in wanted]
    for target in stale:
        print(f"  {out.yellow('-')} {target} (not in manifest)")
    return 0


def cmd_unlink(args: argparse.Namespace) -> int:
    """``pkg unlink`` — remove all symlinks and rendered files pkg created."""
    removed = linker.unlink(host())
    verb = "symlink(s)" if removed == 1 else "symlinks"
    print(f"  {out.green(f'removed {removed} {verb}')}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """``pkg init`` — scaffold a new root directory with ``pkg.toml`` and ``configs/``."""
    d = Path(args.target).expanduser().resolve()
    (d / "configs").mkdir(parents=True, exist_ok=True)
    pkg_toml = d / "pkg.toml"
    if pkg_toml.exists() and not args.force:
        print(f"{pkg_toml}: already exists {out.yellow('(use --force to overwrite)')}")
    else:
        pkg_toml.write_text(TEMPLATE)
        print(f"  {out.green('wrote')} {pkg_toml}")
    linker.remember_root(d)
    print(f"  layout: {out.cyan(d)}")
    print("          configs/")
    print("  drop configs into configs/, then run `pkg sync`")
    return 0


def _autocommit(root_dir: Path, message: str) -> None:
    rc = subprocess.run(["git", "-C", str(root_dir), "add", "pkg.toml"], check=False).returncode
    if rc == 0:
        rc = subprocess.run(
            ["git", "-C", str(root_dir), "commit", "-m", message], check=False
        ).returncode
    if rc == 0:
        print(f"  {out.green('committed')} pkg.toml (git)")
    else:
        print(out.yellow(f"  warning: git commit failed: {message}"))


def _manifest_commit(root_dir: Path, changed: list[str], verb: str) -> None:
    if not changed or not (root_dir / ".git").exists():
        return
    if cfg.Root.load(root_dir, top=True).git_autocommit:
        _autocommit(root_dir, f"pkg: {verb} {', '.join(changed)}")
    else:
        print(out.yellow("  hint: pkg.toml changed — commit it in the dots repo"))


def cmd_add(args: argparse.Namespace) -> int:
    """``pkg add`` — install packages and declare them in the manifest."""
    root_dir = find_root(args.root)
    manager = get_manager(root_dir)
    pkg_toml = root_dir / "pkg.toml"

    before, after = cfg.add_packages(pkg_toml, args.packages)
    added = [p for p in args.packages if p in after and p not in before]
    for pkg in added:
        print(f"  {out.cyan('+')} {pkg} (declared in manifest)")

    pkgs = [
        cfg.resolve_package_name(p, manager.name, cfg.Root.load(root_dir).pkgs_map)
        for p in args.packages
    ]
    missing = manager.check_many(pkgs)
    present = [p for p, mapped in zip(args.packages, pkgs) if mapped not in missing]
    for pkg in present:
        print(f"  {out.green('=')} {pkg} (already installed)")
    if missing:
        rc = _system_install(manager, missing)
        if rc:
            return 1

    _manifest_commit(root_dir, added, "add")
    print(f"  {out.green(out.bold('in sync'))}")
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    """``pkg remove`` — uninstall packages and remove them from the manifest."""
    root_dir = find_root(args.root)
    manager = get_manager(root_dir)
    pkg_toml = root_dir / "pkg.toml"

    pkgs = [
        cfg.resolve_package_name(p, manager.name, cfg.Root.load(root_dir).pkgs_map)
        for p in args.packages
    ]
    present = [p for p, mapped in zip(args.packages, pkgs) if manager.check(mapped)]
    if present:
        rc = _system_remove(
            manager,
            [
                cfg.resolve_package_name(p, manager.name, cfg.Root.load(root_dir).pkgs_map)
                for p in present
            ],
        )
        if rc:
            return 1

    before, after = cfg.remove_packages(pkg_toml, args.packages)
    removed = [p for p in args.packages if p in before and p not in after]
    for pkg in removed:
        print(f"  {out.red('-')} {pkg} (removed from manifest)")

    _manifest_commit(root_dir, removed, "remove")
    print(f"  {out.green(out.bold('in sync'))}")
    return 0


_CMD = {
    "diff": cmd_diff,
    "plan": cmd_diff,
    "sync": cmd_sync,
    "watch": cmd_watch,
    "status": cmd_status,
    "unlink": cmd_unlink,
    "init": cmd_init,
    "add": cmd_add,
    "remove": cmd_remove,
}


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``pkg`` CLI.  Parses args and dispatches to the subcommand."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0
    try:
        return _CMD[args.cmd](args)
    except cfg.ConfigError as exc:
        print(err.red(f"error: {exc}"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
