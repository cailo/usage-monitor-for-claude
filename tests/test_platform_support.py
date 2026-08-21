"""Tests for platform_support - the single place where Windows and Linux diverge."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from usage_monitor_for_claude import platform_support


def _windows_ctypes(chars: int, itime_value: int) -> MagicMock:
    """Build a fake ctypes module whose GetLocaleInfoEx returns *chars* and *itime_value*."""
    fake = MagicMock()
    fake.wintypes.DWORD.return_value.value = itime_value
    fake.windll.kernel32.GetLocaleInfoEx.return_value = chars
    return fake


class TestSystemTimeFormatWindows(unittest.TestCase):
    """Tests for the Windows LOCALE_ITIME branch of system_time_format()."""

    def _detect(self, chars: int, itime_value: int) -> str:
        """Run detection against a faked Win32 locale API on any platform."""
        fake = _windows_ctypes(chars, itime_value)
        with patch.object(platform_support, 'IS_WINDOWS', True), \
             patch.dict(sys.modules, {'ctypes': fake, 'ctypes.wintypes': fake.wintypes}):
            return platform_support.system_time_format()

    def test_itime_one_is_24h(self):
        """LOCALE_ITIME of 1 maps to a 24-hour clock."""
        self.assertEqual(self._detect(chars=2, itime_value=1), '24h')

    def test_itime_zero_is_12h(self):
        """LOCALE_ITIME of 0 maps to a 12-hour clock."""
        self.assertEqual(self._detect(chars=2, itime_value=0), '12h')

    def test_query_failure_falls_back_to_24h(self):
        """A failed locale query (0 chars written) falls back to 24-hour."""
        self.assertEqual(self._detect(chars=0, itime_value=0), '24h')


class TestSystemTimeFormatPosix(unittest.TestCase):
    """Tests for the POSIX T_FMT branch of system_time_format()."""

    def _detect(self, time_format: str) -> str:
        """Run detection with the locale's T_FMT string mocked."""
        with patch.object(platform_support, 'IS_WINDOWS', False), \
             patch.object(platform_support._locale, 'setlocale'), \
             patch.object(platform_support._locale, 'nl_langinfo', return_value=time_format):
            return platform_support.system_time_format()

    def test_24h_format(self):
        """A T_FMT without AM/PM directives is a 24-hour clock."""
        self.assertEqual(self._detect('%H:%M:%S'), '24h')

    def test_12h_format_from_am_pm(self):
        """A %p directive marks a 12-hour clock."""
        self.assertEqual(self._detect('%I:%M:%S %p'), '12h')

    def test_12h_format_from_hour_directive(self):
        """A %I directive alone is enough to mark a 12-hour clock."""
        self.assertEqual(self._detect('%I:%M'), '12h')

    def test_locale_error_falls_back_to_24h(self):
        """A locale that cannot be set falls back to 24-hour."""
        with patch.object(platform_support, 'IS_WINDOWS', False), \
             patch.object(platform_support._locale, 'setlocale', side_effect=platform_support._locale.Error):
            self.assertEqual(platform_support.system_time_format(), '24h')

    def test_missing_nl_langinfo_falls_back_to_24h(self):
        """Absent nl_langinfo support falls back to 24-hour instead of raising."""
        with patch.object(platform_support, 'IS_WINDOWS', False), \
             patch.object(platform_support._locale, 'setlocale'), \
             patch.object(platform_support._locale, 'nl_langinfo', side_effect=AttributeError):
            self.assertEqual(platform_support.system_time_format(), '24h')


class TestNoWindowFlags(unittest.TestCase):
    """Tests for no_window_flags()."""

    def test_zero_on_linux(self):
        """Linux subprocesses need no flag - there is no console to suppress."""
        with patch.object(platform_support, 'IS_WINDOWS', False):
            self.assertEqual(platform_support.no_window_flags(), 0)

    def test_create_no_window_on_windows(self):
        """Windows subprocesses get CREATE_NO_WINDOW."""
        fake_subprocess = MagicMock()
        fake_subprocess.CREATE_NO_WINDOW = 0x08000000
        with patch.object(platform_support, 'IS_WINDOWS', True), \
             patch.dict(sys.modules, {'subprocess': fake_subprocess}):
            self.assertEqual(platform_support.no_window_flags(), 0x08000000)


