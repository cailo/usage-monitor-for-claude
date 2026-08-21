"""
Single Instance
================

Ensures only one daemon runs per Claude config directory.

The well-known bus name is the lock: D-Bus grants it to exactly one
process, so a second start is rejected by the bus itself.  Nothing is
written to disk, and the name is released automatically when the process
exits - including on a crash, which a lock file could not guarantee.
"""
from __future__ import annotations

import dbus
import dbus.service

from .names import BUS_NAME

__all__ = ['acquire_bus_name']


def acquire_bus_name(bus: dbus.Bus) -> dbus.service.BusName | None:
    """Claim the daemon's well-known bus name.

    Parameters
    ----------
    bus : dbus.Bus
        Session bus connection to claim the name on.

    Returns
    -------
    dbus.service.BusName or None
        The claimed name, which the caller must keep referenced for the
        lifetime of the process, or None when another instance already
        holds it.
    """
    try:
        return dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)
    except dbus.exceptions.NameExistsException:
        return None
