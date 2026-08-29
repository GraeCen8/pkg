# Usage Guide

A sample workflow:

1. Scaffold a new root (directory):
   ```sh
   pkg init ~/dots
   ```
2. Add packages:
   ```sh
   pkg add zsh git nvim
   ```
3. Add configs:
   ```sh
   mv ~/.config/zsh ~/dots/configs/zsh
   mv ~/.config/nvim ~/dots/configs/nvim
   ```
4. Sync everything:
   ```sh
   pkg sync
   ```

see [index.md](index.md) for more details on the manifest and configuration.


