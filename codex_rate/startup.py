"""Opt-in, current-user Windows sign-in startup for the installed executable."""

import sys
from pathlib import Path


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "CodexRate"


def _executable_path():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return Path(__file__).resolve().parent.parent / "dist" / "CodexRate.exe"


def command():
    """Return the quoted permanent executable command, even before a build exists."""
    return f'"{_executable_path()}" --background'


def is_enabled():
    """Whether this copy's command is registered; permission errors reach the caller."""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_QUERY_VALUE) as key:
            value, kind = winreg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    return kind == winreg.REG_SZ and value == command()


def enable():
    """Register an existing executable and return its command; repeated calls are safe."""
    executable = _executable_path()
    if not executable.is_file():
        raise FileNotFoundError(f"Codex Rate executable not found: {executable}")

    import winreg

    value = command()
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                           winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
        try:
            previous = winreg.QueryValueEx(key, VALUE_NAME)
        except FileNotFoundError:
            previous = None
        if previous != (value, winreg.REG_SZ):
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, value)
    return value


def disable():
    """Delete only this application's value; return False when it was already absent."""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    return True
