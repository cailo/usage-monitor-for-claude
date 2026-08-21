"""
Snapshot Serialization
=======================

Turns the cache state into the JSON payload the desktop frontends render.

Everything that needs a formatting rule, a translation, or knowledge of
the API response shape is resolved here, in Python, once.  The Plasma
applet and the GNOME extension only draw what this module produces, so
neither of them has to reimplement label parsing, reset arithmetic, or
the 13 locale files.
"""
from __future__ import annotations

from typing import Any

from usage_monitor_for_claude import __version__
from usage_monitor_for_claude.anthropic_status import STATUS_PAGE_URL, AnthropicStatus
from usage_monitor_for_claude.cache import CacheSnapshot
from usage_monitor_for_claude.claude_cli import CHANGELOG_URL, PROJECT_URL, find_installations
from usage_monitor_for_claude.formatting import (
    divider_positions, elapsed_pct, expand_popup_fields, field_period, format_credits, format_tooltip, popup_label, time_until,
)
from usage_monitor_for_claude.i18n import T
from usage_monitor_for_claude.settings import (
    ICON_FIELDS, ICON_STYLE, ON_DOUBLE_CLICK_COMMAND, ON_RESET_COMMAND, ON_STARTUP_COMMAND, ON_THRESHOLD_COMMAND, POPUP_FIELDS,
)

from .autostart import is_autostart_enabled

__all__ = ['build_snapshot']

_ERROR_TEXT_LIMIT = 120


def build_snapshot(
    snap: CacheSnapshot, *, installations: list[dict[str, str]] | None = None, next_poll_time: float | None = None,
    anthropic_status: AnthropicStatus | None = None, failed: bool = False, auth_error: bool = False,
) -> dict[str, Any]:
    """Build the JSON-serializable payload published over D-Bus.

    Parameters
    ----------
    snap : CacheSnapshot
        Immutable snapshot of the cache state.
    installations : list or None
        Pre-computed installation list, or None to detect now.
    next_poll_time : float or None
        Unix timestamp of the next scheduled API poll.
    anthropic_status : AnthropicStatus or None
        Last known Anthropic server status, or None when the indicator is
        disabled or nothing was fetched yet.
    failed : bool
        True when the most recent poll returned an error, which makes the
        panel icon show a warning glyph instead of stale percentages.
    auth_error : bool
        True when that error was an authentication failure, which the icon
        distinguishes from a general failure.

    Returns
    -------
    dict
        Payload with ``icon``, ``tooltip``, ``profile``, ``usage``,
        ``extra``, ``installations``, ``anthropic_status`` and ``status``
        sections.
    """
    if installations is None:
        installations = [{'name': i.name, 'version': i.version} for i in find_installations()]

    return {
        'version': snap.version,
        'app_version': __version__,
        'labels': _labels(),
        'links': {'changelog': CHANGELOG_URL, 'project': PROJECT_URL, 'status_page': STATUS_PAGE_URL},
        'icon': _icon_section(snap.usage, failed, auth_error),
        'tooltip': format_tooltip(snap.usage) if snap.usage else '',
        'profile': _profile_section(snap.profile),
        'usage': _usage_section(snap.usage),
        'extra': _extra_section(snap.usage),
        'installations': installations,
        'autostart': is_autostart_enabled(),
        'events': {
            'double_click': bool(ON_DOUBLE_CLICK_COMMAND),
            'reset': bool(ON_RESET_COMMAND),
            'startup': bool(ON_STARTUP_COMMAND),
            'threshold': bool(ON_THRESHOLD_COMMAND),
        },
        'anthropic_status': _status_row(anthropic_status),
        'status': _status_section(snap, next_poll_time),
    }


def _labels() -> dict[str, str]:
    """Return the translated section headings and status templates.

    The frontends render text, they never translate it: shipping the strings
    inside the snapshot keeps the locale files the single source for every
    desktop, and keeps QML and GJS from drifting apart.
    """
    return {
        'title': T['popup_title'],
        'account': T['account'],
        'email': T['email'],
        'plan': T['plan'],
        'usage': T['usage'],
        'extra_usage': T['extra_usage'],
        'claude_code': T['claude_code'],
        # Uppercased from the notification title rather than stored as its own
        # key: it is the same wording, in the same 13 files, and deriving it
        # keeps the section heading from ever drifting away from the tooltip
        # and the notification that report the same state.
        'anthropic_status': T['notify_anthropic_status_title'].upper(),
        'changelog': T['changelog'],
        'status_updated': T['status_updated'],
        'status_updated_s': T['status_updated_s'],
        'status_next_update': T['status_next_update'],
        'status_refreshing': T['status_refreshing'],
        'duration_hm': T['duration_hm'],
        'duration_m': T['duration_m'],
        'duration_s': T['duration_s'],
        'menu_show': T['menu_show'],
        'menu_project': T['menu_project'],
        'autostart': T['autostart_session'],
        'restart': T['restart'],
        'quit': T['quit'],
        'test_commands': T['test_commands'],
        'test_reset_5h': T['test_reset_5h'],
        'test_reset_7d': T['test_reset_7d'],
        'test_threshold_5h': T['test_threshold_5h'],
        'test_threshold_7d': T['test_threshold_7d'],
        'test_startup': T['test_startup'],
        'test_double_click': T['test_double_click'],
        'no_token': T['no_token'],
    }


