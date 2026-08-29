# pkg

A declarative wraparound for exactly two things: your **system package manager** and **symlinks**.

Write a root `pkg.toml`, drop configs into `configs/`, run `pkg sync`, and the machine matches the manifest.

## Quick start

```sh
# Install
curl -fsSL https://raw.githubusercontent.com/graecen8/pkg/main/install.sh | bash

# Scaffold a new root
pkg init ~/dots

# Add your first package
pkg add zsh

# Sync everything
pkg sync
```

## Documentation

- [Configuration reference](configuration.md) — full `pkg.toml` manifest syntax
- [Architecture](architecture.md) — module responsibilities and data flow
- [Contributing](contributing.md) — development setup and guidelines

The [README](../README.md) contains a comprehensive user guide covering all features.
