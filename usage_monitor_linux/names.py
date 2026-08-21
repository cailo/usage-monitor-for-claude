"""
D-Bus Names
============

Well-known bus name, object path and interface of the daemon.

The names carry the per-instance suffix derived from ``--config-dir``, so
one daemon per Claude account can run side by side, each served by its own
panel widget.
"""
from __future__ import annotations

from usage_monitor_for_claude.instance_id import config_dir_suffix

__all__ = ['BUS_NAME', 'INTERFACE', 'OBJECT_PATH']

_BASE_NAME = 'com.github.cailo.UsageMonitor'

BUS_NAME = _BASE_NAME + config_dir_suffix()
OBJECT_PATH = '/' + BUS_NAME.replace('.', '/')
INTERFACE = _BASE_NAME
