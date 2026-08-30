# TODO

Backlog and roadmap for `pkg`. Roughly priority-ordered; checked items are done.

## v0.3 (current)

- [x] **Git-backed roots** — per-root `[git] url`; `pkg sync` runs
      `git pull --ff-only` before that root's stage. `--no-git` disables.
- [x] **Pruning** — `pkg sync --prune`: removes orphaned symlinks / rendered
      files no longer in the manifest; dropped packages are reviewed, never
      auto-removed.
- [x] **Per-host templating** — `*.tmpl` files in stow-mode configs render via
      `$var` syntax (built-ins `host`, `os`, `home` + `[config] vars`).
- [x] Hardened PM tests — mocked `_run`/`_quiet` asserting command shapes for
      all backends.
- [x] **Flatpak + Brew casks** — new Flatpak backend; Brew now handles
      formulas and casks automatically.
- [x] **Better error messages** — install/remove show actual PM output on failure.
- [x] **pkg diff** — renamed from `plan` for clarity.
- [x] **CI-friendly spinner** — shows ok/failed instead of disappearing.

## v0.x

- [x] Profiles — `[config] profiles` + `profiles = [...]` on `[[system]]`
      blocks (role filtering, like `os`).
- [x] Ignore globs — `[config] ignore = [...]` excludes files/configs from the
      link plan.
- [x] `[git] autocommit` — `pkg add`/`pkg remove` commit `pkg.toml` in git
      roots.
- [x] More PM fronts — yay/paru (no sudo wrapping), flatpak, brew casks.
- [x] Glob / exclude support inside configs (ignore files within stow payload).
- [x] `pkg sync --prune` review step made interactive/non-interactive aware
      (dropped packages: tty prompt to uninstall `[y/N]`, script-safe listing).
- [ ] `pkg new <name>` — scaffold a config or module dir.
- [ ] Secrets — age-encrypted dotfiles, decrypted only at apply time.
- [ ] `pkg diff --watch` — live preview of changes.
- [ ] Parallel package installs for faster sync.
- [ ] `pkg edit` — open pkg.toml or a config in $EDITOR.

## Explicit non-goals (v0)

- Building from source / content store.
- Package removal without review.
- Templating secrets into plaintext files.
