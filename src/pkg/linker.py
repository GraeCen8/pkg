from __future__ import annotations

import hashlib
import json
import os
import socket
import string
import time
from dataclasses import dataclass
from pathlib import Path

from pkg.config import ConfigError, host_os, roots_in_order


class ConflictError(Exception):
    pass


@dataclass
class LinkItem:
    target: Path
    source: Path
    kind: str
    content: str | None = None
    hash: str | None = None


def state_dir() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "pkg"
    return Path.home() / ".local" / "state" / "pkg"


def state_file() -> Path:
    return state_dir() / "links.json"


def read_link(path: Path) -> str:
    try:
        return os.readlink(path)
    except OSError:
        return ""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _read_db() -> dict:
    try:
        data = json.loads(state_file().read_text())
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def _write_db(db: dict) -> None:
    state_dir().mkdir(parents=True, exist_ok=True)
    safe = {"version": 1, "links": [], "installed": []}
    safe.update(db if isinstance(db, dict) else {})
    tmp = state_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(safe, indent=2) + "\n")
    os.replace(tmp, state_file())


def load_state() -> list[dict]:
    return [e for e in _read_db().get("links", []) if isinstance(e, dict)]


def load_state_map() -> dict[str, str]:
    return {e["target"]: e["source"] for e in load_state() if "target" in e and "source" in e}


def load_installed() -> list[str]:
    return [p for p in _read_db().get("installed", []) if isinstance(p, str)]


def state_entry(target: Path) -> dict | None:
    for entry in load_state():
        if entry.get("target") == str(target):
            return entry
    return None


def save_state(entries: list[dict]) -> None:
    db = _read_db()
    db["links"] = entries
    _write_db(db)


def record_installed(packages: list[str]) -> None:
    db = _read_db()
    db["installed"] = packages
    _write_db(db)


def _scan_stow(src: Path, out: list[Path]) -> None:
    for child in sorted(src.iterdir()):
        if child.is_dir() and not child.is_symlink():
            _scan_stow(child, out)
        else:
            out.append(child)


def _vars_for(root, home: Path) -> dict:
    variables = {
        "host": socket.gethostname(),
        "os": host_os(),
        "home": str(home),
    }
    variables.update(root.template_vars)
    return variables


def _render_template(path: Path, variables: dict) -> str:
    try:
        return string.Template(path.read_text()).substitute(**variables)
    except (ValueError, KeyError) as exc:
        raise ConfigError(f"template {path}: {exc}") from exc


def _plan_one(
    cdir: Path,
    mode: str,
    home: Path,
    items: list[LinkItem],
    variables: dict,
) -> None:
    if mode == "pkg":
        payload: list[Path] = []
        _scan_stow(cdir, payload)
        if any(p.name.endswith(".tmpl") for p in payload):
            print(
                f"{cdir}: warning: contains .tmpl files but is in pkg mode "
                "(whole-dir symlink); use 'stow' mode for templating"
            )
        items.append(LinkItem(home / ".config" / cdir.name, cdir, "dir"))
        return
    files: list[Path] = []
    _scan_stow(cdir, files)
    for source in files:
        rel = source.relative_to(cdir)
        if rel.name.endswith(".tmpl"):
            content = _render_template(source, variables)
            target = home / rel.parent / rel.name[: -len(".tmpl")]
            items.append(
                LinkItem(
                    target, source, "render", content=content, hash=_sha256_bytes(content.encode())
                )
            )
        else:
            items.append(LinkItem(home / rel, source, "file"))


def plan(root_dir: Path, home: Path) -> list[LinkItem]:
    items: list[LinkItem] = []
    for root in roots_in_order(root_dir):
        cfgdir = root.dir / "configs"
        if not cfgdir.is_dir():
            continue
        variables = _vars_for(root, home)
        for child in sorted(cfgdir.iterdir()):
            if child.name.startswith("."):
                continue
            if child.is_dir():
                mode = "stow" if child.name in root.stow else root.mode
                _plan_one(child, mode, home, items, variables)
            else:
                print(f"{cfgdir}: warning: stray file ignored: {child.name}")
    items.sort(key=lambda it: str(it.target))
    return items


def item_status(item: LinkItem) -> str:
    target = item.target
    if item.kind == "render":
        if target.is_symlink() or not target.exists():
            if target.is_symlink():
                return "conflict"
            return "new"
        if not item.source.exists():
            return "broken"
        entry = state_entry(target)
        if entry and entry.get("kind") == "render" and entry.get("hash"):
            if entry.get("hash") == _sha256_file(target):
                return "ok" if entry.get("hash") == item.hash else "new"
            return "conflict"
        return "conflict"
    if target.is_symlink() and read_link(target) == str(item.source):
        return "ok"
    if not item.source.exists():
        return "broken"
    if target.is_symlink() or target.exists():
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
        if item.kind == "render":
            if target.is_symlink():
                problems.add(f"{target}: existing symlink; cannot render a file over it")
            elif target.exists():
                entry = state_entry(target)
                owned = bool(
                    entry
                    and entry.get("kind") == "render"
                    and entry.get("hash") == _sha256_file(target)
                )
                if not owned:
                    problems.add(f"{target}: existing file (use --force to replace)")
            continue
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


