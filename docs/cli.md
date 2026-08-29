# CLI Usage

---

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/graecen8/pkg/main/install.sh | bash
```

## Common commands

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

## How sync works

`pkg sync` runs in order: git pull → check → install → symlink → hooks.

- The system package manager is auto-detected from `/etc/os-release`
- Each package is installed individually with a spinner; failures are reported per-package.
- Symlinks (configs) and rendered templates are applied or updated as needed.
- Dropped packages are interactively reviewed for uninstalling.
- Conflicts abort unless `--force` is passed.
- Everything is idempotent: already-installed packages and already-correct symlinks are no-ops.

## Pruning

`sync --prune` and `plan --prune` remove orphaned links previously managed by pkg. Safe, leaves edited/repurposed files alone.
