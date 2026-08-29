import builtins
import sys

from pkg import cli


def test_consent_force_yes(monkeypatch):
    calls = []
    monkeypatch.setattr(builtins, "input", lambda *a: calls.append(a) or "n")
    assert cli._consent(True, "run?") is True
    assert calls == []

def test_consent_tty_yes(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(builtins, "input", lambda *a: "yes")
    assert cli._consent(False, "run?") is True


def test_consent_tty_no(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(builtins, "input", lambda *a: "n")
    assert cli._consent(False, "run?") is False


def test_consent_not_tty(monkeypatch):
    calls = []
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(builtins, "input", lambda *a: calls.append(a) or "y")
    assert cli._consent(False, "run?") is False
    assert calls == []
