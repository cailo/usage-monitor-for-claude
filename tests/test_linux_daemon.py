"""
Linux Daemon Tests
===================

Unit tests for the D-Bus daemon: snapshot serialization, poll scheduling,
and the refresh gate.
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# The daemon binds to python-dbus and GLib, which exist only on the Linux side.
if os.name == 'nt':
    raise unittest.SkipTest('Linux-only application layer')

from tempfile import TemporaryDirectory

from usage_monitor_for_claude.cache import CacheSnapshot
from usage_monitor_for_claude.settings import POLL_FAST
from usage_monitor_linux import daemon as daemon_mod
from usage_monitor_linux.daemon import RESET_BUFFER, UsageMonitorDaemon, align_to_reset
from usage_monitor_linux import autostart as autostart_mod
from usage_monitor_linux.snapshot import build_snapshot


def _snapshot(usage: dict | None = None, profile: dict | None = None, **kwargs) -> CacheSnapshot:
    """Build a CacheSnapshot with sensible defaults for the fields under test."""
    defaults = {'last_success_time': 1000.0, 'refreshing': False, 'last_error': None, 'version': 1}
    defaults.update(kwargs)
    return CacheSnapshot(usage=usage or {}, profile=profile, **defaults)


def _build(usage: dict | None = None, profile: dict | None = None, **kwargs) -> dict:
    """Serialize a snapshot without touching the filesystem for installations."""
    return build_snapshot(_snapshot(usage, profile, **kwargs), installations=[])


# ---------------------------------------------------------------------------
# align_to_reset
# ---------------------------------------------------------------------------

class TestAlignToReset(unittest.TestCase):
    """Tests for the reset-aligned poll scheduler."""

    def test_no_reset_keeps_interval(self):
        """No upcoming reset keeps the normal interval, no alignment."""
        self.assertEqual(align_to_reset(180, None), (180, False))

    def test_non_positive_reset_keeps_interval(self):
        """A non-positive next_reset keeps the normal interval."""
        self.assertEqual(align_to_reset(180, 0.0), (180, False))

    def test_distant_reset_keeps_interval(self):
        """A reset far beyond the interval leaves the cadence untouched."""
        self.assertEqual(align_to_reset(180, 10000.0), (180, False))

    def test_inside_danger_window_returns_poll_fast(self):
        """Inside the last POLL_FAST - RESET_BUFFER seconds, only POLL_FAST is possible."""
        self.assertEqual(align_to_reset(180, POLL_FAST - RESET_BUFFER - 1), (POLL_FAST, True))

    def test_near_reset_commits_to_confirming_poll(self):
        """A reset within reach places the poll just after it."""
        interval, aligned = align_to_reset(180, 200.0)
        self.assertTrue(aligned)
        self.assertEqual(interval, 205)

    def test_never_returns_below_poll_fast(self):
        """Invariant: no alignment may schedule a poll faster than the cache cooldown."""
        for next_reset in range(1, 4000, 7):
            for interval in (POLL_FAST, 180, 300, 900):
                result, _ = align_to_reset(interval, float(next_reset))
                self.assertGreaterEqual(result, POLL_FAST, f'interval={interval} next_reset={next_reset}')


# ---------------------------------------------------------------------------
# build_snapshot
# ---------------------------------------------------------------------------

class TestSnapshotIconSection(unittest.TestCase):
    """Tests for the panel-icon inputs."""

    def test_missing_fields_render_as_zero(self):
        """An empty response still yields two bars so the icon can always draw."""
        icon = _build()['icon']
        self.assertEqual(len(icon['bars']), 2)
        self.assertEqual([bar['pct'] for bar in icon['bars']], [0, 0])

    def test_non_dict_entry_is_ignored(self):
        """A configured field pointing at a non-dict value does not crash the icon."""
        icon = _build({'five_hour': ['not', 'a', 'dict']})['icon']
        self.assertEqual(icon['bars'][0]['pct'], 0)

    def test_utilization_is_passed_through(self):
        """Utilization reaches the frontend unrounded so it can draw its own bar."""
        icon = _build({'five_hour': {'utilization': 42.5, 'resets_at': None}})['icon']
        self.assertEqual(icon['bars'][0]['pct'], 42.5)

    def test_extra_usage_available_when_under_limit(self):
        """Paid credits still available mark the icon as 'costs money', not 'blocked'."""
        icon = _build({'extra_usage': {'is_enabled': True, 'monthly_limit': 100, 'used_credits': 40}})['icon']
        self.assertTrue(icon['extra_usage_available'])

    def test_extra_usage_exhausted(self):
        """Spent-out credits mark the icon as blocked."""
        icon = _build({'extra_usage': {'is_enabled': True, 'monthly_limit': 100, 'used_credits': 100}})['icon']
        self.assertFalse(icon['extra_usage_available'])

    def test_uncapped_extra_usage_is_always_available(self):
        """A missing monthly limit means uncapped credits, which cannot be exhausted."""
        icon = _build({'extra_usage': {'is_enabled': True, 'monthly_limit': None, 'used_credits': 9999}})['icon']
        self.assertTrue(icon['extra_usage_available'])


class TestSnapshotProfileSection(unittest.TestCase):
    """Tests for the account row."""

    def test_absent_profile_is_none(self):
        """No profile hides the account section instead of rendering empty fields."""
        self.assertIsNone(_build()['profile'])

    def test_empty_profile_is_none(self):
        """An empty profile response also hides the account section."""
        self.assertIsNone(_build(profile={})['profile'])

    def test_plan_is_humanized(self):
        """The organization type is turned into a readable plan name."""
        profile = _build(profile={'account': {'email': 'a@b.c'}, 'organization': {'organization_type': 'claude_pro'}})['profile']
        self.assertEqual(profile, {'email': 'a@b.c', 'plan': 'Claude Pro'})

    def test_null_organization_does_not_crash(self):
        """A null organization is treated as absent, not as an attribute error."""
        profile = _build(profile={'account': {'email': 'a@b.c'}, 'organization': None})['profile']
        self.assertEqual(profile['plan'], '')


class TestSnapshotUsageSection(unittest.TestCase):
    """Tests for the quota bars."""

    def test_field_without_utilization_is_skipped(self):
        """A quota the account does not have produces no bar."""
        self.assertEqual(_build({'five_hour': {'utilization': None, 'resets_at': None}})['usage'], [])

    def test_fill_is_clamped_to_one(self):
        """Utilization above 100 still yields a drawable fill fraction."""
        bar = _build({'five_hour': {'utilization': 140, 'resets_at': None}})['usage'][0]
        self.assertEqual(bar['fill_pct'], 1.0)
        self.assertTrue(bar['warn'])

    def test_percentage_text_is_rounded(self):
        """The percentage label is pre-rendered so frontends do not round differently."""
        bar = _build({'five_hour': {'utilization': 42.6, 'resets_at': None}})['usage'][0]
        self.assertEqual(bar['pct_text'], '43%')


class TestSnapshotExtraSection(unittest.TestCase):
    """Tests for the extra-usage row."""

    def test_absent_when_disabled(self):
        """Extra usage that is not enabled produces no row."""
        self.assertIsNone(_build({'extra_usage': {'is_enabled': False}})['extra'])

    def test_absent_when_no_credits_reported(self):
        """A missing used_credits value produces no row rather than a zero row."""
        self.assertIsNone(_build({'extra_usage': {'is_enabled': True, 'used_credits': None}})['extra'])

    def test_uncapped_has_no_percentage(self):
        """Uncapped credits show what was spent without implying a limit."""
        extra = _build({'extra_usage': {'is_enabled': True, 'used_credits': 500, 'monthly_limit': 0}})['extra']
        self.assertFalse(extra['has_limit'])
        self.assertEqual(extra['pct_text'], '')

    def test_capped_reports_percentage(self):
        """A monthly limit yields a percentage and a fill fraction."""
        extra = _build({'extra_usage': {'is_enabled': True, 'used_credits': 500, 'monthly_limit': 1000}})['extra']
        self.assertTrue(extra['has_limit'])
        self.assertEqual(extra['pct_text'], '50%')
        self.assertEqual(extra['fill_pct'], 0.5)


class TestSnapshotStatusSection(unittest.TestCase):
    """Tests for the footer status."""

    def test_error_before_first_success(self):
        """With no data yet, the error is surfaced as the status text."""
        status = _build(last_error='boom')['status']
        self.assertTrue(status['is_error'])
        self.assertEqual(status['text'], 'boom')

    def test_error_text_is_truncated(self):
        """An oversized error message is trimmed before it reaches the frontend."""
        self.assertEqual(len(_build(last_error='x' * 500)['status']['text']), 120)

    def test_refreshing_before_first_success(self):
        """Without data or error, the status reports the initial refresh."""
        self.assertTrue(_build()['status']['refreshing'])

    def test_timestamps_passed_through_after_success(self):
        """With data present, raw timestamps drive the frontend's live timer."""
        status = _build({'five_hour': {'utilization': 10, 'resets_at': None}})['status']
        self.assertEqual(status['last_success_time'], 1000.0)
        self.assertIsNone(status['error'])


