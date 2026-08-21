"""
Platform Support
=================

Single place where behavior differs between Windows and Linux.

The application is Windows-first: every other module keeps its native
Windows implementation and delegates only the handful of operations
that have no Windows equivalent on Linux (message boxes, console-less
subprocess flags, interface language and clock detection) to this module.  Keeping the
branching here means an audit only has to read one small file to know
exactly where platform behavior diverges.
"""
from __future__ import annotations

import locale as _locale
import os
import sys

__all__ = ['IS_WINDOWS', 'desktop_ui_language', 'error_box', 'no_window_flags', 'system_time_format']

IS_WINDOWS = sys.platform == 'win32'

# Messages locale in gettext precedence order; the first one set decides.
_MESSAGES_LOCALE_VARS = ('LC_ALL', 'LC_MESSAGES', 'LANG')
_NEUTRAL_LOCALES = frozenset({'C', 'POSIX'})


def desktop_ui_language() -> str:
    """Return the desktop's interface language, or an empty string when there is none to report.

    On Linux the interface language and the regional formats are two
    independent settings.  KDE Plasma and GNOME write the language into
    ``LANGUAGE`` and leave ``LANG`` for dates, numbers and currency, so an
    English desktop used in Argentina runs with ``LANGUAGE=en_US`` next to
    ``LANG=es_AR.UTF-8``.  ``locale.getlocale()`` reports the formats and
    would answer Spanish for that session, so the gettext precedence is
    applied here instead: ``LANGUAGE`` first, then the messages locale from
    ``LC_ALL``, ``LC_MESSAGES`` or ``LANG``.

    Windows has no such split - the user's interface language is what
    ``locale.getlocale()`` already reports - so it answers with an empty
    string and leaves the caller's own detection untouched.

    Returns
    -------
    str
        A locale string such as ``'en_US'``, or ``''`` when the platform
        exposes no interface language of its own.
    """
    if IS_WINDOWS:
        return ''

    messages_locale = ''
    for variable in _MESSAGES_LOCALE_VARS:
        value = os.environ.get(variable, '').strip()
        if value:
            messages_locale = value
            break

    # Under the neutral C/POSIX locale a translated interface is explicitly
    # not wanted, and gettext ignores LANGUAGE there for that reason.
    if messages_locale.split('.')[0] in _NEUTRAL_LOCALES:
        return messages_locale

    # LANGUAGE holds a colon-separated preference list; only the first entry
    # can be honored because a single translation file is loaded.
    preferred = os.environ.get('LANGUAGE', '').strip()
    if preferred:
        return preferred.split(':')[0]

    return messages_locale


def error_box(message: str, title: str, icon: int = 0x10) -> None:
    """Show a modal error dialog, or print to stderr where none exists.

    On Linux the process is a headless daemon: a dialog would have no
    parent window and no desktop session to attach to, so the message
    goes to stderr where the systemd user journal records it.

    Parameters
    ----------
    message : str
        Body text of the dialog.
    title : str
        Window title of the dialog.
    icon : int
        ``MB_ICONERROR`` (0x10) or ``MB_ICONWARNING`` (0x30).  Ignored
        on Linux.
    """
    if not IS_WINDOWS:
        print(f'{title}: {message}', file=sys.stderr, flush=True)
        return

    import ctypes

    ctypes.windll.user32.MessageBoxW(0, message[:2000], title, icon)


def no_window_flags() -> int:
    """Return ``creationflags`` that keep a subprocess from opening a console.

    ``CREATE_NO_WINDOW`` exists only on Windows; on Linux a subprocess
    never gets a console of its own, so no flag is needed.
    """
    if not IS_WINDOWS:
        return 0

    import subprocess

    return subprocess.CREATE_NO_WINDOW


def system_time_format() -> str:
    """Detect whether the system clock uses a 24-hour or 12-hour format.

    On Windows this reads ``LOCALE_ITIME`` for the current user locale,
    which honors regional customizations.  On Linux it inspects the
    locale's time format string: a ``%p`` (AM/PM) or ``%I`` (12-hour
    hour) directive means a 12-hour clock.

    Returns
    -------
    str
        ``'24h'`` or ``'12h'``.  Falls back to ``'24h'`` when the query
        fails.
    """
    if not IS_WINDOWS:
        return _posix_time_format()

    import ctypes
    import ctypes.wintypes

    LOCALE_NAME_USER_DEFAULT = None  # NULL selects the current user locale
    LOCALE_ITIME = 0x00000023
    LOCALE_RETURN_NUMBER = 0x20000000
    value = ctypes.wintypes.DWORD()
    chars = ctypes.windll.kernel32.GetLocaleInfoEx(
        LOCALE_NAME_USER_DEFAULT, LOCALE_ITIME | LOCALE_RETURN_NUMBER,
        ctypes.cast(ctypes.byref(value), ctypes.c_wchar_p), 2,
    )
    if chars == 0:
        return '24h'

    return '24h' if value.value == 1 else '12h'


def _posix_time_format() -> str:
    """Read the clock format from the POSIX locale's ``T_FMT`` string."""
    try:
        _locale.setlocale(_locale.LC_TIME, '')
        time_format = _locale.nl_langinfo(_locale.T_FMT)
    except (_locale.Error, AttributeError, ValueError):
        return '24h'

    return '12h' if '%p' in time_format or '%I' in time_format else '24h'
