# Configuration

All configuration lives in a `pkg.toml` manifest at the root of your dots directory.

## Full example

```toml
[git]
url = "git@github.com:you/dots.git"
autocommit = true

[manager]
name = "apt"

[config]
mode = "pkg"
stow = ["zsh"]
profiles = ["work"]
ignore = ["**/*.swp", ".DS_Store"]

[config.vars]
editor = "nvim"

[[system]]
name = "base"
packages = ["zsh", "git", "ripgrep"]
modules = ["nvim", "kitty"]

[[system]]
os = ["linux"]
packages = ["build-essential"]

[[system]]
profiles = ["work"]
packages = ["docker"]

[hooks]
post = ["chsh -s $(which zsh)"]
```

## Sections

### `[git]`

| Key | Type | Description |
|-----|------|-------------|
| `url` | string | Git remote URL. Sync auto-pulls before applying. |
| `autocommit` | bool | Auto-commit `pkg.toml` changes on `pkg add`/`remove`. |

### `[manager]`

| Key | Type | Description |
|-----|------|-------------|
| `name` | string | Force a specific package manager (`apt`, `pacman`, `dnf`, `zypper`, `apk`, `brew`). Auto-detected if omitted. Only valid in the top root. |

### `[config]`

| Key | Type | Description |
|-----|------|-------------|
| `mode` | string | Default mode: `"pkg"` (whole-dir symlink) or `"stow"` (individual file symlinks). |
| `stow` | list | Configs to process in stow mode regardless of the default. |
| `profiles` | list | Active roles on this machine. Used to filter `[[system]]` blocks. |
| `ignore` | list | Glob patterns to exclude from the link plan. |

### `[config.vars]`

Template variables available in `.tmpl` files. Merged with builtins `host`, `os`, and `home`.

### `[[system]]`

| Key | Type | Description |
|-----|------|-------------|
| `name` | string | Optional label for the block. |
| `packages` | list | System packages to install. |
| `modules` | list | Top-level directories that are their own roots (nested `pkg.toml` + `configs/`). |
| `os` | list | Only apply on these OS values (e.g. `["linux"]`, `["darwin"]`). |
| `profiles` | list | Only apply when one of these profiles is active. |

A block with no `os` or `profiles` always applies.

### `[hooks]`

| Key | Type | Description |
|-----|------|-------------|
| `post` | list | Shell commands to run after a fully successful sync. |

### `[pkgs_map]`

Cross-platform package name mapping:

```toml
[pkgs_map]
rg = { apt = "ripgrep", brew = "ripgrep" }
fd = { apt = "fd-find", brew = "fd" }
```

## Templating

Files ending in `.tmpl` inside a **stow-mode** config are rendered with `string.Template`:

```
configs/zsh/.zshrc.tmpl  →  ~/.zshrc
```

Built-in variables: `host`, `os`, `home`. Custom variables from `[config.vars]`. Use `$$` for a literal `$`.

Rendered files are tracked by sha256. pkg rewrites them when the template or vars change, refuses to overwrite hand-edited files (unless `--force`), and considers symlinks at the target path a conflict.

## Profiles

Profiles select between `[[system]]` blocks the way `os` does, for when one dots repo spans machines with different roles:

```toml
[config]
profiles = ["work"]

[[system]]
profiles = ["work"]
packages = ["docker"]
```

## Ignore globs

```toml
[config]
ignore = ["**/*.swp", ".DS_Store", "cache/"]
```

Patterns match paths inside config dirs. `**` crosses directories.

## Config mapping modes

- **pkg mode (default):** `configs/<name>` → whole-dir symlink to `~/.config/<name>`.
- **stow mode:** every file is individually symlinked into `$HOME`, mirroring the relative path. GNU Stow semantics.

Toggle per-config with `stow = ["name"]` or globally with `mode = "stow"`.
