# Contributing

## Development setup

```sh
git clone https://github.com/graecen8/pkg.git
cd pkg
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Or with just:

```sh
just install
```

## Running tests

```sh
just test        # or: pytest
just lint        # or: ruff check
just build       # self-contained ./pkg zipapp
```

## Code style

- Python 3.11+ (uses `X | Y` unions, `tomllib`, `match` if needed).
- Google-style docstrings for all public modules, classes, and functions.
- Line length: 100 characters.
- Linter: ruff.
- No comments unless requested.
- No unnecessary abstractions — keep things direct and readable.

## Adding a package manager

1. Subclass `PackageManager` in `src/pkg/pms.py`.
2. Implement `check()`, `install()`, and `remove()`.
3. Add the class to `_REGISTRY` and the appropriate family tuple in `_FAMILIES`.
4. Add tests in `tests/`.

## Testing

Tests live in `tests/`. Run with `pytest`. Key test modules:

- `test_pms.py` — package manager detection and backend behavior
- `test_linker.py` — symlink planning, conflict detection, state management
- `test_cli.py` — CLI command behavior and integration

## Commit style

Short, descriptive messages. No conventional commits prefix required — use your judgment.