class TestErrorBox(unittest.TestCase):
    """Tests for error_box()."""

    def test_prints_to_stderr_on_linux(self):
        """Without a desktop dialog, the message goes to stderr for the journal."""
        with patch.object(platform_support, 'IS_WINDOWS', False), \
             patch('builtins.print') as mock_print:
            platform_support.error_box('the detail', 'The Title')

        self.assertIn('The Title', mock_print.call_args[0][0])
        self.assertIn('the detail', mock_print.call_args[0][0])
        self.assertIs(mock_print.call_args[1]['file'], sys.stderr)

    def test_shows_message_box_on_windows(self):
        """Windows gets a modal dialog with the requested icon."""
        fake = MagicMock()
        with patch.object(platform_support, 'IS_WINDOWS', True), \
             patch.dict(sys.modules, {'ctypes': fake}):
            platform_support.error_box('the detail', 'The Title', 0x30)

        fake.windll.user32.MessageBoxW.assert_called_once_with(0, 'the detail', 'The Title', 0x30)

    def test_truncates_long_message_on_windows(self):
        """An oversized message is truncated so MessageBoxW stays well-behaved."""
        fake = MagicMock()
        with patch.object(platform_support, 'IS_WINDOWS', True), \
             patch.dict(sys.modules, {'ctypes': fake}):
            platform_support.error_box('x' * 5000, 'The Title')

        self.assertEqual(len(fake.windll.user32.MessageBoxW.call_args[0][1]), 2000)


class TestDesktopUiLanguage(unittest.TestCase):
    """Tests for desktop_ui_language() - the gettext precedence used by KDE and GNOME."""

    def _detect(self, is_windows: bool = False, **environment: str) -> str:
        """Run detection against a fully controlled environment."""
        with patch.object(platform_support, 'IS_WINDOWS', is_windows), \
             patch.dict(os.environ, environment, clear=True):
            return platform_support.desktop_ui_language()

    def test_windows_reports_nothing(self):
        """Windows has no separate UI-language variable, so the caller keeps its own detection."""
        self.assertEqual(self._detect(is_windows=True, LANGUAGE='en_US', LANG='es_AR.UTF-8'), '')

    def test_language_wins_over_lang(self):
        """An English desktop with Argentine formats reports English, not Spanish."""
        self.assertEqual(self._detect(LANGUAGE='en_US', LANG='es_AR.UTF-8'), 'en_US')

    def test_language_list_uses_first_entry(self):
        """LANGUAGE holds a colon-separated preference list; the first entry wins."""
        self.assertEqual(self._detect(LANGUAGE='de_DE:fr_FR:en', LANG='es_AR.UTF-8'), 'de_DE')

    def test_falls_back_to_lang_without_language(self):
        """Without LANGUAGE the messages locale decides."""
        self.assertEqual(self._detect(LANG='de_DE.UTF-8'), 'de_DE.UTF-8')

    def test_lc_all_outranks_lc_messages_and_lang(self):
        """LC_ALL overrides every other messages variable."""
        self.assertEqual(self._detect(LC_ALL='ja_JP.UTF-8', LC_MESSAGES='fr_FR.UTF-8', LANG='de_DE.UTF-8'), 'ja_JP.UTF-8')

    def test_lc_messages_outranks_lang(self):
        """LC_MESSAGES overrides LANG."""
        self.assertEqual(self._detect(LC_MESSAGES='fr_FR.UTF-8', LANG='de_DE.UTF-8'), 'fr_FR.UTF-8')

    def test_neutral_locale_ignores_language(self):
        """Under the C locale a translated interface is explicitly not wanted."""
        self.assertEqual(self._detect(LANGUAGE='de_DE', LC_ALL='C.UTF-8'), 'C.UTF-8')

    def test_posix_locale_ignores_language(self):
        """POSIX is the same neutral locale under its other name."""
        self.assertEqual(self._detect(LANGUAGE='de_DE', LANG='POSIX'), 'POSIX')

    def test_empty_environment_reports_nothing(self):
        """With nothing set there is no desktop language to report."""
        self.assertEqual(self._detect(), '')

    def test_blank_variables_are_skipped(self):
        """An empty LC_ALL does not shadow the LANG that follows it."""
        self.assertEqual(self._detect(LC_ALL='', LC_MESSAGES='', LANG='it_IT.UTF-8'), 'it_IT.UTF-8')


if __name__ == '__main__':
    unittest.main()
