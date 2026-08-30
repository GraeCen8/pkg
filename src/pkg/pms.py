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

    def install(self, packages: list[str]) -> tuple[int, str]:
        """Install *packages*.  Return (0, "") on success, (non-zero, error_msg) on failure."""
        raise NotImplementedError

    def remove(self, packages: list[str]) -> tuple[int, str]:
        """Remove *packages*.  Return (0, "") on success, (non-zero, error_msg) on failure."""
        raise NotImplementedError

    def list_available(self) -> list[str]:
        """Return a list of all available packages from the system PM."""
        raise NotImplementedError

    def list_installed(self) -> list[str]:
        """Return a list of all installed packages."""
        raise NotImplementedError

    def print_info(self, package: str) -> str:
        """Return formatted, colored info for *package*."""
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

    def _run_captured(self, cmd: list[str]) -> tuple[int, str]:
        """Run *cmd*, capturing output. Return (returncode, error_output)."""
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return 0, ""
        error = result.stderr.strip() or result.stdout.strip()
        if not error:
            error = f"exit code {result.returncode}"
        return result.returncode, error

    def _sudo(self, cmd: list[str]) -> list[str]:
        """Prepend ``sudo`` to *cmd* unless already running as root."""
        if os.geteuid() == 0:
            return cmd
        return ["sudo", *cmd]

    def _verify(self, missing: list[str]) -> tuple[int, str]:
        """Re-check that *missing* packages are now installed.  Return (0, "") if all present."""
        remaining = self.check_many(missing)
        if remaining:
            return 1, f"still missing after install: {', '.join(remaining)}"
        return 0, ""


