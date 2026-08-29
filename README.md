# pkg

pkg manages system packages and application configs with ease using a minimal design for everyday use, cross-distro flexibility, and reproducibility.

- **Blazing fast workflows:** Add, remove, and sync packages and configs with a single command.
- **Smart mapping:** Switch between whole-dir, file-level (GNU Stow compatible), or templated configs out of the box.
- **Real modules:** Nestable repo structure with per-OS/profile rules—supporting all your machines in one place.
- **Safety first:** Built-in idempotence, conflict detection, and dry-run planning.

## Quick start

```sh
curl -fsSL https://raw.githubusercontent.com/graecen8/pkg/main/install.sh | bash # Install pkg
pkg init ~/dots      # Scaffold a new root
pkg add nvim     # Add packages
mv ~/.config/nvim ~/dots/configs/nvim    # Add configs
pkg sync             # Sync everything
```

## Documentation

- [Features](docs/features.md)
- [Usage Guide](docs/usage.md)
- [Configuration reference](docs/configuration.md)
- [CLI commands](docs/cli.md)
- [Architecture](docs/architecture.md)
- [Contributing & Development](docs/contributing.md)

---

For a full introduction and common workflows, start with the [Usage Guide](docs/usage.md).
