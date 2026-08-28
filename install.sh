#!/usr/bin/env bash
set -euo pipefail

OS=$(uname -s)

case "$OS" in
  Linux|Darwin)
    ;;
  *)
    echo "Unsupported OS: $OS (only Linux and macOS are supported)" >&2
    exit 1
    ;;
esac

cd "$(dirname "$0")"

# Ensure python3, pip, venv modules exist
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

# Create the venv if not present
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

. .venv/bin/activate
pip install --upgrade pip
pip install -e "."

# Build the zipapp as in Justfile
rm -rf .stage
mkdir -p .stage
cp -r src/pkg .stage/pkg
printf 'from pkg.cli import main\nraise SystemExit(main())\n' > .stage/__main__.py
.venv/bin/python -m zipapp .stage -o ./pkg -p '/usr/bin/env python3'
rm -rf .stage
chmod +x ./pkg

echo "Installing pkg to /usr/bin/pkg (sudo required)..."
sudo cp ./pkg /usr/bin/pkg

echo "Installation complete! Run 'pkg --help' to verify."
