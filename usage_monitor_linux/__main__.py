"""Entry point for ``python -m usage_monitor_linux``."""
from __future__ import annotations

import os
import signal
import sys
import threading
from pathlib import Path
from typing import Any

from usage_monitor_for_claude.instance_id import parse_config_dir

# --config-dir selects which Claude account to monitor.  It must be resolved
# into CLAUDE_CONFIG_DIR before any other package import: api, settings and
# i18n all read the variable at import or first-use time.  Keep every other
# package import below this block.
_config_dir = parse_config_dir(sys.argv)
if _config_dir is not None:
    _config_path = Path(_config_dir)
    if not _config_path.is_dir():
        print(f'--config-dir directory does not exist: {_config_dir}', file=sys.stderr)
        sys.exit(1)
    os.environ['CLAUDE_CONFIG_DIR'] = str(_config_path.resolve())

import dbus
import dbus.mainloop.glib
from gi.repository import GLib, GLibUnix  # type: ignore[import-untyped]  # provided by python-gobject

from usage_monitor_linux.daemon import UsageMonitorDaemon
from usage_monitor_linux.names import BUS_NAME
from usage_monitor_linux.service import UsageMonitorService
from usage_monitor_linux.single_instance import acquire_bus_name


def main() -> int:
    """Run the daemon until it is asked to quit."""
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()

    bus_name = acquire_bus_name(bus)
    if bus_name is None:
        print(f'Another instance already owns {BUS_NAME}', file=sys.stderr)
        return 0

    loop = GLib.MainLoop()
    service_holder: dict[str, UsageMonitorService] = {}

    def publish(snapshot: dict[str, Any]) -> None:
        # The poll loop runs on its own thread; D-Bus signals must be emitted
        # from the thread running the main loop.
        service = service_holder.get('service')
        if service is not None:
            GLib.idle_add(service.publish, snapshot)

    daemon = UsageMonitorDaemon(publish)

    def quit_daemon() -> None:
        daemon.stop()
        loop.quit()

    service_holder['service'] = UsageMonitorService(
        bus_name, daemon.snapshot, daemon.request_refresh, quit_daemon, daemon.run_event_test, daemon.set_autostart,
    )

    poll_thread = threading.Thread(target=daemon.run, name='poll', daemon=True)
    poll_thread.start()

    for sig in (signal.SIGINT, signal.SIGTERM):
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (quit_daemon(), GLib.SOURCE_REMOVE)[1])

    loop.run()
    daemon.stop()
    poll_thread.join(timeout=3)

    return 0


if __name__ == '__main__':
    sys.exit(main())
