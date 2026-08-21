"""
GNOME Frontend Tests
=====================

Contract tests between the GNOME Shell extension and the daemon.

The extension is JavaScript and cannot import the Python service, so it
restates the D-Bus interface as an XML literal.  That copy is the one
thing in the port that can drift silently: adding a method to
``service.py`` leaves the extension calling an interface that no longer
matches, and nothing fails until a user clicks the menu entry.  These
tests compare the two definitions directly.
"""
from __future__ import annotations

import json
import os
import re
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path

# The daemon binds to python-dbus, which exists only on the Linux side.
if os.name == 'nt':
    raise unittest.SkipTest('Linux-only application layer')

from usage_monitor_linux.names import INTERFACE, OBJECT_PATH
from usage_monitor_linux.service import UsageMonitorService

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / 'frontends' / 'gnome'
_CLIENT_SOURCE = (_FRONTEND_DIR / 'daemonClient.js').read_text(encoding='utf-8')

# Every file the extension is made of, so a rename that misses the packaging
# is caught here rather than by an empty panel on the user's machine.
_EXTENSION_FILES = (
    'metadata.json', 'stylesheet.css', 'extension.js', 'color.js', 'statusText.js',
    'daemonClient.js', 'indicator.js', 'layout.js', 'panelIcon.js', 'usageBar.js',
)

_JAVASCRIPT_FILES = tuple(name for name in _EXTENSION_FILES if name.endswith('.js'))

_BLOCK_COMMENT = re.compile(r'/\*.*?\*/', re.DOTALL)
_LINE_COMMENT = re.compile(r'//[^\n]*')


def _code_only(source: str) -> str:
    """Return *source* with its comments removed.

    The compatibility checks below look for API names that must not be
    *called*, and those same names appear in the comments explaining why -
    ``color.js`` documents the removal of ``Clutter.Color`` at length.
    Stripping comments keeps the guard on the code without forbidding the
    prose that justifies it.

    Deliberately naive: it would also strip a ``//`` inside a string literal,
    which none of these files contain.
    """
    return _LINE_COMMENT.sub('', _BLOCK_COMMENT.sub('', source))


def _javascript_constant(name: str) -> str:
    """Return the value of a top-level ``const NAME = '...'`` in the client."""
    match = re.search(rf"^const {name} = '([^']*)';$", _CLIENT_SOURCE, re.MULTILINE)
    assert match is not None, f'{name} not found in daemonClient.js'
    return match.group(1)


def _declared_interface() -> ElementTree.Element:
    """Return the ``<interface>`` element the extension declares."""
    match = re.search(r'const IFACE_XML = `(.*?)`;', _CLIENT_SOURCE, re.DOTALL)
    assert match is not None, 'IFACE_XML not found in daemonClient.js'

    node = ElementTree.fromstring(match.group(1).strip())
    interface = node.find('interface')
    assert interface is not None, 'IFACE_XML declares no interface'
    return interface


def _service_methods() -> dict[str, tuple[str, str]]:
    """Return ``{name: (in_signature, out_signature)}`` for the daemon's own methods.

    Filtered to ``INTERFACE``: ``dbus.service.Object`` also carries
    ``Introspect`` on ``org.freedesktop.DBus.Introspectable``, a standard
    interface Gio implements for the client, which the extension neither
    declares nor calls.
    """
    methods = {}
    for name in dir(UsageMonitorService):
        attribute = getattr(UsageMonitorService, name)
        if getattr(attribute, '_dbus_is_method', False) and attribute._dbus_interface == INTERFACE:
            methods[name] = (attribute._dbus_in_signature or '', attribute._dbus_out_signature or '')

    return methods


def _service_signals() -> dict[str, str]:
    """Return ``{name: signature}`` for the daemon's own signals."""
    signals = {}
    for name in dir(UsageMonitorService):
        attribute = getattr(UsageMonitorService, name)
        if getattr(attribute, '_dbus_is_signal', False) and attribute._dbus_interface == INTERFACE:
            signals[name] = attribute._dbus_signature or ''

    return signals


def _declared_signatures(interface: ElementTree.Element, tag: str) -> dict[str, tuple[str, str]]:
    """Return ``{name: (in_signature, out_signature)}`` for one XML tag."""
    declared = {}
    for element in interface.findall(tag):
        incoming = ''.join(arg.get('type', '') for arg in element.findall('arg') if arg.get('direction', 'in') == 'in')
        outgoing = ''.join(arg.get('type', '') for arg in element.findall('arg') if arg.get('direction') == 'out')
        declared[element.get('name', '')] = (incoming, outgoing)

    return declared


# ---------------------------------------------------------------------------
# D-Bus contract
# ---------------------------------------------------------------------------

class TestDBusContract(unittest.TestCase):

    def test_interface_name_matches_the_daemon(self):
        self.assertEqual(_declared_interface().get('name'), INTERFACE)

    def test_object_path_matches_the_daemon(self):
        # The extension cannot derive the path from config_dir_suffix(), so it
        # hardcodes the default instance's path - which must stay the one the
        # daemon exports when no --config-dir is in play.
        self.assertEqual(_javascript_constant('OBJECT_PATH'), OBJECT_PATH)

    def test_bus_name_matches_the_interface(self):
        self.assertEqual(_javascript_constant('BUS_NAME'), INTERFACE)

    def test_every_daemon_method_is_declared(self):
        declared = _declared_signatures(_declared_interface(), 'method')
        self.assertEqual(set(declared), set(_service_methods()))

    def test_method_signatures_match(self):
        declared = _declared_signatures(_declared_interface(), 'method')
        for name, signatures in _service_methods().items():
            with self.subTest(method=name):
                self.assertEqual(declared[name], signatures)

    def test_every_daemon_signal_is_declared(self):
        declared = _declared_signatures(_declared_interface(), 'signal')
        self.assertEqual(set(declared), set(_service_signals()))

    def test_signal_signatures_match(self):
        declared = _declared_signatures(_declared_interface(), 'signal')
        for name, signature in _service_signals().items():
            with self.subTest(signal=name):
                self.assertEqual(declared[name][0], signature)