def _icon_section(usage: dict[str, Any], failed: bool = False, auth_error: bool = False) -> dict[str, Any]:
    """Build the inputs the panel icon is drawn from.

    Mirrors the two configured ``ICON_FIELDS`` bars, each with its
    utilization, display mode and elapsed-time marker, plus the flag that
    decides whether an exhausted quota reads as "costs money" or "blocked".

    A failed poll takes over the icon entirely: showing the last known
    percentages would present stale numbers as current, so the icon says
    so instead.
    """
    bars = []
    for entry_spec in ICON_FIELDS[:2]:
        field, mode = entry_spec.split(':', 1) if ':' in entry_spec else (entry_spec, 'utilization')
        # isinstance instead of truthiness: a configured field may point at
        # a non-dict response value (e.g. the raw limits array).
        entry = usage.get(field)
        if not isinstance(entry, dict):
            entry = {}
        period = field_period(field)
        bars.append({
            'key': field,
            'mode': mode,
            'pct': entry.get('utilization', 0) or 0,
            'time_pct': elapsed_pct(entry.get('resets_at', ''), period) if period else None,
        })

    extra = usage.get('extra_usage') or {}
    extra_limit = extra.get('monthly_limit') or 0
    extra_used = extra.get('used_credits') or 0
    # A missing/null monthly_limit means uncapped pay-as-you-go extra usage,
    # which cannot be exhausted.
    extra_available = bool(extra.get('is_enabled')) and (extra_limit <= 0 or extra_used < extra_limit)

    return {
        'style': ICON_STYLE,
        'bars': bars,
        'extra_usage_available': extra_available,
        'failed': failed,
        'auth_error': auth_error,
    }


def _profile_section(profile: dict[str, Any] | None) -> dict[str, str] | None:
    """Build the account row, or None when the profile is empty or incomplete."""
    # Truthiness check (not `is not None`): hides the account section when the
    # API returns an empty response instead of rendering empty fields.
    if not profile:
        return None

    account = profile.get('account') or {}
    org = profile.get('organization') or {}
    return {
        'email': account.get('email', ''),
        'plan': org.get('organization_type', '').replace('_', ' ').title(),
    }


def _usage_section(usage: dict[str, Any]) -> list[dict[str, Any]]:
    """Build one entry per configured quota bar, ready to draw."""
    if not usage:
        return []

    bars = []
    for field in expand_popup_fields(POPUP_FIELDS, usage):
        entry = usage.get(field)
        if not entry or entry.get('utilization') is None:
            continue

        pct = entry.get('utilization', 0) or 0
        resets_at = entry.get('resets_at', '')
        period = field_period(field)
        time_pct = elapsed_pct(resets_at, period) if period else None
        bars.append({
            'key': field,
            'label': popup_label(field),
            'pct_text': f'{pct:.0f}%',
            'fill_pct': max(0.0, min(1.0, pct / 100)),
            'warn': pct >= 100 or (time_pct is not None and pct > time_pct),
            'reset_text': time_until(resets_at) if resets_at else '',
            'dividers': divider_positions(resets_at, period) if period else [],
            'marker_rel': max(0.0, min(1.0, time_pct / 100)) if time_pct is not None else None,
        })

    return bars


def _extra_section(usage: dict[str, Any]) -> dict[str, Any] | None:
    """Build the extra-usage row, or None when it is disabled or unused."""
    extra_data = (usage or {}).get('extra_usage')
    if not extra_data or not extra_data.get('is_enabled'):
        return None

    used = extra_data.get('used_credits')
    if used is None:
        return None

    limit = extra_data.get('monthly_limit', 0) or 0
    currency = extra_data.get('currency')
    decimal_places = extra_data.get('decimal_places')

    # No monthly cap (e.g. uncapped pay-as-you-go credits) - show what has
    # been spent without a percentage bar to imply a limit.
    if limit <= 0:
        return {
            'has_limit': False,
            'pct_text': '',
            'fill_pct': 0.0,
            'spent_text': T['extra_usage_spent_no_limit'].format(used=format_credits(used, currency, decimal_places)),
        }

    pct = used / limit * 100
    return {
        'has_limit': True,
        'pct_text': f'{pct:.0f}%',
        'fill_pct': max(0.0, min(1.0, pct / 100)),
        'spent_text': T['extra_usage_spent'].format(
            used=format_credits(used, currency, decimal_places),
            limit=format_credits(limit, currency, decimal_places),
        ),
    }


def _status_row(anthropic_status: AnthropicStatus | None) -> dict[str, Any] | None:
    """Build the Anthropic server status row, or None when it is not shown."""
    if anthropic_status is None:
        return None

    # The status feed speaks English, so its description is shown verbatim;
    # only the unreachable-feed fallback text comes from the translations.
    if anthropic_status.indicator == 'unknown':
        text = T['anthropic_status_unavailable']
    else:
        text = anthropic_status.description or T['anthropic_status_unavailable']

    return {
        'indicator': anthropic_status.indicator,
        'text': text,
        'incident': anthropic_status.incident_name,
    }


def _status_section(snap: CacheSnapshot, next_poll_time: float | None) -> dict[str, Any]:
    """Build the footer status, with raw timestamps for the frontend's live timer."""
    if not snap.usage:
        if snap.last_error:
            return {'text': snap.last_error[:_ERROR_TEXT_LIMIT], 'is_error': True}
        return {'text': T['status_refreshing'], 'is_error': False, 'refreshing': True}

    return {
        'last_success_time': snap.last_success_time,
        'next_poll_time': next_poll_time,
        'refreshing': snap.refreshing,
        'error': snap.last_error[:_ERROR_TEXT_LIMIT] if snap.last_error else None,
    }
