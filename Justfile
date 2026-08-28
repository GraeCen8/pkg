default:
    @just --list

venv := ".venv"

# Build a self-contained ./pkg executable you can run anywhere
build:
    rm -rf .stage
    mkdir -p .stage
    cp -r src/pkg .stage/pkg
    printf 'from pkg.cli import main\nraise SystemExit(main())\n' > .stage/__main__.py
    {{venv}}/bin/python -m zipapp .stage -o ./pkg -p '/usr/bin/env python3'
    rm -rf .stage
    chmod +x ./pkg

# Build a wheel + sdist into dist/ (for publishing)
dist:
    {{venv}}/bin/python -m build

# Run the CLI, e.g. `just run --version` or `just run -- plan -R ~/dots`
run *args="--help": build
    ./pkg {{args}}

# Run the test suite
test:
    {{venv}}/bin/pytest -q

# Lint and check formatting
lint:
    {{venv}}/bin/ruff check .
    {{venv}}/bin/ruff format --check .

# (Re)install the package + dev deps into the venv
install:
    {{venv}}/bin/pip install -e ".[dev]"