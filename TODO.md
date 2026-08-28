# TODO

Backlog and roadmap for `pkg`. Roughly priority-ordered; checked items are done.

## Next

- [ ] **Dogfood on this machine** — give `short` a real `~/dots` root, run
      `pkg sync`, fix what hurts.

## v0.2 (in progress)

- [x] **Git-backed roots** — per-root `[git] url`; `pkg sync` runs
      `git pull --ff-only` before that root's stage. `--no-git` disables.
- [x] **Pruning** — `pkg sync --prune`: removes orphaned symlinks / rendered
      files no longer in the manifest; dropped packages are reviewed, never
      auto-removed.
- [x] **Per-host templating** — `*.tmpl` files in stow-mode configs render via
      `$var` syntax (built-ins `host`, `os`, `home` + `[config] vars`).
- [x] Hardened PM tests — mocked `_run`/`_quiet` asserting command shapes for
      all six backends (apt lazy-update path included).

## v0.x

- [ ] `pkg new <name>` — scaffold a config or module dir.
- [ ] Secrets — age-encrypted dotfiles, decrypted only at apply time.
- [ ] More PM fronts — AUR helpers (yay/paru), flatpak, brew casks.
- [ ] Glob / exclude support inside configs (ignore files within stow payload).
- [x] `pkg sync --prune` review step made interactive/non-interactive aware
      (dropped packages: tty prompt to uninstall `[y/N]`, script-safe listing).

## Explicit non-goals (v0)

- Building from source / content store.
- Package removal without review.
- Templating secrets into plaintext files.