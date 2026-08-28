from pkg import pms


class FakeResult:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode


def test_pacman_install_and_remove_shapes(monkeypatch):
    calls: list[list[str]] = []
    installed: set[str] = set()

    def fake_run(cmd, **kw):
        calls.append(cmd)
        pkg = cmd[-1]
        if "-S" in cmd:
            installed.add(pkg)
        if "-Rns" in cmd:
            installed.discard(pkg)
        return FakeResult()

    monkeypatch.setattr(pms.subprocess, "run", fake_run)
    pm = pms.Pacman()
    pm.check = lambda p: p in installed
    assert pm.install(["zsh"]) == 0
    assert pm.remove(["zsh"]) == 0
    assert ["sudo", "pacman", "-S", "--noconfirm", "--needed", "zsh"] in calls
    assert ["sudo", "pacman", "-Rns", "--noconfirm", "zsh"] in calls


def test_apt_runs_lazy_update_then_install(monkeypatch):
    calls: list[list[str]] = []
    installed: set[str] = set()

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if "install" in cmd:
            installed.update(cmd[cmd.index("--no-install-recommends") + 1 :])
        return FakeResult()

    monkeypatch.setattr(pms.subprocess, "run", fake_run)
    pm = pms.Apt()
    pm.check = lambda p: p in installed
    assert pm.install(["fd"]) == 0
    assert ["sudo", "apt-get", "update"] in calls
    assert ["sudo", "apt-get", "install", "-y", "--no-install-recommends", "fd"] in calls
    assert len(calls) == 2


def test_verify_after_failed_install_returns_1(monkeypatch):
    monkeypatch.setattr(pms.subprocess, "run", lambda cmd, **kw: FakeResult(1))
    pm = pms.Pacman()
    pm.check = lambda p: False
    assert pm.install(["ghost"]) == 1
