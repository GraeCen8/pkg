#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/graecen8/pkg.git"
REPO_DEFAULT_DIR="pkg-src"
OS=$(uname -s)

case "$OS" in
  Linux|Darwin) ;;
  *)
    echo "Unsupported OS: $OS (only Linux and macOS are supported)" >&2
    exit 1
    ;;
esac

# If not in a pkg repo, clone it to $REPO_DEFAULT_DIR
if [ ! -f pyproject.toml ]; then
  if [ ! -d "$REPO_DEFAULT_DIR" ]; then
    echo "No pyproject.toml found, cloning repo to ./$REPO_DEFAULT_DIR ..."
    git clone "$REPO_URL" "$REPO_DEFAULT_DIR"
  else
    echo "Using existing repo in $REPO_DEFAULT_DIR ..."
  fi
  cd "$REPO_DEFAULT_DIR"
else
  echo "pyproject.toml found, continuing from present directory ..."
fi

# Python prerequisites
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required. Please install it." >&2
  exit 1
fi
if ! python3 -m pip --version >/dev/null 2>&1; then
  echo "Installing pip..."
  curl -sS https://bootstrap.pypa.io/get-pip.py | python3
fi
if ! python3 -m venv --help >/dev/null 2>&1; then
  echo "Python venv module not found. Please install 'python3-venv' (Debian/Ubuntu) or the equivalent." >&2
  exit 1
fi

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

. .venv/bin/activate
pip install --upgrade pip
pip install -e "."

# Build zipapp
rm -rf .stage
mkdir -p .stage
cp -r src/pkg .stage/pkg
printf 'from pkg.cli import main\nraise SystemExit(main())\n' > .stage/__main__.py
.venv/bin/python -m zipapp .stage -o ./pkg -p '/usr/bin/env python3'
rm -rf .stage
chmod +x ./pkg

echo "Installing pkg to /usr/bin/pkg..."
if [ "$(id -u)" -eq 0 ]; then
  cp ./pkg /usr/bin/pkg
else
  sudo cp ./pkg /usr/bin/pkg
fi

echo "Installation complete! Run 'pkg --help' to verify."