class TestSnapshotAnthropicStatus(unittest.TestCase):
    """Tests for the Anthropic server status row."""

    def test_absent_when_not_fetched(self):
        """No status reading hides the row entirely."""
        self.assertIsNone(_build()['anthropic_status'])

    def test_unknown_uses_translated_fallback(self):
        """An unreachable feed shows translated text rather than an empty row."""
        status = MagicMock(indicator='unknown', description='', incident_name=None)
        row = build_snapshot(_snapshot(), installations=[], anthropic_status=status)['anthropic_status']
        self.assertEqual(row['indicator'], 'unknown')
        self.assertTrue(row['text'])


# ---------------------------------------------------------------------------
# UsageMonitorDaemon
# ---------------------------------------------------------------------------

class TestSnapshotFailureState(unittest.TestCase):
    """Tests for the icon's failed-poll state."""

    def test_healthy_by_default(self):
        """A successful poll leaves the icon showing percentages."""
        icon = _build({'five_hour': {'utilization': 40, 'resets_at': None}})['icon']
        self.assertFalse(icon['failed'])
        self.assertFalse(icon['auth_error'])

    def test_failed_poll_is_reported(self):
        """A failed poll is flagged so the icon stops showing stale numbers."""
        icon = build_snapshot(_snapshot({'five_hour': {'utilization': 40}}), installations=[], failed=True)['icon']
        self.assertTrue(icon['failed'])
        self.assertFalse(icon['auth_error'])

    def test_auth_error_is_distinguished(self):
        """An authentication failure is flagged separately from a general one."""
        icon = build_snapshot(_snapshot(), installations=[], failed=True, auth_error=True)['icon']
        self.assertTrue(icon['auth_error'])