def _apply_item(item: LinkItem, home: Path, force: bool, backup_dir: Path) -> bool:
    target = item.target
    if item.kind == "render":
        if target.is_symlink():
            raise ConflictError(f"{target}: cannot render a file over a symlink")
        if target.exists():
            entry = state_entry(target)
            owned = bool(
                entry
                and entry.get("kind") == "render"
                and entry.get("hash") == _sha256_file(target)
            )
            if owned and entry.get("hash") == item.hash:
                return False
            if not owned and not force:
                raise ConflictError(f"{target}: diverged from pkg (use --force)")
            if not owned:
                _force_replace(target, backup_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.content)
        return True
    if target.is_symlink() and read_link(target) == str(item.source):
        return False
    if target.is_symlink() or target.exists():
        if not force:
            raise ConflictError(f"{target}: target exists (use --force)")
        _force_replace(target, backup_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(item.source, target, target_is_directory=(item.kind == "dir"))
    return True


def apply(items: list[LinkItem], home: Path, force: bool = False) -> list[LinkItem]:
    backup_dir = state_dir() / "backup"
    created: list[LinkItem] = []
    try:
        for item in items:
            if _apply_item(item, home, force, backup_dir):
                created.append(item)
    except BaseException:
        for item in created:
            try:
                if item.kind == "render" or (
                    item.target.is_symlink() and read_link(item.target) == str(item.source)
                ):
                    item.target.unlink()
                    prune_empty_parents(item.target.parent, home)
            except OSError:
                pass
        raise
    _merge_state(items)
    return created


def orphaned(items: list[LinkItem]) -> list[str]:
    desired = {str(item.target) for item in items}
    owned = []
    for entry in load_state():
        if entry.get("target") in desired:
            continue
        target = Path(entry["target"])
        if entry.get("kind") == "render":
            if target.is_file() and entry.get("hash") and entry.get("hash") == _sha256_file(target):
                owned.append(entry["target"])
        elif target.is_symlink() and entry.get("source") and read_link(target) == entry["source"]:
            owned.append(entry["target"])
    return sorted(owned)


def prune(items: list[LinkItem], home: Path) -> tuple[int, list[str]]:
    desired = {str(item.target) for item in items}
    kept: list[dict] = []
    removed = 0
    notices: list[str] = []
    for entry in load_state():
        target = Path(entry["target"])
        if entry.get("target") in desired:
            kept.append(entry)
            continue
        if entry.get("kind") == "render":
            if target.is_file() and entry.get("hash") and entry.get("hash") == _sha256_file(target):
                target.unlink()
                prune_empty_parents(target.parent, home)
                removed += 1
            else:
                kept.append(entry)
                notices.append(f"{target}: kept (user-modified)")
            continue
        if target.is_symlink() and entry.get("source") and read_link(target) == entry["source"]:
            target.unlink()
            prune_empty_parents(target.parent, home)
            removed += 1
        else:
            kept.append(entry)
            notices.append(f"{target}: kept (not pkg-owned)")
    save_state(kept)
    return removed, notices


def unlink(home: Path) -> int:
    entries = load_state()
    kept: list[dict] = []
    removed = 0
    for entry in entries:
        target = Path(entry["target"])
        source = entry.get("source", "")
        if entry.get("kind") == "render":
            if entry.get("hash") and target.is_file() and entry.get("hash") == _sha256_file(target):
                target.unlink()
                prune_empty_parents(target.parent, home)
                removed += 1
            else:
                kept.append(entry)
            continue
        if target.is_symlink() and read_link(target) == source:
            target.unlink()
            prune_empty_parents(target.parent, home)
            removed += 1
        else:
            kept.append(entry)
    save_state(kept)
    return removed


def _merge_state(items: list[LinkItem]) -> None:
    by_target = {e["target"]: e for e in load_state()}
    for item in items:
        if item.kind == "render":
            by_target[str(item.target)] = {
                "target": str(item.target),
                "source": str(item.source),
                "kind": "render",
                "hash": item.hash,
            }
        else:
            by_target[str(item.target)] = {
                "target": str(item.target),
                "source": str(item.source),
            }
    save_state(list(by_target.values()))