class Apt(PackageManager):
    """Debian/Ubuntu ``apt-get`` backend with lazy ``update``."""

    name = "apt"
    label = "Debian/Ubuntu (apt)"

    def __init__(self) -> None:
        self._updated = False

    def check(self, package: str) -> bool:
        return self._quiet("dpkg", "-s", package)

    def install(self, packages: list[str]) -> tuple[int, str]:
        missing = self.check_many(packages)
        if not missing:
            return 0, ""
        if not self._updated:
            rc, err = self._run_captured(self._sudo(["apt-get", "update"]))
            if rc != 0:
                return rc, f"apt-get update failed: {err}"
            self._updated = True
        still = self.check_many(missing)
        rc, err = self._run_captured(
            self._sudo(["apt-get", "install", "-y", "--no-install-recommends", *still])
        )
        if rc != 0:
            self._updated = False
            return rc, f"apt-get install failed: {err}"
        return self._verify(still)

    def remove(self, packages: list[str]) -> tuple[int, str]:
        present = [p for p in packages if self.check(p)]
        if not present:
            return 0, ""
        rc, err = self._run_captured(self._sudo(["apt-get", "remove", "-y", *present]))
        if rc != 0:
            return rc, f"apt-get remove failed: {err}"
        remaining = [p for p in present if self.check(p)]
        if remaining:
            return 1, f"could not remove: {', '.join(remaining)}"
        return 0, ""

    def list_available(self) -> list[str]:
        if not self._updated:
            self._run_captured(self._sudo(["apt-get", "update"]))
            self._updated = True
        result = subprocess.run(
            ["apt-cache", "search", "."],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        return [line.split()[0] for line in result.stdout.splitlines() if line.strip()]

    def list_installed(self) -> list[str]:
        result = subprocess.run(
            ["dpkg", "--get-selections"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        return [line.split()[0] for line in result.stdout.splitlines() if "\tinstall" in line]

    def print_info(self, package: str) -> str:
        result = subprocess.run(
            ["apt-cache", "show", package],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return f"Package '{package}' not found."
        return result.stdout


class Pacman(PackageManager):
    """Arch Linux ``pacman`` backend; automatically uses ``yay`` or ``paru`` if available for AUR support."""

    name = "pacman"
    label = "Arch Linux (pacman)"

    def _bin(self) -> str:
        return "yay" if shutil.which("yay") else "pacman"

    def _is_aur_helper(self) -> bool:
        """Return True if an AUR helper (yay/paru) is available."""
        return shutil.which("yay") is not None or shutil.which("paru") is not None

    def check(self, package: str) -> bool:
        return self._quiet(self._bin(), "-Q", package)

    def install(self, packages: list[str]) -> tuple[int, str]:
        missing = self.check_many(packages)
        if not missing:
            return 0, ""

        bin_name = self._bin()

        if self._is_aur_helper():
            # AUR helpers handle sudo internally; wrapping in sudo
            # causes nested sudo prompts that fail without a terminal.
            cmd = [bin_name, "-S", "--noconfirm", "--needed", *missing]
        else:
            cmd = self._sudo([bin_name, "-S", "--noconfirm", "--needed", *missing])

        rc, error = self._run_captured(cmd)
        if rc != 0:
            return rc, error

        return self._verify(missing)

    def remove(self, packages: list[str]) -> tuple[int, str]:
        present = [p for p in packages if self.check(p)]
        if not present:
            return 0, ""

        bin_name = self._bin()

        if self._is_aur_helper():
            cmd = [bin_name, "-Rns", "--noconfirm", *present]
        else:
            cmd = self._sudo([bin_name, "-Rns", "--noconfirm", *present])

        rc, error = self._run_captured(cmd)
        if rc != 0:
            return rc, error

        remaining = [p for p in present if self.check(p)]
        if remaining:
            return 1, f"could not remove: {', '.join(remaining)}"
        return 0, ""

    def list_available(self) -> list[str]:
        bin_name = self._bin()
        result = subprocess.run(
            [bin_name, "-Slq"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def list_installed(self) -> list[str]:
        bin_name = self._bin()
        result = subprocess.run(
            [bin_name, "-Qq"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def print_info(self, package: str) -> str:
        bin_name = self._bin()
        result = subprocess.run(
            [bin_name, "-Si", package],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return f"Package '{package}' not found."
        return result.stdout


class Dnf(PackageManager):
    """Fedora/RHEL ``dnf`` backend."""

    name = "dnf"
    label = "Fedora/RHEL (dnf)"

    def check(self, package: str) -> bool:
        return self._quiet("rpm", "-q", package)

    def install(self, packages: list[str]) -> tuple[int, str]:
        missing = self.check_many(packages)
        if not missing:
            return 0, ""
        rc, error = self._run_captured(self._sudo(["dnf", "install", "-y", *missing]))
        if rc != 0:
            return rc, error
        return self._verify(missing)

    def remove(self, packages: list[str]) -> tuple[int, str]:
        present = [p for p in packages if self.check(p)]
        if not present:
            return 0, ""
        rc, error = self._run_captured(self._sudo(["dnf", "remove", "-y", *present]))
        if rc != 0:
            return rc, error
        remaining = [p for p in present if self.check(p)]
        if remaining:
            return 1, f"could not remove: {', '.join(remaining)}"
        return 0, ""

    def list_available(self) -> list[str]:
        result = subprocess.run(
            ["dnf", "list", "available", "--quiet"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        lines = result.stdout.splitlines()[2:]  # skip header
        return [line.split()[0].rsplit(".", 1)[0] for line in lines if line.strip()]

    def list_installed(self) -> list[str]:
        result = subprocess.run(
            ["dnf", "list", "installed", "--quiet"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        lines = result.stdout.splitlines()[2:]  # skip header
        return [line.split()[0].rsplit(".", 1)[0] for line in lines if line.strip()]

    def print_info(self, package: str) -> str:
        result = subprocess.run(
            ["dnf", "info", package],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return f"Package '{package}' not found."
        return result.stdout


class Zypper(PackageManager):
    """openSUSE ``zypper`` backend."""

    name = "zypper"
    label = "openSUSE (zypper)"

    def check(self, package: str) -> bool:
        return self._quiet("rpm", "-q", package)

    def install(self, packages: list[str]) -> tuple[int, str]:
        missing = self.check_many(packages)
        if not missing:
            return 0, ""
        rc, error = self._run_captured(
            self._sudo(["zypper", "--non-interactive", "install", *missing])
        )
        if rc != 0:
            return rc, error
        return self._verify(missing)

    def remove(self, packages: list[str]) -> tuple[int, str]:
        present = [p for p in packages if self.check(p)]
        if not present:
            return 0, ""
        cmd = self._sudo(["zypper", "--non-interactive", "remove", "-y", *present])
        rc, error = self._run_captured(cmd)
        if rc != 0:
            return rc, error
        remaining = [p for p in present if self.check(p)]
        if remaining:
            return 1, f"could not remove: {', '.join(remaining)}"
        return 0, ""

    def list_available(self) -> list[str]:
        result = subprocess.run(
            ["zypper", "--non-interactive", "search", "-i"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        packages = []
        for line in result.stdout.splitlines():
            if line.startswith(("v ", "i ")):
                parts = line.split("|")
                if len(parts) >= 2:
                    packages.append(parts[1].strip())
        return packages

    def list_installed(self) -> list[str]:
        result = subprocess.run(
            ["zypper", "--non-interactive", "packages", "-i"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        packages = []
        for line in result.stdout.splitlines():
            if "|" in line and not line.startswith("---"):
                parts = line.split("|")
                if len(parts) >= 2:
                    name = parts[1].strip()
                    if name and name != "Name":
                        packages.append(name)
        return packages

    def print_info(self, package: str) -> str:
        result = subprocess.run(
            ["zypper", "--non-interactive", "info", package],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return f"Package '{package}' not found."
        return result.stdout


class Apk(PackageManager):
    """Alpine ``apk`` backend."""

    name = "apk"
    label = "Alpine (apk)"

    def check(self, package: str) -> bool:
        return self._quiet("apk", "info", "-e", package)

    def install(self, packages: list[str]) -> tuple[int, str]:
        missing = self.check_many(packages)
        if not missing:
            return 0, ""
        rc, error = self._run_captured(self._sudo(["apk", "add", "--no-interactive", *missing]))
        if rc != 0:
            return rc, error
        return self._verify(missing)

    def remove(self, packages: list[str]) -> tuple[int, str]:
        present = [p for p in packages if self.check(p)]
        if not present:
            return 0, ""
        rc, error = self._run_captured(["apk", "del", "--no-interactive", *present])
        if rc != 0:
            return rc, error
        remaining = [p for p in present if self.check(p)]
        if remaining:
            return 1, f"could not remove: {', '.join(remaining)}"
        return 0, ""

    def list_available(self) -> list[str]:
        result = subprocess.run(
            ["apk", "search"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def list_installed(self) -> list[str]:
        result = subprocess.run(
            ["apk", "list", "--installed"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        packages = []
        for line in result.stdout.splitlines():
            if line.strip():
                parts = line.split()
                if parts:
                    # Strip version suffix like -1.2.3-r0
                    name = parts[0].rsplit("-", 2)[0] if len(parts) > 1 else parts[0]
                    packages.append(name)
        return packages

    def print_info(self, package: str) -> str:
        result = subprocess.run(
            ["apk", "info", package],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return f"Package '{package}' not found."
        return result.stdout


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
    """macOS Homebrew backend with formula and cask support."""

    name = "brew"
    label = "Homebrew (brew)"

    def __init__(self) -> None:
        exe = _brew()
        if exe is None:
            sys.exit("cannot find brew")
        self._brew = exe

    def _is_cask(self, package: str) -> bool:
        """Return True if *package* is a Homebrew cask."""
        return self._quiet(self._brew, "list", "--cask", package)

    def check(self, package: str) -> bool:
        return self._quiet(self._brew, "list", "--formula", package) or self._is_cask(package)

    def install(self, packages: list[str]) -> tuple[int, str]:
        missing = self.check_many(packages)
        if not missing:
            return 0, ""
        formulas = [p for p in missing if not self._is_cask(p)]
        casks = [p for p in missing if self._is_cask(p)]
        if formulas:
            rc, error = self._run_captured([self._brew, "install", *formulas])
            if rc != 0:
                return rc, error
        if casks:
            rc, error = self._run_captured([self._brew, "install", "--cask", *casks])
            if rc != 0:
                return rc, error
        return self._verify(missing)

    def remove(self, packages: list[str]) -> tuple[int, str]:
        present = [p for p in packages if self.check(p)]
        if not present:
            return 0, ""
        formulas = [p for p in present if not self._is_cask(p)]
        casks = [p for p in present if self._is_cask(p)]
        if formulas:
            rc, error = self._run_captured([self._brew, "uninstall", *formulas])
            if rc != 0:
                return rc, error
        if casks:
            rc, error = self._run_captured([self._brew, "uninstall", "--cask", *casks])
            if rc != 0:
                return rc, error
        remaining = [p for p in present if self.check(p)]
        if remaining:
            return 1, f"could not remove: {', '.join(remaining)}"
        return 0, ""

    def list_available(self) -> list[str]:
        result = subprocess.run(
            [self._brew, "search"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def list_installed(self) -> list[str]:
        result = subprocess.run(
            [self._brew, "list", "--formula"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def print_info(self, package: str) -> str:
        result = subprocess.run(
            [self._brew, "info", package],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return f"Package '{package}' not found."
        return result.stdout


class Flatpak(PackageManager):
    """Flatpak backend for universal Linux packages."""

    name = "flatpak"
    label = "Flatpak"

    def check(self, package: str) -> bool:
        return self._quiet("flatpak", "list", "--app", "--columns=application", package)

    def install(self, packages: list[str]) -> tuple[int, str]:
        missing = self.check_many(packages)
        if not missing:
            return 0, ""
        rc, error = self._run_captured(["flatpak", "install", "-y", "flathub", *missing])
        if rc != 0:
            return rc, error
        return self._verify(missing)

    def remove(self, packages: list[str]) -> tuple[int, str]:
        present = [p for p in packages if self.check(p)]
        if not present:
            return 0, ""
        rc, error = self._run_captured(["flatpak", "uninstall", "-y", *present])
        if rc != 0:
            return rc, error
        remaining = [p for p in present if self.check(p)]
        if remaining:
            return 1, f"could not remove: {', '.join(remaining)}"
        return 0, ""

    def list_available(self) -> list[str]:
        result = subprocess.run(
            ["flatpak", "search", "--columns=application"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def list_installed(self) -> list[str]:
        result = subprocess.run(
            ["flatpak", "list", "--app", "--columns=application"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def print_info(self, package: str) -> str:
        result = subprocess.run(
            ["flatpak", "info", package],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return f"Package '{package}' not found."
        return result.stdout


_REGISTRY = (Pacman, Apt, Dnf, Zypper, Apk, Brew, Flatpak)

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
