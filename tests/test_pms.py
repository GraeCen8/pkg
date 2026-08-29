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
    monkeypatch.setattr(pms.shutil, "which", lambda name: None)
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


# ---------------------------------------------------------------------------
# detect() tests
# ---------------------------------------------------------------------------


def _mock_os_release(content: str):
    """Return a function that mocks Path.read_text for /etc/os-release."""

    def fake_read_text(self, *args, **kwargs):
        if str(self) == "/etc/os-release":
            return content
        raise OSError(f"unexpected read: {self}")

    return fake_read_text


def test_detect_linux_debian(monkeypatch):
    monkeypatch.setattr(pms.Path, "read_text", _mock_os_release("ID=ubuntu\n"))
    monkeypatch.setattr(pms.platform, "system", lambda: "Linux")
    result = pms.detect()
    assert isinstance(result, pms.Apt)


def test_detect_linux_arch(monkeypatch):
    monkeypatch.setattr(pms.Path, "read_text", _mock_os_release("ID=arch\n"))
    monkeypatch.setattr(pms.platform, "system", lambda: "Linux")
    result = pms.detect()
    assert isinstance(result, pms.Pacman)


def test_detect_linux_fedora(monkeypatch):
    monkeypatch.setattr(pms.Path, "read_text", _mock_os_release("ID=fedora\n"))
    monkeypatch.setattr(pms.platform, "system", lambda: "Linux")
    result = pms.detect()
    assert isinstance(result, pms.Dnf)


def test_detect_linux_id_like_fallback(monkeypatch):
    monkeypatch.setattr(
        pms.Path,
        "read_text",
        _mock_os_release('ID=centos\nID_LIKE="rhel fedora"\n'),
    )
    monkeypatch.setattr(pms.platform, "system", lambda: "Linux")
    result = pms.detect()
    assert isinstance(result, pms.Dnf)


def test_detect_linux_alpine(monkeypatch):
    monkeypatch.setattr(pms.Path, "read_text", _mock_os_release("ID=alpine\n"))
    monkeypatch.setattr(pms.platform, "system", lambda: "Linux")
    result = pms.detect()
    assert isinstance(result, pms.Apk)


def test_detect_linux_opensuse(monkeypatch):
    monkeypatch.setattr(
        pms.Path,
        "read_text",
        _mock_os_release('ID=opensuse-leap\nID_LIKE="opensuse suse"\n'),
    )
    monkeypatch.setattr(pms.platform, "system", lambda: "Linux")
    result = pms.detect()
    assert isinstance(result, pms.Zypper)


def test_detect_override_valid(monkeypatch):
    monkeypatch.setattr(pms.platform, "system", lambda: "Linux")
    monkeypatch.setattr(pms.shutil, "which", lambda name: None)
    result = pms.detect(override="apt")
    assert isinstance(result, pms.Apt)


def test_detect_override_case_insensitive(monkeypatch):
    monkeypatch.setattr(pms.platform, "system", lambda: "Linux")
    monkeypatch.setattr(pms.shutil, "which", lambda name: None)
    result = pms.detect(override="DNF")
    assert isinstance(result, pms.Dnf)


def test_detect_override_invalid(monkeypatch):
    monkeypatch.setattr(pms.platform, "system", lambda: "Linux")
    with pytest.raises(SystemExit, match="unknown package manager"):
        pms.detect(override="nonexistent")


def test_detect_darwin_returns_brew(monkeypatch):
    monkeypatch.setattr(pms.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(pms, "_brew", lambda: "/opt/homebrew/bin/brew")
    result = pms.detect()
    assert isinstance(result, pms.Brew)


def test_detect_os_release_missing(monkeypatch):
    def raise_oserror(self, *a, **kw):
        raise OSError("no file")

    monkeypatch.setattr(pms.Path, "read_text", raise_oserror)
    monkeypatch.setattr(pms.platform, "system", lambda: "Linux")
    with pytest.raises(SystemExit, match="cannot auto-detect"):
        pms.detect()


def test_detect_unrecognized_linux(monkeypatch):
    monkeypatch.setattr(pms.Path, "read_text", _mock_os_release("ID=void\n"))
    monkeypatch.setattr(pms.platform, "system", lambda: "Linux")
    with pytest.raises(SystemExit, match="cannot auto-detect"):
        pms.detect()


# ---------------------------------------------------------------------------
# Pacman yay fallback
# ---------------------------------------------------------------------------


def test_pacman_uses_yay_when_available(monkeypatch):
    calls, installed = stateful_runner(monkeypatch)
    monkeypatch.setattr(pms.shutil, "which", lambda name: "/usr/bin/yay" if name == "yay" else None)
    pm = pms.Pacman()
    pm.check = lambda p: p in installed
    assert pm.install([PACKAGE]) == 0
    assert ["sudo", "yay", "-S", "--noconfirm", "--needed", PACKAGE] in calls


def test_pacman_falls_back_to_pacman(monkeypatch):
    calls, installed = stateful_runner(monkeypatch)
    monkeypatch.setattr(pms.shutil, "which", lambda name: None)
    pm = pms.Pacman()
    pm.check = lambda p: p in installed
    assert pm.install([PACKAGE]) == 0
    assert ["sudo", "pacman", "-S", "--noconfirm", "--needed", PACKAGE] in calls


# ---------------------------------------------------------------------------
# Brew edge cases
# ---------------------------------------------------------------------------


def test_brew_init_exits_when_not_found(monkeypatch):
    monkeypatch.setattr(pms.shutil, "which", lambda name: None)
    monkeypatch.setattr("os.path.exists", lambda path: False)
    with pytest.raises(SystemExit, match="cannot find brew"):
        pms.Brew()


def test_brew_check_uses_detected_path(monkeypatch):
    monkeypatch.setattr(pms, "_brew", lambda: "/custom/brew")
    calls = []
    monkeypatch.setattr(
        pms.subprocess,
        "run",
        lambda cmd, **kw: (calls.append(cmd), FakeResult(0))[1],
    )
    pm = pms.Brew()
    pm.check("git")
    assert calls[-1] == ["/custom/brew", "list", "--formula", "git"]
