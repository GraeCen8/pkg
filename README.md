# pkg

A declarative wraparound for exactly two things: your **system package manager**
and **symlinks**. Write a root `pkg.toml`, drop configs into `configs/`, run
`pkg sync`, and the machine matches the manifest.

> **Non-goals (v0):** no building from source, no content store, no secrets.

## Layout

```
~/dots/
├─ pkg.toml                    # main manifest
├─ configs/<name>/             # main's configs
├─ <module>/                   # enabled module (declared in [[system]] modules)
│   ├─ pkg.toml
│   └─ configs/
└─ <module2>/                  # not declared = ignored
```

The root is anywhere a `pkg.toml` + `configs/` lives; `~/dots` is just the
default home for it.

## `pkg.toml`

```toml
[git]
url = "git@github.com:you/dots.git"   # optional; sync runs `git pull --ff-only`

[manager]
name = "apt"                # optional; auto-detect otherwise (top root only)

[config]
stow = ["zsh"]              # these configs use stow mode
mode = "pkg"                # "pkg" (default) | "stow" — process, then stow

[config.vars]
editor = "nvim"             # template variables, in addition to builtins

[config]                    # optional role filtering + file exclusions
profiles = ["work"]         # active roles; overrides nothing by default
ignore = ["**/*.swp", ".DS_Store"]   # glob patterns; optional
```

plus optional per-root tables:

```toml
[[system]]                  # machine-wide packages; root or any module
os = ["darwin"]
profiles = ["work"]         # optional; only on machines with this role active
packages = ["ripgrep"]

[git]
autocommit = true           # pkg add/remove commits pkg.toml in git roots

[hooks]
post = ["chsh -s $(which zsh)"]   # run after a fully successful sync
```

**Profiles** select between `[[system]]` blocks the way `os` does, for when one
dots repo spans machines with different roles:

```toml
[config]
profiles = ["work"]         # this machine's roles

[[system]]
profiles = ["work"]         # block only applies where "work" is active
packages = ["docker"]
```

A block with no `profiles` (and no `os`) always applies; so leaving the key
out means today's behavior. `pkg add` always declares into the every-machine
block.

**Ignore globs** drop files out of the link plan:

```toml
[config]
ignore = ["**/*.swp", ".DS_Store", "cache/"]
```

Patterns match the path inside a config dir (or the config's name itself);
`**` crosses directories. Great for editor junk and whole subfolders you don't
want mirrored.

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

With `[git] autocommit = true`, `pkg add` and `pkg remove` commit the
`pkg.toml` change themselves (`pkg: add zsh`) instead of just hinting — handy
when the manifest lives in the dots repo. Without it they print the usual
"commit it in the dots repo" hint.

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

Modules are declared in `[[system]]` blocks with the `modules` key. A module is
a top-level dir that is its own root (has its own `pkg.toml` + `configs/`).

```toml
[[system]]
packages = ["bash"]
modules = ["nvim", "kitty"]    # these dirs are embedded roots
```

Modules respect `os` and `profiles` filters, so you can scope modules to
specific machines:

```toml
[[system]]
os = ["linux"]
modules = ["linux-tools"]

[[system]]
os = ["darwin"]
modules = ["mac-tools"]
```

Modules can themselves declare modules for nesting. Enabled-but-missing module
(or a module missing its `pkg.toml`) is a hard error.

**Apply order is depth-first, modules before main:**
module's modules → module → … → main. `[[system]]` packages and hooks merge
across the whole tree.

## CLI

### Install

```sh
curl -fsSL https://raw.githubusercontent.com/graecen8/pkg/main/install.sh | bash
```

### Commands

```
pkg plan                         # preview what sync would do, no side effects
                                 #   --prune also shows orphans
pkg sync [dir]                   # sync machine to manifest: install pkgs, pull
                                 #   git roots, symlink configs, prune orphans,
                                 #   run hooks. Pass a dir or use -R to override.
                                 #   --system-only | --configs-only | --force
                                 #   --yes | --prune | --no-git
pkg watch [dir]                  # re-run sync when pkg.toml or configs/ changes
                                 #   --interval N  (poll seconds, default 2)
pkg status                       # show packages and link state
pkg add <pkgs>                   # install + declare in manifest
pkg remove <pkgs>                # uninstall + undeclare from manifest
pkg unlink                       # remove only symlinks pkg created
pkg init <dir>                   # scaffold a new root: pkg.toml + configs/
```

### How sync works

`pkg sync` runs in order: git pull → check → install → symlink → hooks.

**Packages:** the system package manager is auto-detected from `/etc/os-release`
(`apt`/`pacman`/`dnf`/`zypper`/`apk`), or `brew` on macOS. If `yay` or `paru`
is installed, it is used instead of `pacman` so AUR packages are supported.
Override with `[manager] name` in the top root. Each package is installed
individually with a spinner; failures are reported per-package.

**Configs:** each dir in `configs/` becomes a symlink under `~/.config/` (pkg
mode) or individual files under `~` (stow mode). Conflicts abort unless
`--force` is passed.

**Dropped packages:** packages removed from `[[system]]` are listed for review
at the end of sync. In interactive mode you're asked whether to uninstall them;
in batch mode they're left alone.

### Manifest editing

`pkg add`/`pkg remove` keep the manifest and the machine in step: `pkg add zsh`
installs `zsh` and appends it to the unfiltered `[[system]]` block, so the next
`pkg sync` on any machine installs it too. `pkg remove zsh` uninstalls it and
drops it from the manifest. Editing is text-preserving: comments, other tables,
and os-filtered `[[system]]` blocks are left alone.

`-R/--root <dir>` overrides the root. The last root you point at (via `-R` or
`pkg init`) is remembered, so plain `pkg sync` works from anywhere.

## Behavior rules

- Output is colored when the terminal supports it (`NO_COLOR` respected).
- Installs run per-package with a spinner — no package manager noise.
- **Apt special-case:** lazy `apt-get update` — only runs when a declared
  package isn't already known to dpkg.
- **Conflicts abort.** If a target already exists (real file, dir, or symlink
  to elsewhere), `plan` shows it and `sync` fails without doing anything;
  `--force` replaces it (backups kept under the state dir). Two configs mapping
  to the same target is also a conflict.
- Everything is **idempotent**: already-installed packages and already-correct
  symlinks are no-ops.
- State lives in `~/.local/state/pkg/links.json` — only symlinks/rendered files
  `pkg` created, so `unlink`/`status`/`--prune` never touch targets it doesn't
  own.

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
