import pytest

from pkg import pms

PACKAGE = "zsh"


class FakeResult:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode


def stateful_runner(monkeypatch) -> tuple[list[list[str]], set[str]]:
    calls: list[list[str]] = []
    installed: set[str] = set()
    _REMOVE_TOKENS = ("-Rns", "remove", "uninstall", "del")

    def fake_run(cmd: list[str], **kw):
        calls.append(cmd)
        if any(tok in cmd for tok in _REMOVE_TOKENS):
            installed.discard(cmd[-1])
        elif "update" not in cmd:
            installed.add(cmd[-1])
        return FakeResult()

    monkeypatch.setattr(pms.subprocess, "run", fake_run)
    return calls, installed


def expect(base: list[str]) -> list[str]:
    return pms.PackageManager()._sudo(base)


@pytest.mark.parametrize(
    "cls,exe,install_cmd,remove_cmd",
    [
        (
            pms.Pacman,
            None,
            expect(["pacman", "-S", "--noconfirm", "--needed", PACKAGE]),
            expect(["pacman", "-Rns", "--noconfirm", PACKAGE]),
        ),
        (
            pms.Dnf,
            None,
            expect(["dnf", "install", "-y", PACKAGE]),
            expect(["dnf", "remove", "-y", PACKAGE]),
        ),
        (
            pms.Zypper,
            None,
            expect(["zypper", "--non-interactive", "install", PACKAGE]),
            expect(["zypper", "--non-interactive", "remove", "-y", PACKAGE]),
        ),
        (
            pms.Apk,
            None,
            expect(["apk", "add", "--no-interactive", PACKAGE]),
            ["apk", "del", "--no-interactive", PACKAGE],
        ),
        (
            pms.Brew,
            "/opt/homebrew/bin/brew",
            ["/opt/homebrew/bin/brew", "install", PACKAGE],
            ["/opt/homebrew/bin/brew", "uninstall", PACKAGE],
        ),
    ],
)
def test_backend_install_and_remove_shapes(monkeypatch, cls, exe, install_cmd, remove_cmd):
    calls, installed = stateful_runner(monkeypatch)
    if exe:
        monkeypatch.setattr(pms, "_brew", lambda: exe)
    pm = cls()
    pm.check = lambda p: p in installed

    assert pm.install([PACKAGE]) == 0
    assert pm.remove([PACKAGE]) == 0

    assert install_cmd in calls
    assert remove_cmd in calls
    assert calls.index(install_cmd) < calls.index(remove_cmd)


def test_apt_lazy_update_then_install(monkeypatch):
    calls, installed = stateful_runner(monkeypatch)
    pm = pms.Apt()
    pm.check = lambda p: p in installed
    assert pm.install(["fd"]) == 0
    assert ["sudo", "apt-get", "update"] in calls
    assert ["sudo", "apt-get", "install", "-y", "--no-install-recommends", "fd"] in calls
    assert calls.count(["sudo", "apt-get", "update"]) == 1


def test_apt_remove_shape(monkeypatch):
    calls, installed = stateful_runner(monkeypatch)
    pm = pms.Apt()
    pm.check = lambda p: p in installed
    installed.add("fd")
    assert pm.remove(["fd"]) == 0
    assert ["sudo", "apt-get", "remove", "-y", "fd"] in calls


def test_present_packages_short_circuit(monkeypatch):
    calls, installed = stateful_runner(monkeypatch)
    pm = pms.Pacman()
    pm.check = lambda p: p in installed
    installed.add(PACKAGE)
    assert pm.install([PACKAGE]) == 0
    installed.clear()
    assert pm.remove([PACKAGE]) == 0
    assert calls == []


def test_sudo_skipped_when_root(monkeypatch):
    calls, _ = stateful_runner(monkeypatch)
    monkeypatch.setattr(pms.os, "geteuid", lambda: 0)
    pm = pms.Pacman()
    pm.check = lambda p: False
    assert pm.install([PACKAGE]) == 1
    assert ["pacman", "-S", "--noconfirm", "--needed", PACKAGE] in calls


def test_verify_after_failed_install_returns_1(monkeypatch):
    monkeypatch.setattr(pms.subprocess, "run", lambda cmd, **kw: FakeResult(1))
    pm = pms.Pacman()
    pm.check = lambda p: False
    assert pm.install(["ghost"]) == 1
