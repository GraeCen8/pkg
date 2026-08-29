# Architecture

## Module overview

```
pkg/
├── cli.py      — argument parsing, command dispatch, user-facing output
├── config.py   — manifest parsing, root/module resolution, package aggregation
├── linker.py   — symlink planning, conflict detection, state tracking, apply/prune
├── pms.py      — package manager abstraction with auto-detection
└── colors.py   — terminal color helpers with NO_COLOR support
```

## Data flow

```
pkg.toml
  │
  ▼
config.py: Root.load()  →  Root dataclass
  │
  ├──► config.roots_in_order()  →  depth-first list of Roots (including modules)
  │
  ├──► config.all_packages()    →  deduplicated package list
  │
  └──► linker.plan()            →  list of LinkItem (symlinks + renders)
         │
         ├──► linker.find_conflicts()  →  error list
         ├──► linker.apply()           →  creates symlinks/files
         ├──► linker.prune()           →  removes orphans
         └──► linker.unlink()          →  removes all pkg-owned links
```

## Key data structures

### `Root` (config.py)

Parsed representation of a `pkg.toml`. Contains the directory path, package manager override, config mode, system entries, hooks, git settings, template vars, and ignore patterns.

### `SystemEntry` (config.py)

A single `[[system]]` block. The `applies()` method checks OS and profile filters against the current machine.

### `LinkItem` (linker.py)

A planned symlink or rendered file. Fields: `target`, `source`, `kind` (`"dir"`, `"file"`, or `"render"`), `content` (for renders), and `hash` (sha256 of rendered content).

### `PackageManager` (pms.py)

Abstract base with `check()`, `install()`, `remove()` methods. Concrete backends: `Apt`, `Pacman`, `Dnf`, `Zypper`, `Apk`, `Brew`. Auto-detection reads `/etc/os-release` on Linux or returns `Brew` on macOS.

## State file

Lives at `~/.local/state/pkg/links.json`:

```json
{
  "version": 1,
  "links": [
    {"target": "/home/user/.config/zsh", "source": "/home/user/dots/configs/zsh", "kind": "dir"},
    {"target": "/home/user/.zshrc", "source": "...", "kind": "render", "hash": "abc123"}
  ],
  "installed": ["zsh", "git", "ripgrep"]
}
```

- `links` tracks symlinks and rendered files pkg created (for `unlink`, `prune`, `status`).
- `installed` tracks the last declared package list (for detecting dropped packages).

## Sync order

`pkg sync` runs: git pull → package install → symlink/apply → hooks → dropped package review.

## Conflict detection

`linker.find_conflicts()` checks for: duplicate targets, non-directory parents, existing symlinks pointing elsewhere, existing files/dirs at target, and unowned rendered files. Conflicts abort unless `--force` is passed (which backs up existing targets).
