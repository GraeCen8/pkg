# Features

- Declarative state for system packages and symlinks, with one manifest and configs dir
- Cross-distro: supports apt, pacman (+yay/paru), dnf, zypper, apk, brew, and flatpak
- Module system: nestable, with per-OS/profile rules and tree-merge
- `pkg` mode (whole-dir symlink to ~/.config/<name>) or `stow` mode (file-level, GNUs Stow compatible)
- [Git](configuration.md#git) integration: auto-pull, auto-commit
- Zero-config per-config mapping—auto link everything in `configs/`
- Extensible via modules/roots
- Interactive orphan prune and uninstall review
- `.tmpl` file templating with built-in/custom variables
- Safety: conflict detection, idempotent, never touches unowned files
- Colorful CLI with batch mode, with output suitable for CI
- [Hooks](configuration.md#hooks) for post-sync custom steps
- **Interactive package search** with fzf/curses fallback and preview
- **Flatpak support** — install/remove/search Flatpak applications
- **Brew cask support** — automatically detects and manages casks
- **Better error messages** — shows actual PM output on install/remove failure
- **CI-friendly spinner** — shows ok/failed status in non-interactive mode

See [CLI documentation](cli.md) for usage and [Configuration](configuration.md) for manifest details.