class TestSnapshotMenuData(unittest.TestCase):
    """Tests for the data the panel menu is built from."""

    def test_labels_are_translated(self):
        """Menu labels ship with the snapshot so the frontends never translate."""
        labels = _build()['labels']
        for key in ('menu_show', 'menu_project', 'autostart', 'restart', 'quit', 'test_commands'):
            self.assertTrue(labels[key], key)

    def test_status_heading_matches_the_notification_wording(self):
        """The status section heading is the notification title, uppercased."""
        from usage_monitor_for_claude.i18n import T

        self.assertEqual(_build()['labels']['anthropic_status'], T['notify_anthropic_status_title'].upper())

    def test_autostart_label_is_not_windows_specific(self):
        """The Linux menu must not offer to start with Windows."""
        self.assertNotIn('windows', _build()['labels']['autostart'].lower())

    def test_events_report_what_is_configured(self):
        """Unconfigured event commands are reported so their menu entries can hide."""
        events = _build()['events']
        self.assertEqual(set(events), {'double_click', 'reset', 'startup', 'threshold'})
        for configured in events.values():
            self.assertIsInstance(configured, bool)


class TestAutostart(unittest.TestCase):
    """Tests for the XDG autostart entry."""

    def test_disabled_when_absent(self):
        """No entry on disk reads as disabled."""
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {'XDG_CONFIG_HOME': tmp}):
            self.assertFalse(autostart_mod.is_autostart_enabled())

    def test_enable_copies_the_template(self):
        """Enabling installs the packaged template into the user's autostart dir."""
        with TemporaryDirectory() as tmp, TemporaryDirectory() as share:
            template = Path(share) / 'usage-monitor-for-claude.desktop'
            template.write_text('[Desktop Entry]\n', encoding='utf-8')
            with patch.dict(os.environ, {'XDG_CONFIG_HOME': tmp}), \
                 patch.object(autostart_mod, '_TEMPLATE', template):
                self.assertTrue(autostart_mod.set_autostart(True))
                self.assertTrue(autostart_mod.is_autostart_enabled())

    def test_disable_removes_the_entry(self):
        """Disabling removes the entry and reports the new state."""
        with TemporaryDirectory() as tmp, TemporaryDirectory() as share:
            template = Path(share) / 'usage-monitor-for-claude.desktop'
            template.write_text('[Desktop Entry]\n', encoding='utf-8')
            with patch.dict(os.environ, {'XDG_CONFIG_HOME': tmp}), \
                 patch.object(autostart_mod, '_TEMPLATE', template):
                autostart_mod.set_autostart(True)
                self.assertFalse(autostart_mod.set_autostart(False))
                self.assertFalse(autostart_mod.is_autostart_enabled())

    def test_disable_is_safe_when_already_absent(self):
        """Disabling something that was never enabled is not an error."""
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {'XDG_CONFIG_HOME': tmp}):
            self.assertFalse(autostart_mod.set_autostart(False))

    def test_missing_template_reports_real_state(self):
        """Without the packaged template, enabling reports failure rather than success."""
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {'XDG_CONFIG_HOME': tmp}), \
             patch.object(autostart_mod, '_TEMPLATE', Path(tmp) / 'missing.desktop'):
            self.assertFalse(autostart_mod.set_autostart(True))


