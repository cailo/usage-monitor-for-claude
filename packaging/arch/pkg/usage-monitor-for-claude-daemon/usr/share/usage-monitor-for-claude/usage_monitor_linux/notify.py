"""
Notifications
==============

Sends desktop notifications over ``org.freedesktop.Notifications``.

The ``desktop-entry`` hint is what gives the toast the application's own
logo instead of a generic placeholder or the live panel icon.  That
matters for the same reason it does on Windows: the panel icon reflects
the most-exhausted quota, so a "quota reset" toast carrying it would show
an exhausted glyph and contradict its own text.
"""
from __future__ import annotations

import dbus

__all__ = ['DESKTOP_ENTRY', 'send_notification']

APP_NAME = 'Usage Monitor for Claude'
DESKTOP_ENTRY = 'usage-monitor-for-claude'

_SERVICE = 'org.freedesktop.Notifications'
_PATH = '/org/freedesktop/Notifications'
_DEFAULT_TIMEOUT_MS = 10000

_session_bus: dbus.Bus | None = None


def send_notification(message: str, title: str, timeout_ms: int = _DEFAULT_TIMEOUT_MS) -> bool:
    """Show a desktop notification.

    Parameters
    ----------
    message : str
        Notification body text.
    title : str
        Notification title.
    timeout_ms : int
        Requested display duration in milliseconds.  Desktops are free to
        ignore it in favor of their own policy.

    Returns
    -------
    bool
        True when the notification server accepted the message.  A missing
        or failing server is not an error worth interrupting a poll for.
    """
    global _session_bus

    try:
        if _session_bus is None:
            _session_bus = dbus.SessionBus()

        interface = dbus.Interface(_session_bus.get_object(_SERVICE, _PATH), _SERVICE)
        interface.Notify(
            APP_NAME, dbus.UInt32(0), DESKTOP_ENTRY, title, message,
            dbus.Array([], signature='s'), {'desktop-entry': DESKTOP_ENTRY}, timeout_ms,
        )
        return True
    except dbus.DBusException:
        return False
