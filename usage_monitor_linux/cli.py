"""
Client
=======

Command-line bridge between the Plasma applet and the daemon.

QML has no D-Bus binding of its own, so the applet reads the snapshot by
running this client through Plasma's ``executable`` data engine.  Output
is a single JSON document on stdout.  The GNOME extension does not need
this detour - GJS talks to the daemon directly through ``Gio.DBusProxy``.
"""
from __future__ import annotations

import json
import sys

import dbus

from .names import BUS_NAME, INTERFACE, OBJECT_PATH

__all__ = ['main']

_USAGE = (
    'usage: usage-monitor-for-claude-client\n'
    '           [--snapshot | --refresh | --quit]\n'
    '           [--run-event NAME] [--set-autostart 0|1]'
)
_COMMANDS = ('--snapshot', '--refresh', '--quit', '--run-event', '--set-autostart')


def main(argv: list[str] | None = None) -> int:
    """Run the requested client command.

    Parameters
    ----------
    argv : list[str] or None
        Argument list without the program name, or None to read
        ``sys.argv``.

    Returns
    -------
    int
        Process exit code.  A JSON document is printed on stdout in every
        case, so the applet always has something to parse.
    """
    args = sys.argv[1:] if argv is None else argv
    command = args[0] if args else '--snapshot'

    if command in ('-h', '--help'):
        print(_USAGE)
        return 0

    if command not in _COMMANDS:
        print(json.dumps({'error': f'unknown command: {command}'}))
        return 2

    argument = args[1] if len(args) > 1 else ''
    if command in ('--run-event', '--set-autostart') and not argument:
        print(json.dumps({'error': f'{command} needs an argument'}))
        return 2

    try:
        interface = _interface()
    except dbus.DBusException:
        # The applet stays installed while the daemon is stopped; report the
        # state as data rather than as a crash so the panel can say so.
        print(json.dumps({'error': 'daemon-unavailable'}))
        return 1

    if command == '--snapshot':
        print(interface.GetSnapshot())
    elif command == '--refresh':
        print(json.dumps({'refreshing': bool(interface.Refresh())}))
    elif command == '--run-event':
        print(json.dumps({'ran': bool(interface.RunEventTest(argument))}))
    elif command == '--set-autostart':
        print(json.dumps({'autostart': bool(interface.SetAutostart(argument not in ('0', 'false', 'off')))}))
    else:
        interface.Quit()
        print(json.dumps({'quit': True}))

    return 0


def _interface() -> dbus.Interface:
    """Return the daemon's D-Bus interface on the session bus."""
    bus = dbus.SessionBus()
    return dbus.Interface(bus.get_object(BUS_NAME, OBJECT_PATH), INTERFACE)


if __name__ == '__main__':
    sys.exit(main())
