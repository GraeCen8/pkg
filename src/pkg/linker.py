from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_state_dir

from pkg.config import roots_in_order


class ConflictError(Exception):
    pass


@dataclass
class LinkItem:
    target: Path
    source: Path
    kind: str


def state_dir() -> Path:
    return Path(user_state_dir("pkg"))


def state_file() -> Path:
    return state_dir() / "links.json"


def read_link(path: Path) -> str:
    try:
        return os.readlink(path)
    except OSError:
        return ""


def load_state() -> list[dict]:
    try:
        data = json.loads(state_file().read_text())
    except (OSError, ValueError):
        return []
    return [e for e in data.get("links", []) if isinstance(e, dict)]


def load_state_map() -> dict[str, str]:
    return {
        e["target"]: e["source"]
        for e in load_state()
        if isinstance(e, dict) and "target" in e and "source" in e
    }


def save_state(entries: list[dict]) -> None:
    state_dir().mkdir(parents=True, exist_ok=True)
    tmp = state_file().with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": 1, "links": entries}, indent=2) + "\n")
    os.replace(tmp, state_file())


def _scan_stow(src: Path, out: list[Path]) -> None:
    for child in sorted(src.iterdir()):
        if child.is_dir() and not child.is_symlink():
            _scan_stow(child, out)
        else:
            out.append(child)


def plan(root_dir: Path, home: Path) -> list[LinkItem]:
    items: list[LinkItem] = []
    for root in roots_in_order(root_dir):
        cfgdir = root.dir / "configs"
        if not cfgdir.is_dir():
            continue
        for child in sorted(cfgdir.iterdir()):
            if child.name.startswith("."):
                continue
            if child.is_dir():
                mode = "stow" if child.name in root.stow else root.mode
                _plan_one(child, mode, home, items)
            else:
                print(f"{cfgdir}: warning: stray file ignored: {child.name}")
    items.sort(key=lambda it: str(it.target))
    return items


def _plan_one(cdir: Path, mode: str, home: Path, items: list[LinkItem]) -> None:
    if mode == "pkg":
        items.append(LinkItem(home / ".config" / cdir.name, cdir, "dir"))
        return
    files: list[Path] = []
    _scan_stow(cdir, files)
    for source in files:
        items.append(LinkItem(home / source.relative_to(cdir), source, "file"))


def item_status(item: LinkItem) -> str:
    if item.target.is_symlink() and read_link(item.target) == str(item.source):
        return "ok"
    if not item.source.exists():
        return "broken"
    if item.target.is_symlink() or item.target.exists():
        return "conflict"
    return "new"


def find_conflicts(items: list[LinkItem], home: Path) -> list[str]:
    problems: set[str] = set()
    seen: dict[Path, Path] = {}
    for item in items:
        other = seen.get(item.target)
        if other is not None:
            problems.add(f"duplicate target {item.target} ({other} and {item.source})")
        else:
            seen[item.target] = item.source
        parent = item.target.parent
        while parent != home and parent != parent.parent:
            if parent.exists() and not parent.is_dir():
                problems.add(f"{parent}: not a directory; cannot create links under it")
                break
            parent = parent.parent
        target = item.target
        if target.is_symlink():
            if read_link(target) != str(item.source):
                problems.add(f"{target}: existing symlink to elsewhere")
        elif target.exists():
            kind = "directory" if target.is_dir() else "file"
            problems.add(f"{target}: existing {kind} (use --force to replace)")
    return sorted(problems)


def _move_to_backup(target: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    base = backup_dir / f"{target.name}.{time.strftime('%Y%m%d-%H%M%S')}"
    dest = base
    n = 1
    while dest.exists():
        dest = Path(f"{base}.{n}")
        n += 1
    os.replace(target, dest)
    return dest


def _force_replace(target: Path, backup_dir: Path) -> None:
    if target.is_dir() and not target.is_symlink():
        if any(target.iterdir()):
            raise ConflictError(f"{target}: --force cannot replace a non-empty directory")
        target.rmdir()
        return
    _move_to_backup(target, backup_dir)


def prune_empty_parents(path: Path, home: Path) -> None:
    while path != home and path != path.parent:
        try:
            path.rmdir()
        except OSError:
            break
        path = path.parent


def unlink(home: Path) -> int:
    entries = load_state()
    kept: list[dict] = []
    removed = 0
    for entry in entries:
        target = Path(entry["target"])
        source = entry.get("source", "")
        if target.is_symlink() and read_link(target) == source:
            target.unlink()
            prune_empty_parents(target.parent, home)
            removed += 1
        else:
            kept.append(entry)
    save_state(kept)
    return removed


def apply(items: list[LinkItem], home: Path, force: bool = False) -> list[LinkItem]:
    backup_dir = state_dir() / "backup"
    created: list[LinkItem] = []
    try:
        for item in items:
            target = item.target
            if target.is_symlink() and read_link(target) == str(item.source):
                continue
            if target.is_symlink() or target.exists():
                if not force:
                    raise ConflictError(f"{target}: target exists (use --force)")
                _force_replace(target, backup_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(
                item.source,
                target,
                target_is_directory=(item.kind == "dir"),
            )
            created.append(item)
    except BaseException:
        for item in created:
            try:
                if item.target.is_symlink() and read_link(item.target) == str(item.source):
                    item.target.unlink()
                    prune_empty_parents(item.target.parent, home)
            except OSError:
                pass
        raise
    current = load_state_map()
    for item in items:
        current[str(item.target)] = str(item.source)
    save_state([{"target": k, "source": v} for k, v in current.items()])
    return created
