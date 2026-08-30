# CLI Usage

---

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/graecen8/pkg/main/install.sh | bash
```

## Common commands

```
pkg diff [dir]                    # preview what sync would do, no side effects
                                  #   --prune also shows orphans
pkg plan                          # alias for diff
pkg sync [dir]                    # sync machine to manifest: install pkgs, pull
                                  #   git roots, symlink configs, prune orphans,
                                  #   run hooks. Pass a dir or use -R to override.
                                  #   --system-only | --configs-only | --force
                                  #   --yes | --prune | --no-git
pkg watch [dir]                   # re-run sync when pkg.toml or configs/ changes
                                  #   --interval N  (poll seconds, default 2)
pkg status                        # show packages and link state
pkg add <pkgs>                    # install + declare in manifest
pkg remove <pkgs>                 # uninstall + undeclare from manifest
pkg unlink                        # remove only symlinks pkg created
pkg init <dir>                    # scaffold a new root: pkg.toml + configs/
pkg search [query]                # interactive package browser
                                  #   --installed  show only manifest packages
                                  #   --manager X  force a specific PM
```

## How sync works

`pkg sync` runs in order: git pull → check → install → symlink → hooks.

- The system package manager is auto-detected from `/etc/os-release`
- Each package is installed individually with a spinner; failures are reported per-package.
- Symlinks (configs) and rendered templates are applied or updated as needed.
- Dropped packages are interactively reviewed for uninstalling.
- Conflicts abort unless `--force` is passed.
- Everything is idempotent: already-installed packages and already-correct symlinks are no-ops.

## Search

`pkg search` opens an interactive browser for system packages:

```sh
pkg search                  # browse all available packages
pkg search neovim           # pre-filtered search
pkg search --installed      # show only packages from your manifest
```

**Features:**
- Fuzzy search with fzf (or curses fallback if fzf isn't installed)
- Preview pane showing package info
- Action menu: `1: add`, `2: remove`, `3: print`
- Works with all supported package managers

## Pruning

`sync --prune` and `diff --prune` remove orphaned links previously managed by pkg. Safe, leaves edited/repurposed files alone.
