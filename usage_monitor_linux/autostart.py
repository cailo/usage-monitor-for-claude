"""
Autostart
==========

Enables and disables starting the daemon with the desktop session.

This is the Linux counterpart of the Windows ``HKCU\\...\\Run`` entry: a
file under ``~/.config/autostart/`` written only when the user turns
autostart on from the panel menu, and removed when they turn it off.
XDG autostart is used rather than a systemd user unit because the daemon
has to end up on the same session bus as the panel, which a
``systemd --user`` service does not on a session that is not
systemd-managed.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

__all__ = ['autostart_path', 'is_autostart_enabled', 'set_autostart']

_ENTRY_NAME = 'usage-monitor-for-claude.desktop'
_TEMPLATE = Path('/usr/share/usage-monitor-for-claude/autostart') / _ENTRY_NAME


def autostart_path() -> Path:
    """Return the path of the user's autostart entry."""
    config_home = os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config'
    return Path(config_home) / 'autostart' / _ENTRY_NAME


def is_autostart_enabled() -> bool:
    """Return True when the autostart entry is in place."""
    return autostart_path().is_file()


def set_autostart(enabled: bool) -> bool:
    """Create or remove the autostart entry.

    Parameters
    ----------
    enabled : bool
        True to start the daemon with the session, False to stop doing so.

    Returns
    -------
    bool
        The resulting state.  A failure to write returns the state that is
        actually on disk rather than the one that was requested, so the
        menu never shows a checkmark for something that did not happen.
    """
    target = autostart_path()

    try:
        if not enabled:
            target.unlink(missing_ok=True)
            return False

        if not _TEMPLATE.is_file():
            return target.is_file()

        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_TEMPLATE, target)
    except OSError:
        return target.is_file()

    return target.is_file()
