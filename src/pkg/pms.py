from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


class PackageManager:
    name: str = "?"
    label: str = "?"

    def check(self, package: str) -> bool:
        raise NotImplementedError

    def check_many(self, packages: list[str]) -> list[str]:
        return [p for p in packages if not self.check(p)]

    def install(self, packages: list[str]) -> int:
        raise NotImplementedError

    def remove(self, packages: list[str]) -> int:
        raise NotImplementedError

    def _quiet(self, *cmd: str) -> bool:
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
        return subprocess.run(cmd, check=False)

    def _run_silent(self, cmd: list[str]) -> int:
        return subprocess.run(
            list(cmd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
        ).returncode

    def _sudo(self, cmd: list[str]) -> list[str]:
        if os.geteuid() == 0:
            return cmd
        return ["sudo", *cmd]

    def _verify(self, missing: list[str]) -> int:
        remaining = self.check_many(missing)
        return 1 if remaining else 0


class Apt(PackageManager):
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
    name = "pacman"
    label = "Arch Linux (pacman)"

    def check(self, package: str) -> bool:
        return self._quiet("pacman", "-Q", package)

    def install(self, packages: list[str]) -> int:
        missing = self.check_many(packages)
        if not missing:
            return 0
        if self._run_silent(self._sudo(["pacman", "-S", "--noconfirm", "--needed", *missing])) != 0:
            return 1
        return self._verify(missing)

    def remove(self, packages: list[str]) -> int:
        present = [p for p in packages if self.check(p)]
        if not present:
            return 0
        if self._run_silent(self._sudo(["pacman", "-Rns", "--noconfirm", *present])) != 0:
            return 1
        return 1 if [p for p in present if self.check(p)] else 0


class Dnf(PackageManager):
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
    exe = shutil.which("brew")
    if exe:
        return exe
    for path in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if os.path.exists(path):
            return path
    return None


class Brew(PackageManager):
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
