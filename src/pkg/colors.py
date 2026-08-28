from __future__ import annotations

import os
import sys


def enabled(stream) -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


class Palette:
    def __init__(self, stream) -> None:
        self._on = enabled(stream)

    def _c(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self._on else text

    def cyan(self, text: str) -> str:
        return self._c("36", text)

    def green(self, text: str) -> str:
        return self._c("32", text)

    def red(self, text: str) -> str:
        return self._c("31", text)

    def yellow(self, text: str) -> str:
        return self._c("33", text)

    def magenta(self, text: str) -> str:
        return self._c("35", text)

    def bold(self, text: str) -> str:
        return self._c("1", text)

    def dim(self, text: str) -> str:
        return self._c("2", text)

    def section(self, text: str) -> str:
        return self._c("1;36", text)


out = Palette(sys.stdout)
err = Palette(sys.stderr)