class TestDaemonEventTests(unittest.TestCase):
    """Tests for the panel menu's event-command test entries."""

    def test_unknown_event_is_declined(self):
        """An unrecognized event name never launches anything."""
        daemon = UsageMonitorDaemon(publish=MagicMock())
        with patch.object(daemon_mod, 'run_event_command') as mock_run:
            self.assertFalse(daemon.run_event_test('does_not_exist'))
        mock_run.assert_not_called()

    def test_unconfigured_event_is_declined(self):
        """With no command configured, the entry does nothing."""
        daemon = UsageMonitorDaemon(publish=MagicMock())
        with patch.object(daemon_mod, 'ON_RESET_COMMAND', []), \
             patch.object(daemon_mod, 'run_event_command') as mock_run:
            self.assertFalse(daemon.run_event_test('reset_5h'))
        mock_run.assert_not_called()

    def test_configured_event_runs_with_captured_output(self):
        """A user-driven test surfaces failures instead of swallowing them."""
        daemon = UsageMonitorDaemon(publish=MagicMock())
        with patch.object(daemon_mod, 'ON_RESET_COMMAND', ['echo hi']), \
             patch.object(daemon_mod, 'run_event_command') as mock_run:
            self.assertTrue(daemon.run_event_test('reset_5h'))

        commands, env_vars = mock_run.call_args[0]
        self.assertEqual(commands, ['echo hi'])
        self.assertEqual(env_vars['USAGE_MONITOR_EVENT'], 'reset')
        self.assertEqual(env_vars['USAGE_MONITOR_VARIANT'], 'five_hour')
        self.assertTrue(mock_run.call_args[1]['capture_output'])

    def test_double_click_command_uses_current_usage(self):
        """The double-click command receives the latest quota state."""
        daemon = UsageMonitorDaemon(publish=MagicMock())
        daemon._last_response = {'five_hour': {'utilization': 42, 'resets_at': '2026-01-01T00:00:00+00:00'}}
        with patch.object(daemon_mod, 'ON_DOUBLE_CLICK_COMMAND', ['run']), \
             patch.object(daemon_mod, 'run_event_command') as mock_run:
            self.assertTrue(daemon.run_double_click_command())

        env_vars = mock_run.call_args[0][1]
        self.assertEqual(env_vars['USAGE_MONITOR_UTILIZATION_FIVE_HOUR'], '42')

    def test_double_click_declined_without_command(self):
        """No configured command means the middle click does nothing."""
        daemon = UsageMonitorDaemon(publish=MagicMock())
        with patch.object(daemon_mod, 'ON_DOUBLE_CLICK_COMMAND', []):
            self.assertFalse(daemon.run_double_click_command())


