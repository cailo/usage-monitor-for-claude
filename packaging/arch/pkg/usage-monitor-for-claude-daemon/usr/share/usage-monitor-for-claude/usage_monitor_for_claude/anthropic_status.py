"""
Anthropic Status
=================

Reads the public Anthropic status feed (status.anthropic.com, an
Atlassian Statuspage) for the status indicator in the popup and tooltip.

Deliberately separate from ``api.py``: that module is the only one
handling credentials and talks exclusively to ``api.anthropic.com``.
The status feed is public, read-only, and credential-free, so it lives
in its own module - and the whole feature can be turned off with the
``status_enabled`` setting, in which case this module never makes a
request.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

__all__ = ['STATUS_API_URL', 'STATUS_INCIDENTS_URL', 'STATUS_PAGE_URL', 'STATUS_UNKNOWN', 'AnthropicStatus', 'AnthropicStatusCache', 'fetch_status']

# Status feed endpoints & status page
STATUS_PAGE_URL = 'https://status.anthropic.com'
STATUS_API_URL = 'https://status.anthropic.com/api/v2/status.json'
STATUS_INCIDENTS_URL = 'https://status.anthropic.com/api/v2/incidents/unresolved.json'

# Short timeout: the indicator is a convenience and must never stall the poll loop.
_REQUEST_TIMEOUT = 5

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnthropicStatus:
    """Current Anthropic server status.

    Attributes
    ----------
    indicator : str
        Statuspage severity indicator: ``'none'`` (operational),
        ``'minor'``, ``'major'``, ``'critical'``, or ``'unknown'`` when
        the feed could not be read.
    description : str
        Human-readable status text from the feed (e.g. ``'All Systems
        Operational'``); empty when the feed could not be read.
    incident_name : str or None
        Name of the most recent unresolved incident, or None when there
        is none or it could not be read.
    """

    indicator: str
    description: str
    incident_name: str | None = None


STATUS_UNKNOWN = AnthropicStatus(indicator='unknown', description='')


def fetch_status() -> AnthropicStatus:
    """Fetch the current Anthropic server status from the public feed.

    Any network or parsing problem yields ``STATUS_UNKNOWN`` instead of
    raising.  The unresolved-incident name is only requested while the
    indicator reports a problem - during normal operation a single
    request per poll suffices.
    """
    try:
        response = requests.get(STATUS_API_URL, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        status = response.json().get('status') or {}
        indicator = status.get('indicator')
        description = status.get('description')
    except Exception:
        log.info('fetch_status -> failed')
        return STATUS_UNKNOWN

    if not isinstance(indicator, str) or not indicator:
        log.info('fetch_status -> unusable response')
        return STATUS_UNKNOWN

    incident_name = _fetch_incident_name() if indicator != 'none' else None
    log.info('fetch_status -> %s', indicator)
    return AnthropicStatus(
        indicator=indicator,
        description=description if isinstance(description, str) else '',
        incident_name=incident_name,
    )


class AnthropicStatusCache:
    """Serves the last fetched status, refetching at most every ``poll_interval`` seconds.

    The status changes rarely, so it is polled far less often than the
    usage data.  Not thread-safe by design: ``current()`` is only called
    from the poll loop; other threads read the app's last stored status.
    """

    def __init__(self, poll_interval: int) -> None:
        assert poll_interval > 0
        self._poll_interval = poll_interval
        self._status = STATUS_UNKNOWN
        self._last_fetch_time: float | None = None

    def current(self) -> AnthropicStatus:
        """Return the cached status, refetching once the poll interval elapsed."""
        now = time.time()

        # Re-anchor after a backward clock jump (manual correction, NTP step,
        # VM restore) - otherwise the next refetch would wait until the wall
        # clock catches up with the pre-jump timestamp.
        if self._last_fetch_time is not None and now < self._last_fetch_time:
            self._last_fetch_time = now - self._poll_interval

        if self._last_fetch_time is None or now - self._last_fetch_time >= self._poll_interval:
            self._status = fetch_status()
            self._last_fetch_time = now

        return self._status


def _fetch_incident_name() -> str | None:
    """Return the name of the most recent unresolved incident, or None."""
    try:
        response = requests.get(STATUS_INCIDENTS_URL, timeout=_REQUEST_TIMEOUT)
        response.raise_for_status()
        incidents = response.json().get('incidents')
        if not isinstance(incidents, list) or not incidents:
            return None

        name = incidents[0].get('name')
        return name if isinstance(name, str) and name else None
    except Exception:
        return None
