"""
D-Bus Service
==============

Publishes the usage snapshot on the session bus.

The daemon owns every decision - polling cadence, formatting, i18n,
alerts - and hands the panel frontends a finished payload.  The Plasma
applet and the GNOME extension are drawing surfaces, not clients of the
Anthropic API: no credential ever reaches the desktop shell process.
"""
from __future__ import annotations

import json
from typing import Any, Callable

import dbus.service

from .names import INTERFACE, OBJECT_PATH

__all__ = ['UsageMonitorService']


class UsageMonitorService(dbus.service.Object):
    """Session-bus object serving the current snapshot to panel frontends.

    Parameters
    ----------
    bus_name : dbus.service.BusName
        Claimed well-known name the object is exported under.
    snapshot_provider : callable
        Returns the current snapshot payload as a dict.
    refresh_handler : callable
        Requests an out-of-band poll.  Returns True when a refresh was
        started, False when one was declined (cooldown or backoff).
    quit_handler : callable
        Shuts the daemon down.
    event_handler : callable
        Runs one configured event command by name, for the panel menu's
        test entries.  Returns True when a command was launched.
    autostart_handler : callable
        Turns starting with the session on or off, returning the state
        that actually ended up on disk.
    """

    def __init__(
        self, bus_name: dbus.service.BusName, snapshot_provider: Callable[[], dict[str, Any]],
        refresh_handler: Callable[[], bool], quit_handler: Callable[[], None],
        event_handler: Callable[[str], bool], autostart_handler: Callable[[bool], bool],
    ) -> None:
        super().__init__(bus_name, OBJECT_PATH)
        self._snapshot_provider = snapshot_provider
        self._refresh_handler = refresh_handler
        self._quit_handler = quit_handler
        self._event_handler = event_handler
        self._autostart_handler = autostart_handler

    @dbus.service.method(INTERFACE, out_signature='s')
    def GetSnapshot(self) -> str:
        """Return the current snapshot as a JSON document."""
        return json.dumps(self._snapshot_provider())

    @dbus.service.method(INTERFACE, out_signature='b')
    def Refresh(self) -> bool:
        """Request an immediate poll, returning False when it was declined."""
        return self._refresh_handler()

    @dbus.service.method(INTERFACE, in_signature='s', out_signature='b')
    def RunEventTest(self, event: str) -> bool:
        """Run one configured event command, returning False when none is set."""
        return self._event_handler(str(event))

    @dbus.service.method(INTERFACE, in_signature='b', out_signature='b')
    def SetAutostart(self, enabled: bool) -> bool:
        """Turn starting with the session on or off, returning the resulting state."""
        return self._autostart_handler(bool(enabled))

    @dbus.service.method(INTERFACE)
    def Quit(self) -> None:
        """Shut the daemon down."""
        self._quit_handler()

    @dbus.service.signal(INTERFACE, signature='s')
    def SnapshotChanged(self, payload: str) -> None:
        """Emitted with the new JSON snapshot whenever the data changes."""

    def publish(self, snapshot: dict[str, Any]) -> None:
        """Emit ``SnapshotChanged`` with *snapshot* serialized as JSON."""
        self.SnapshotChanged(json.dumps(snapshot))
