# pkg

A declarative wraparound for exactly two things: your **system package manager**
and **symlinks**. Write a root `pkg.toml`, drop configs into `configs/`, run
`pkg sync`, and the machine matches the manifest.

**Sync is one-directional:** it installs missing packages, creates missing
symlinks, and fixes drifted ones so the machine matches the manifest. It never
removes anything on its own. `pkg sync --prune` additionally removes orphaned
links for configs dropped from the manifest; removed **packages** are only ever
listed for review, never uninstalled.

> **Non-goals (v0):** no building from source, no content store, no secrets.

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
[git]
url = "git@github.com:you/dots.git"   # optional; sync runs `git pull --ff-only`

[manager]
name = "apt"                # optional; auto-detect otherwise (top root only)

[modules]
on = ["nvim", "kitty"]      # top-level dirs to treat as embedded roots

[config]
stow = ["zsh"]              # these configs use stow mode
mode = "pkg"                # "pkg" (default) | "stow" — process, then stow

[config.vars]
editor = "nvim"             # template variables, in addition to builtins
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

## Templating

Files ending in `.tmpl` inside a **stow-mode** config are rendered into `$HOME`
with `string.Template` (`$var` syntax, `$$` for a literal `$`):

```
configs/zsh/.zshrc.tmpl  →  ~/.zshrc        (rendered, not symlinked)
```

Available variables are the builtins `host`, `os`, and `home`, merged with any
`[config.vars]` from the same root. A template referencing an unknown variable
is a hard error. Rendered files are tracked by sha256 in the state file: pkg
rewrites them when the template or vars change, refuses to overwrite them once
you've hand-edited them (unless `--force`), and a rendered target that is a
symlink is always a conflict. `.tmpl` files under a **pkg-mode** config are
ignored with a warning — templating needs stow mode.

## Git-backed roots

A root (or module) with `[git] url` is auto-pulled before every `sync`:

```
[git]
url = "git@github.com:you/dots.git"
```

`pkg sync --no-git` skips pulls; `plan`/`status` show the configured URL.
A root that declares a URL but isn't a git checkout, or a pull that fails, is a
hard error.

## Pruning

Configs you delete from a root become orphaned links on disk. `sync --prune`
(and `plan --prune` to preview) removes orphans — but only ones `pkg` owns: the
target must still match what pkg created (a hand-edited or re-pointed file is
left alone with a notice). Packages that you remove from `[[system]]` are never
automatically uninstalled; at the end of a sync, pkg lists any packages it
previously saw and now no longer declares, and — when the terminal is
interactive — asks whether to uninstall them (`[y/N]`). Saying no (or running
non-interactively) never removes anything and leaves the decision pending, so
the review comes back next sync. `-y/--yes` counts as consent.

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
               #   --prune also lists orphans that `sync --prune` would remove
pkg sync       # sync the machine to the manifest: ─ install pkgs (prompt
               #   unless -y) ─ pull git roots (unless --no-git) ─ symlink
               #   ─ prune orphans (--prune) ─ hooks
               #   --system-only | --configs-only | --force | --yes | --prune | --no-git
pkg status     # pkg installed/missing; links ok/drifted
pkg add pkgs   # install pkgs and declare them in the manifest
pkg remove pkgs# uninstall pkgs and undeclare them in the manifest
pkg unlink     # remove only symlinks pkg created (state file)
pkg init <dir> # scaffold a root at <dir>: pkg.toml + configs/
               #   (e.g. `pkg init ~/dots` or `pkg init .`)
```

`pkg add`/`pkg remove` keep the manifest and the machine in step: `pkg add zsh`
installs `zsh` (via the normal package-manager path) and appends it to the
unfiltered `[[system]]` block, so the next `pkg sync` on any machine installs it
too. `pkg remove zsh` uninstalls it and drops it from the manifest. Editing is
text-preserving: comments, other tables, and os-filtered `[[system]]` blocks are
left alone.

`-R/--root <dir>` overrides the root. The last root you point at (via `-R` or
`pkg init`) is remembered, so plain `pkg sync` works from anywhere — you only
ever type the root once.

## Behavior rules

- Output is colored when the terminal supports it (and `NO_COLOR` not set);
  installs run quietly — you see `installing: pkg …` with a spinner, not the
  package manager's own output — and only packages that genuinely couldn't be
  installed are called out as "not found".
- Package manager auto-detected from `/etc/os-release` (`ID` + `ID_LIKE`)
  → apt/pacman/dnf/zypper/apk, or `brew` on macOS. Override with
  `[manager] name` in the top root.
- **Apt special-case:** lazy `apt-get update` — only runs when a declared
  package isn't already known to dpkg.
- Order is always: git pull → check → install (live confirm) → symlink →
  hooks. Hooks only run after a fully successful sync.
- **Conflicts abort.** If a target already exists (real file, dir, or symlink
  to elsewhere), `plan` shows it and `sync` fails without doing anything;
  `--force` replaces it (non-empty directories are still refused and a backup
  of anything replaced is kept under the state dir). Two configs mapping to the
  same target is also a conflict — nothing is "last wins".
- Everything is **idempotent**: already-installed packages and already-correct
  symlinks are no-ops.
- State lives in `~/.local/state/pkg/links.json` — only symlinks/rendered files
  `pkg` created, so `unlink`/`status`/`--prune` never touch targets it doesn't
  own. Safety relies on never overwriting without `--force`, so a mid-run
  failure only leaves orphan symlinks from that run, which are cleaned up
  before exiting nonzero.

## Development

```sh
just install      # venv + editable install + dev deps
just build        # self-contained ./pkg executable (zipapp, no deps)
just test         # pytest
just lint         # ruff
```

Or manually:

```sh
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check
```

## Deferred to v0.x

- Secret encryption
- AUR / flatpak / homebrew-cask