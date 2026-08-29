"""Package manager abstraction with auto-detection for Linux and macOS."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


class PackageManager:
    """Abstract base for OS package manager backends.

    Subclasses must implement :meth:`check`, :meth:`install`, and
    :meth:`remove`.  Helper methods handle sudo, subprocesses, and
    post-install verification.
    """

    name: str = "?"
    label: str = "?"

    def check(self, package: str) -> bool:
        """Return True if *package* is already installed."""
        raise NotImplementedError

    def check_many(self, packages: list[str]) -> list[str]:
        """Return the subset of *packages* that are not currently installed."""
        return [p for p in packages if not self.check(p)]

    def install(self, packages: list[str]) -> int:
        """Install *packages*.  Return 0 on success, non-zero on failure."""
        raise NotImplementedError

    def remove(self, packages: list[str]) -> int:
        """Remove *packages*.  Return 0 on success, non-zero on failure."""
        raise NotImplementedError

    def _quiet(self, *cmd: str) -> bool:
        """Run *cmd* silently, returning True if it exits 0."""
        return (
            subprocess.run(
                list(cmd),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode
            == 0
        )

    def _run(self, cmd: list[str]) -> subprocess.CompletedProcess:
        """Run *cmd* without suppressing output."""
        return subprocess.run(cmd, check=False)

    def _run_silent(self, cmd: list[str]) -> int:
        """Run *cmd* with output suppressed, returning the exit code."""
        return subprocess.run(
            list(cmd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
        ).returncode

    def _sudo(self, cmd: list[str]) -> list[str]:
        """Prepend ``sudo`` to *cmd* unless already running as root."""
        if os.geteuid() == 0:
            return cmd
        return ["sudo", *cmd]

    def _verify(self, missing: list[str]) -> int:
        """Re-check that *missing* packages are now installed.  Return 0 if all present."""
        remaining = self.check_many(missing)
        return 1 if remaining else 0


class Apt(PackageManager):
    """Debian/Ubuntu ``apt-get`` backend with lazy ``update``."""

    name = "apt"
    label = "Debian/Ubuntu (apt)"

    def __init__(self) -> None:
        self._updated = False

    def check(self, package: str) -> bool:
        return self._quiet("dpkg", "-s", package)

    def install(self, packages: list[str]) -> int:
        missing = self.check_many(packages)
        if not missing:
            return 0
        if not self._updated:
            if self._run_silent(self._sudo(["apt-get", "update"])) != 0:
                return 1
            self._updated = True
        still = self.check_many(missing)
        if (
            self._run_silent(
                self._sudo(["apt-get", "install", "-y", "--no-install-recommends", *still])
            )
            != 0
        ):
            return 1
        return self._verify(still)

    def remove(self, packages: list[str]) -> int:
        present = [p for p in packages if self.check(p)]
        if not present:
            return 0
        if self._run_silent(self._sudo(["apt-get", "remove", "-y", *present])) != 0:
            return 1
        return 1 if [p for p in present if self.check(p)] else 0


class Pacman(PackageManager):
    """Arch Linux ``pacman`` backend; automatically uses ``yay`` or ``paru`` if available for AUR support."""

    name = "pacman"
    label = "Arch Linux (pacman)"

    def _bin(self) -> str:
        return "yay" if shutil.which("yay") else "pacman"

    def check(self, package: str) -> bool:
        return self._quiet(self._bin(), "-Q", package)

    def install(self, packages: list[str]) -> int:
        missing = self.check_many(packages)
        if not missing:
            return 0
        if (
            self._run_silent(self._sudo([self._bin(), "-S", "--noconfirm", "--needed", *missing]))
            != 0
        ):
            return 1
        return self._verify(missing)

    def remove(self, packages: list[str]) -> int:
        present = [p for p in packages if self.check(p)]
        if not present:
            return 0
        if self._run_silent(self._sudo([self._bin(), "-Rns", "--noconfirm", *present])) != 0:
            return 1
        return 1 if [p for p in present if self.check(p)] else 0


class Dnf(PackageManager):
    """Fedora/RHEL ``dnf`` backend."""

    name = "dnf"
    label = "Fedora/RHEL (dnf)"

    def check(self, package: str) -> bool:
        return self._quiet("rpm", "-q", package)

    def install(self, packages: list[str]) -> int:
        missing = self.check_many(packages)
        if not missing:
            return 0
        if self._run_silent(self._sudo(["dnf", "install", "-y", *missing])) != 0:
            return 1
        return self._verify(missing)

    def remove(self, packages: list[str]) -> int:
        present = [p for p in packages if self.check(p)]
        if not present:
            return 0
        if self._run_silent(self._sudo(["dnf", "remove", "-y", *present])) != 0:
            return 1
        return 1 if [p for p in present if self.check(p)] else 0


class Zypper(PackageManager):
    """openSUSE ``zypper`` backend."""

    name = "zypper"
    label = "openSUSE (zypper)"

    def check(self, package: str) -> bool:
        return self._quiet("rpm", "-q", package)

    def install(self, packages: list[str]) -> int:
        missing = self.check_many(packages)
        if not missing:
            return 0
        if self._run_silent(self._sudo(["zypper", "--non-interactive", "install", *missing])) != 0:
            return 1
        return self._verify(missing)

    def remove(self, packages: list[str]) -> int:
        present = [p for p in packages if self.check(p)]
        if not present:
            return 0
        cmd = self._sudo(["zypper", "--non-interactive", "remove", "-y", *present])
        if self._run_silent(cmd) != 0:
            return 1
        return 1 if [p for p in present if self.check(p)] else 0


class Apk(PackageManager):
    """Alpine ``apk`` backend."""

    name = "apk"
    label = "Alpine (apk)"

    def check(self, package: str) -> bool:
        return self._quiet("apk", "info", "-e", package)

    def install(self, packages: list[str]) -> int:
        missing = self.check_many(packages)
        if not missing:
            return 0
        if self._run_silent(self._sudo(["apk", "add", "--no-interactive", *missing])) != 0:
            return 1
        return self._verify(missing)

    def remove(self, packages: list[str]) -> int:
        present = [p for p in packages if self.check(p)]
        if not present:
            return 0
        if self._run_silent(["apk", "del", "--no-interactive", *present]) != 0:
            return 1
        return 1 if [p for p in present if self.check(p)] else 0


def _brew() -> str | None:
    """Locate the Homebrew executable on macOS."""
    exe = shutil.which("brew")
    if exe:
        return exe
    for path in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if os.path.exists(path):
            return path
    return None


class Brew(PackageManager):
    """macOS Homebrew backend."""

    name = "brew"
    label = "Homebrew (brew)"

    def __init__(self) -> None:
        exe = _brew()
        if exe is None:
            sys.exit("cannot find brew")
        self._brew = exe

    def check(self, package: str) -> bool:
        return self._quiet(self._brew, "list", "--formula", package)

    def install(self, packages: list[str]) -> int:
        missing = self.check_many(packages)
        if not missing:
            return 0
        if self._run_silent([self._brew, "install", *missing]) != 0:
            return 1
        return self._verify(missing)

    def remove(self, packages: list[str]) -> int:
        present = [p for p in packages if self.check(p)]
        if not present:
            return 0
        if self._run_silent([self._brew, "uninstall", *present]) != 0:
            return 1
        return 1 if [p for p in present if self.check(p)] else 0


_REGISTRY = (Pacman, Apt, Dnf, Zypper, Apk, Brew)

_FAMILIES = (
    (("arch", "manjaro", "endeavouros", "garuda", "cachyos"), Pacman),
    (("debian", "ubuntu", "raspbian", "linuxmint", "pop", "kali", "devuan"), Apt),
    (("fedora", "rhel", "centos", "rocky", "almalinux", "ol", "nobara"), Dnf),
    (("opensuse", "suse", "sles"), Zypper),
    (("alpine",), Apk),
)


def detect(override: str | None = None) -> PackageManager:
    """Detect and return the appropriate package manager for the current system.

    On macOS returns Homebrew. On Linux, reads ``/etc/os-release`` to match
    the distribution to a known backend. Pass *override* to force a specific
    manager (e.g. from ``[manager] name``).

    Raises:
        SystemExit: If the override is unknown or auto-detection fails.
    """
    if override:
        for cls in _REGISTRY:
            if cls.name == override.lower():
                return cls()
        sys.exit(f"unknown package manager in [manager] name: {override!r}")
    if platform.system() == "Darwin":
        return Brew()
    ids: list[str] = []
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith(("ID=", "ID_LIKE=")):
                _, value = line.split("=", 1)
                ids.extend(v.strip().strip('"') for v in value.split())
    except OSError:
        pass
    for family, cls in _FAMILIES:
        if set(family) & set(ids):
            return cls()
    sys.exit("cannot auto-detect a package manager from /etc/os-release")


if __name__ == "__main__":
    print(detect().label)
