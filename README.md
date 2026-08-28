# pkg

A declarative wraparound for exactly two things: your **system package manager**
and **symlinks**. Write a root `pkg.toml`, drop configs into `configs/`, run
`pkg sync`, and the machine matches the manifest.

**Sync is one-directional:** it installs missing packages, creates missing
symlinks, and fixes drifted ones so the machine matches the manifest. It never
removes anything on its own.

> **Non-goals (v0):** no building from source, no content store, no templating,
> no secrets, no pruning of removed packages.

## Layout

```
~/dots/
├─ pkg.toml                    # main manifest
├─ configs/<name>/             # main's configs
├─ <module>/                   # enabled module (top-level dir, own root)
│   ├─ pkg.toml
│   └─ configs/
└─ <module2>/                  # disabled = not in [modules], just ignored
```

The root is anywhere a `pkg.toml` + `configs/` lives; `~/dots` is just the
default home for it.

## `pkg.toml`

```toml
[manager]
name = "apt"                # optional; auto-detect otherwise (top root only)

[modules]
on = ["nvim", "kitty"]      # top-level dirs to treat as embedded roots

[config]
stow = ["zsh"]              # these configs use stow mode
mode = "pkg"                # "pkg" (default) | "stow" — process, then stow
```

plus optional per-root tables:

```toml
[[system]]                  # machine-wide packages; root or any module
os = ["darwin"]
packages = ["ripgrep"]

[hooks]
post = ["chsh -s $(which zsh)"]   # run after a fully successful sync
```

## Config mapping

Every dir in `configs/` is auto-managed — **zero per-config entries required**.

- **`pkg` mode (default):** `configs/<name>` → whole-dir symlink to
  `~/.config/<name>`.
- **`stow` mode:** every file inside `configs/<name>` is symlinked individually
  into `$HOME`, mirroring the relpath — classic GNU Stow semantics:
  `configs/zsh/.zshrc` → `~/.zshrc`,
  `configs/zsh/.config/zsh/zshrc` → `~/.config/zsh/zshrc`. Parent dirs are
  created as needed. This is why a `mode = "file"` override isn't needed —
  a one-file stow config handles things like `.zshrc`.
- `stow = ["..."]` toggles individual configs to stow mode; `mode = "stow"`
  switches the default for **all** configs (the `stow` list wins for names it
  lists).

A stray top-level *file* directly inside `configs/` is ignored with a warning.

## Modules

`[modules] on` enables top-level dirs as embedded roots. Each module has its own
`pkg.toml` + `configs/`, obeys the same config-mapping rules, and can itself
declare `[modules]` for nesting. Enabled-but-missing module (or a module missing
its `pkg.toml`) is a hard error.

**Apply order is depth-first, modules before main:**
module's modules → module → … → main. `[[system]]` packages and hooks merge
across the whole tree.

## CLI

```
pkg plan       # diff of both stages, no side effects
pkg sync       # sync the machine to the manifest: ─ install pkgs (prompt
               #   unless -y) ─ symlink ─ hooks
               #   --system-only | --configs-only | --force | --yes
pkg status     # pkg installed/missing; links ok/drifted
pkg unlink     # remove only symlinks pkg created (state file)
pkg init       # scaffolds the root: pkg.toml + configs/
```

## Behavior rules

- Package manager auto-detected from `/etc/os-release` (`ID` + `ID_LIKE`)
  → apt/pacman/dnf/zypper/apk, or `brew` on macOS. Override with
  `[manager] name` in the top root.
- **Apt special-case:** lazy `apt-get update` — only runs when a declared
  package isn't already known to dpkg.
- Order is always: check → install (live confirm) → symlink → hooks. Hooks only
  run after a fully successful sync.
- **Conflicts abort.** If a target already exists (real file, dir, or symlink
  to elsewhere), `plan` shows it and `sync` fails without doing anything;
  `--force` replaces it. Two configs mapping to the same target is also a
  conflict — nothing is "last wins".
- Everything is **idempotent**: already-installed packages and already-correct
  symlinks are no-ops.
- State lives in `~/.local/state/pkg/links.json` — only symlinks `pkg` created,
  so `unlink`/`status` never touch orphan targets. Safety relies on never
  overwriting without `--force`, so a mid-run failure only leaves orphan
  symlinks from that run, which are cleaned up before exiting nonzero.

## Development

```sh
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check
```

## Deferred to v0.x

- Templating / per-host variables
- Secret encryption
- Git-backed roots (`pkg sync` auto-pull)
- Pruning removed packages
- AUR / flatpak / homebrew-cask