class TestDaemonRefreshGate(unittest.TestCase):
    """Tests for the D-Bus Refresh() gate."""

    def _daemon(self) -> UsageMonitorDaemon:
        return UsageMonitorDaemon(publish=MagicMock())

    def test_refresh_declined_while_away(self):
        """A refresh requested during idle or lock is declined, not queued."""
        daemon = self._daemon()
        with patch.object(daemon, '_is_user_away', return_value=True):
            self.assertFalse(daemon.request_refresh())
        self.assertFalse(daemon._refresh_requested.is_set())

    def test_refresh_accepted_when_present(self):
        """A refresh requested by a present user is recorded for the poll loop."""
        daemon = self._daemon()
        with patch.object(daemon, '_is_user_away', return_value=False):
            self.assertTrue(daemon.request_refresh())
        self.assertTrue(daemon._refresh_requested.is_set())

    def test_stop_wakes_the_poll_loop(self):
        """Stopping releases the wait so the thread can exit promptly."""
        daemon = self._daemon()
        daemon.stop()
        self.assertFalse(daemon.running)
        self.assertTrue(daemon._refresh_requested.is_set())


class TestDaemonAwayDetection(unittest.TestCase):
    """Tests for the idle and lock pause condition."""

    def test_locked_session_is_away(self):
        """A locked session pauses polling regardless of the idle threshold."""
        daemon = UsageMonitorDaemon(publish=MagicMock())
        with patch.object(daemon_mod, 'is_workstation_locked', return_value=True):
            self.assertTrue(daemon._is_user_away())

    def test_idle_below_threshold_is_present(self):
        """Idle time under the configured pause keeps the user present."""
        daemon = UsageMonitorDaemon(publish=MagicMock())
        with patch.object(daemon_mod, 'is_workstation_locked', return_value=False), \
             patch.object(daemon_mod, 'get_idle_seconds', return_value=1.0), \
             patch.object(daemon_mod, 'IDLE_PAUSE', 300):
            self.assertFalse(daemon._is_user_away())

    def test_idle_above_threshold_is_away(self):
        """Idle time past the configured pause stops polling."""
        daemon = UsageMonitorDaemon(publish=MagicMock())
        with patch.object(daemon_mod, 'is_workstation_locked', return_value=False), \
             patch.object(daemon_mod, 'get_idle_seconds', return_value=600.0), \
             patch.object(daemon_mod, 'IDLE_PAUSE', 300):
            self.assertTrue(daemon._is_user_away())

    def test_idle_pause_disabled_keeps_user_present(self):
        """With IDLE_PAUSE at 0, idle time never pauses polling."""
        daemon = UsageMonitorDaemon(publish=MagicMock())
        with patch.object(daemon_mod, 'is_workstation_locked', return_value=False), \
             patch.object(daemon_mod, 'get_idle_seconds', return_value=99999.0), \
             patch.object(daemon_mod, 'IDLE_PAUSE', 0):
            self.assertFalse(daemon._is_user_away())


class TestDaemonDeferredNotifications(unittest.TestCase):
    """Tests for notifications held back while the user is away."""

    def test_deferred_while_away(self):
        """A notification raised during lock is queued instead of shown."""
        daemon = UsageMonitorDaemon(publish=MagicMock())
        with patch.object(daemon, '_is_user_away', return_value=True), \
             patch.object(daemon, '_notify') as mock_notify:
            daemon._notify_or_defer('reset', 'body', 'title')

        mock_notify.assert_not_called()
        self.assertEqual(daemon._deferred_notifications['reset'], ('body', 'title'))

    def test_only_latest_per_category_is_kept(self):
        """Repeated events in one category collapse into a single notification."""
        daemon = UsageMonitorDaemon(publish=MagicMock())
        with patch.object(daemon, '_is_user_away', return_value=True):
            daemon._notify_or_defer('reset', 'first', 'title')
            daemon._notify_or_defer('reset', 'second', 'title')

        self.assertEqual(len(daemon._deferred_notifications), 1)
        self.assertEqual(daemon._deferred_notifications['reset'], ('second', 'title'))

    def test_flush_shows_and_clears(self):
        """Returning shows every deferred notification exactly once."""
        daemon = UsageMonitorDaemon(publish=MagicMock())
        with patch.object(daemon, '_is_user_away', return_value=True):
            daemon._notify_or_defer('reset', 'body', 'title')
            daemon._notify_or_defer('threshold_five_hour', 'other', 'title')

        with patch.object(daemon, '_notify') as mock_notify:
            daemon._flush_deferred_notifications()

        self.assertEqual(mock_notify.call_count, 2)
        self.assertEqual(daemon._deferred_notifications, {})


if __name__ == '__main__':
    unittest.main()
