"""
Idle Detection
===============

Detects session lock and user inactivity over D-Bus.

Lock state comes from ``org.freedesktop.ScreenSaver``, which both KWin
and GNOME Shell implement.  Idle seconds are another matter: GNOME
exposes ``org.gnome.Mutter.IdleMonitor``, but Plasma on Wayland has no
public equivalent - the idle information lives in the compositor behind
``ext-idle-notify-v1``, which is not reachable from D-Bus.  There, idle
detection degrades to lock detection only, and ``IDLE_PAUSE`` pauses
polling when the session locks rather than when the user stops typing.
"""
from __future__ import annotations

import dbus

__all__ = ['get_idle_seconds', 'is_workstation_locked']

_SCREENSAVER_SERVICE = 'org.freedesktop.ScreenSaver'
_SCREENSAVER_PATH = '/org/freedesktop/ScreenSaver'
_MUTTER_IDLE_SERVICE = 'org.gnome.Mutter.IdleMonitor'
_MUTTER_IDLE_PATH = '/org/gnome/Mutter/IdleMonitor/Core'

_session_bus: dbus.Bus | None = None


def is_workstation_locked() -> bool:
    """Return True when the session is locked.

    Returns
    -------
    bool
        True if the screen locker reports an active lock.  Returns False
        when the query fails, so a missing screen locker never pauses
        polling indefinitely.
    """
    try:
        interface = _interface(_SCREENSAVER_SERVICE, _SCREENSAVER_PATH, _SCREENSAVER_SERVICE)
        return bool(interface.GetActive())
    except dbus.DBusException:
        return False


def get_idle_seconds() -> float:
    """Return seconds since the last keyboard or mouse input.

    Returns
    -------
    float
        Idle duration in seconds where the desktop exposes one (GNOME),
        otherwise 0.0 - which reads as "the user is present" and leaves
        lock detection as the only pause trigger.
    """
    try:
        interface = _interface(_MUTTER_IDLE_SERVICE, _MUTTER_IDLE_PATH, _MUTTER_IDLE_SERVICE)
        return float(interface.GetIdletime()) / 1000.0
    except dbus.DBusException:
        return 0.0


def _interface(service: str, path: str, interface: str) -> dbus.Interface:
    """Return a proxy interface on the session bus, connecting on first use."""
    global _session_bus

    if _session_bus is None:
        _session_bus = dbus.SessionBus()

    return dbus.Interface(_session_bus.get_object(service, path), interface)