# ---------------------------------------------------------------------------
# Extension manifest
# ---------------------------------------------------------------------------

class TestExtensionManifest(unittest.TestCase):

    def setUp(self):
        self.metadata = json.loads((_FRONTEND_DIR / 'metadata.json').read_text(encoding='utf-8'))

    def test_required_keys_are_present(self):
        # GNOME Shell refuses to load an extension missing any of these.
        for key in ('uuid', 'name', 'description', 'shell-version'):
            with self.subTest(key=key):
                self.assertIn(key, self.metadata)

    def test_uuid_matches_the_directory_convention(self):
        # The installed directory has to be named after the uuid, so a
        # mismatch here means the packaged extension never gets loaded.
        self.assertEqual(self.metadata['uuid'], 'usage-monitor-for-claude@cailo.github.com')

    def test_shell_versions_are_esm_capable(self):
        # The extension uses ESM imports and the Extension base class, both of
        # which landed in GNOME 45; claiming support for 44 would load a file
        # the older shell cannot parse.
        for version in self.metadata['shell-version']:
            with self.subTest(version=version):
                self.assertGreaterEqual(int(version.split('.')[0]), 45)

    def test_every_source_file_exists(self):
        for name in _EXTENSION_FILES:
            with self.subTest(file=name):
                self.assertTrue((_FRONTEND_DIR / name).is_file())


# ---------------------------------------------------------------------------
# Snapshot coupling
# ---------------------------------------------------------------------------

class TestShellCompatibility(unittest.TestCase):
    """Guards the decisions that let one copy run on GNOME Shell 45 to 49.

    None of this executes JavaScript - it cannot, without a live shell.  What
    it does is stop a future edit from quietly undoing a compatibility choice
    that was made deliberately, in a codebase where the only other feedback is
    a broken panel on someone else's machine.
    """

    def setUp(self):
        self.sources = {
            name: _code_only((_FRONTEND_DIR / name).read_text(encoding='utf-8'))
            for name in _JAVASCRIPT_FILES
        }

    def test_clutter_color_is_never_referenced(self):
        # Removed in GNOME Shell 47 and merged into Cogl.Color. A reference
        # would throw on every supported shell from 47 onwards.
        for name, source in self.sources.items():
            with self.subTest(file=name):
                self.assertNotIn('Clutter.Color', source)

    def test_box_layout_orientation_is_never_a_construct_property(self):
        # `vertical: true` is deprecated since GNOME Shell 48 in favour of
        # Clutter.Orientable. The property assignment form stays allowed: it is
        # the fallback branch of the feature detection in layout.js.
        for name, source in self.sources.items():
            with self.subTest(file=name):
                self.assertIsNone(
                    re.search(r'\bvertical:\s*true', source),
                    'orientation must go through layout.js, not a construct property',
                )

    def test_colour_reading_is_centralised(self):
        # Component access differs by shell version and by how the binding was
        # generated; an inline read is how a NaN colour - which draws nothing
        # and logs nothing - gets back in.
        for name, source in self.sources.items():
            if name == 'color.js':
                continue
            with self.subTest(file=name):
                self.assertNotIn('setSourceRGBA', source)
                self.assertNotIn('lookup_color', source)

    def test_cairo_contexts_are_always_disposed(self):
        # GJS does not free a Cairo context on garbage collection, so every
        # get_context() needs a matching $dispose() or the panel leaks a
        # surface per repaint.
        for name, source in self.sources.items():
            with self.subTest(file=name):
                self.assertEqual(
                    source.count('get_context()'), source.count('$dispose()'),
                    'every get_context() needs a matching $dispose()',
                )


class TestSnapshotCoupling(unittest.TestCase):
    """The extension renders label keys by name; a renamed key blanks the UI."""

    def setUp(self):
        self.sources = ''.join(
            (_FRONTEND_DIR / name).read_text(encoding='utf-8') for name in _JAVASCRIPT_FILES
        )

    def test_referenced_labels_exist_in_the_snapshot(self):
        from usage_monitor_linux.snapshot import build_snapshot
        from usage_monitor_for_claude.cache import CacheSnapshot

        snapshot = build_snapshot(
            CacheSnapshot(usage={}, profile=None, last_success_time=0.0, refreshing=False, last_error=None, version=1),
            installations=[],
        )

        referenced = set(re.findall(r"_label\('([a-z0-9_]+)'\)", self.sources))
        self.assertTrue(referenced, 'no label lookups found - did _label() get renamed?')

        missing = referenced - set(snapshot['labels'])
        self.assertEqual(missing, set(), f'labels referenced by the extension but absent from the snapshot: {missing}')

    def test_referenced_event_names_exist_in_the_snapshot(self):
        from usage_monitor_linux.snapshot import build_snapshot
        from usage_monitor_for_claude.cache import CacheSnapshot

        snapshot = build_snapshot(
            CacheSnapshot(usage={}, profile=None, last_success_time=0.0, refreshing=False, last_error=None, version=1),
            installations=[],
        )

        referenced = set(re.findall(r"_eventConfigured\('([a-z0-9_]+)'\)", self.sources))
        self.assertTrue(referenced, 'no event lookups found - did _eventConfigured() get renamed?')

        missing = referenced - set(snapshot['events'])
        self.assertEqual(missing, set(), f'events referenced by the extension but absent from the snapshot: {missing}')


if __name__ == '__main__':
    unittest.main()
