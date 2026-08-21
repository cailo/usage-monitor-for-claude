"""
GNOME Frontend JS Tests
========================

Behavior tests for the GNOME extension's pure-logic modules, executed
with Node.js.  Skipped when Node.js is not installed - the app never
needs it; it is only a test runner, the same way ``test_popup_js.py``
uses it for the Windows popup.

Only the modules with no ``gi://`` imports can run here: ``color.js``
and ``statusText.js``.  Everything that touches Cairo or St needs a live
shell and is covered statically in ``test_gnome_frontend.py`` instead.

Scenarios import the real source file by URL rather than a concatenated
copy, so what runs is byte-for-byte what ships.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_FRONTEND_DIR = Path(__file__).resolve().parent.parent / 'frontends' / 'gnome'
_LOCALE_EN = Path(__file__).resolve().parent.parent / 'locale' / 'en.json'

_NODE = shutil.which('node')


def _run(module: str, body: str) -> dict:
    """Import *module* from the extension and run *body*, returning its JSON output.

    Parameters
    ----------
    module : str
        File name inside ``frontends/gnome/``.
    body : str
        JavaScript executed after the import.  It must call ``emit(value)``
        exactly once with the result to assert on.
    """
    source_url = (_FRONTEND_DIR / module).as_uri()
    script = (
        f"import * as mod from '{source_url}';\n"
        'const emit = value => console.log(JSON.stringify(value));\n'
        f'{body}\n'
    )

    with TemporaryDirectory() as tmp:
        script_path = Path(tmp) / 'scenario.mjs'
        script_path.write_text(script, encoding='utf-8')
        proc = subprocess.run([_NODE, str(script_path)], capture_output=True, text=True, timeout=30)

    if proc.returncode != 0:
        raise AssertionError(f'Node scenario failed:\n{proc.stderr}')

    return json.loads(proc.stdout)


# A Cairo context stub that records what setSourceRGBA() was handed.  That call
# is the whole point of color.js: a NaN reaching it draws nothing and logs
# nothing, which is the failure the module exists to prevent.
_CAIRO_STUB = '''
const recorded = [];
const cr = {setSourceRGBA(...args) { recorded.push(args); }};
'''


def _set_source_scenario(color_literal: str, alpha_scale: str = '1') -> str:
    """Build a scenario that calls setSource() and reports the four components."""
    return (
        f'{_CAIRO_STUB}\n'
        f'mod.setSource(cr, {color_literal}, {alpha_scale});\n'
        'const [red, green, blue, alpha] = recorded[0];\n'
        'emit({red, green, blue, alpha, calls: recorded.length});\n'
    )


@unittest.skipUnless(_NODE, 'Node.js not available')
class TestColorNormalization(unittest.TestCase):
    """Every colour representation the extension can be handed must yield 0-1 floats."""

    def assert_valid_rgba(self, result: dict):
        """Assert every component is a finite number within 0-1.

        This is the invariant that keeps Cairo from receiving NaN, which it
        renders as nothing at all without raising or logging.
        """
        for name in ('red', 'green', 'blue', 'alpha'):
            with self.subTest(component=name):
                value = result[name]
                self.assertIsInstance(value, (int, float))
                self.assertFalse(isinstance(value, bool))
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)

    def test_byte_range_fields_are_scaled(self):
        """The old Clutter.Color layout, and the literal fallbacks in the extension."""
        result = _run('color.js', _set_source_scenario('{red: 255, green: 128, blue: 0, alpha: 255}'))

        self.assert_valid_rgba(result)
        self.assertEqual(result['red'], 1.0)
        self.assertEqual(result['blue'], 0.0)
        self.assertAlmostEqual(result['green'], 128 / 255, places=6)

    def test_float_range_fields_are_passed_through(self):
        """Cogl.Color on GNOME Shell 47+, where the byte range became 0-1."""
        result = _run('color.js', _set_source_scenario('{red: 0.25, green: 0.5, blue: 1, alpha: 1}'))

        self.assert_valid_rgba(result)
        self.assertAlmostEqual(result['red'], 0.25, places=6)
        self.assertAlmostEqual(result['green'], 0.5, places=6)
        self.assertEqual(result['blue'], 1.0)

    def test_getter_only_colour_is_read(self):
        """The case the module exists for: fields undefined, getters present.

        A plain `color.red` here is undefined, which the previous inline
        arithmetic turned into NaN - an invisible icon with nothing in the log.
        """
        colour = (
            '{get_red: () => 0.5, get_green: () => 0.25, get_blue: () => 0, get_alpha: () => 1}'
        )
        result = _run('color.js', _set_source_scenario(colour))

        self.assert_valid_rgba(result)
        self.assertAlmostEqual(result['red'], 0.5, places=6)
        self.assertAlmostEqual(result['green'], 0.25, places=6)

    def test_byte_range_getters_are_scaled(self):
        colour = (
            '{get_red: () => 255, get_green: () => 0, get_blue: () => 0, get_alpha: () => 255}'
        )
        result = _run('color.js', _set_source_scenario(colour))

        self.assert_valid_rgba(result)
        self.assertEqual(result['red'], 1.0)
        self.assertEqual(result['alpha'], 1.0)

    def test_all_zero_components_are_not_mistaken_for_a_byte_colour(self):
        """Opaque black in float form: no component exceeds 1, and none should be scaled."""
        result = _run('color.js', _set_source_scenario('{red: 0, green: 0, blue: 0, alpha: 1}'))

        self.assert_valid_rgba(result)
        self.assertEqual(result['alpha'], 1.0)

    def test_missing_component_falls_back_instead_of_producing_nan(self):
        result = _run('color.js', _set_source_scenario('{red: 0.5, green: 0.5}'))

        self.assert_valid_rgba(result)

    def test_nan_component_falls_back(self):
        result = _run('color.js', _set_source_scenario('{red: NaN, green: 0, blue: 0, alpha: 1}'))

        self.assert_valid_rgba(result)

    def test_throwing_getter_falls_back(self):
        colour = '{get_red: () => { throw new Error("boom"); }}'
        result = _run('color.js', _set_source_scenario(colour))

        self.assert_valid_rgba(result)

    def test_null_colour_falls_back(self):
        result = _run('color.js', _set_source_scenario('null'))

        self.assert_valid_rgba(result)

    def test_alpha_scale_is_applied(self):
        result = _run('color.js', _set_source_scenario('{red: 1, green: 1, blue: 1, alpha: 1}', '0.35'))

        self.assert_valid_rgba(result)
        self.assertAlmostEqual(result['alpha'], 0.35, places=6)

    def test_out_of_range_components_are_clamped(self):
        """A float colour reporting 2.0 must not hand Cairo a value above 1."""
        result = _run('color.js', _set_source_scenario('{red: 400, green: -50, blue: 128, alpha: 255}'))

        self.assert_valid_rgba(result)
        self.assertEqual(result['red'], 1.0)
        self.assertEqual(result['green'], 0.0)


@unittest.skipUnless(_NODE, 'Node.js not available')
class TestThemeColorLookup(unittest.TestCase):
    """lookup_color() shape changes must degrade to the caller's fallback."""

    def test_found_colour_is_returned(self):
        scenario = (
            'const node = {lookup_color: () => [true, {red: 10, green: 20, blue: 30, alpha: 255}]};\n'
            "emit(mod.themeColor(node, '-x', {red: 0, green: 0, blue: 0, alpha: 0}));\n"
        )
        result = _run('color.js', scenario)

        self.assertEqual(result['red'], 10)

    def test_missing_colour_uses_the_fallback(self):
        scenario = (
            'const node = {lookup_color: () => [false, null]};\n'
            "emit(mod.themeColor(node, '-x', {red: 7, green: 0, blue: 0, alpha: 255}));\n"
        )
        result = _run('color.js', scenario)

        self.assertEqual(result['red'], 7)

    def test_throwing_lookup_uses_the_fallback(self):
        scenario = (
            'const node = {lookup_color: () => { throw new Error("no such property"); }};\n'
            "emit(mod.themeColor(node, '-x', {red: 7, green: 0, blue: 0, alpha: 255}));\n"
        )
        result = _run('color.js', scenario)

        self.assertEqual(result['red'], 7)

    def test_throwing_foreground_still_yields_a_drawable_colour(self):
        scenario = (
            'const node = {get_foreground_color: () => { throw new Error("not on stage"); }};\n'
            f'{_CAIRO_STUB}\n'
            'mod.setSource(cr, mod.foregroundColor(node), 1);\n'
            'const [red, green, blue, alpha] = recorded[0];\n'
            'emit({red, green, blue, alpha});\n'
        )
        result = _run('color.js', scenario)

        for name in ('red', 'green', 'blue', 'alpha'):
            with self.subTest(component=name):
                self.assertGreaterEqual(result[name], 0.0)
                self.assertLessEqual(result[name], 1.0)


@unittest.skipUnless(_NODE, 'Node.js not available')
class TestStatusText(unittest.TestCase):
    """The footer ticks once a second; its template substitution has to hold."""

    @classmethod
    def setUpClass(cls):
        # The real English templates, so a template and its substitution
        # cannot drift apart without this failing.
        cls.labels = json.dumps(json.loads(_LOCALE_EN.read_text(encoding='utf-8')))

    def _format_status(self, status: str, now: str = '1000') -> str:
        scenario = f'emit(mod.formatStatus({status}, {self.labels}, {now}));'
        return _run('statusText.js', scenario)

    def _format_duration(self, seconds: str) -> str:
        scenario = f'emit(mod.formatDuration({seconds}, {self.labels}));'
        return _run('statusText.js', scenario)

    def assert_no_leftover_placeholder(self, text: str):
        self.assertNotIn('{', text, f'unsubstituted placeholder in {text!r}')

    def test_seconds_only(self):
        text = self._format_duration('45')

        self.assertEqual(text, '45s')
        self.assert_no_leftover_placeholder(text)

    def test_minutes(self):
        text = self._format_duration('120')

        self.assertEqual(text, '2m')
        self.assert_no_leftover_placeholder(text)

    def test_hours_and_minutes(self):
        text = self._format_duration('3900')

        self.assertEqual(text, '1h 5m')
        self.assert_no_leftover_placeholder(text)

    def test_whole_hours_keep_the_minute_field(self):
        """3600 seconds is one hour and zero minutes, not a bare hour."""
        text = self._format_duration('3600')

        self.assertEqual(text, '1h 0m')
        self.assert_no_leftover_placeholder(text)

    def test_zero_is_rendered_as_seconds(self):
        text = self._format_duration('0')

        self.assertEqual(text, '0s')

    def test_recent_success_uses_the_seconds_template(self):
        text = self._format_status('{last_success_time: 970}', now='1000')

        self.assertIn('30', text)
        self.assert_no_leftover_placeholder(text)

    def test_at_sixty_seconds_it_switches_to_the_duration_template(self):
        text = self._format_status('{last_success_time: 940}', now='1000')

        self.assertIn('1m', text)
        self.assert_no_leftover_placeholder(text)

    def test_next_poll_is_appended(self):
        text = self._format_status('{last_success_time: 990, next_poll_time: 1300}', now='1000')

        self.assertIn('·', text)
        self.assertIn('5m', text)
        self.assert_no_leftover_placeholder(text)

    def test_next_poll_alone_needs_no_separator(self):
        text = self._format_status('{next_poll_time: 1300}', now='1000')

        self.assertNotIn('·', text)
        self.assert_no_leftover_placeholder(text)

    def test_a_past_next_poll_never_goes_negative(self):
        text = self._format_status('{next_poll_time: 500}', now='1000')

        self.assertNotIn('-', text)
        self.assert_no_leftover_placeholder(text)

    def test_hard_error_is_shown_verbatim(self):
        text = self._format_status('{is_error: true, text: "HTTP 500"}')

        self.assertEqual(text, 'HTTP 500')

    def test_first_refresh_reports_refreshing(self):
        text = self._format_status('{refreshing: true, last_success_time: 0}')

        self.assertEqual(text, 'Refreshing...')

    def test_error_beside_stale_data_wins(self):
        text = self._format_status('{last_success_time: 990, error: "HTTP 429"}', now='1000')

        self.assertEqual(text, 'HTTP 429')

    def test_missing_status_is_empty(self):
        self.assertEqual(self._format_status('null'), '')

    def test_missing_labels_never_leak_a_placeholder(self):
        """A snapshot from an older daemon may not carry every template."""
        scenario = 'emit(mod.formatStatus({last_success_time: 970}, {}, 1000));'
        text = _run('statusText.js', scenario)

        self.assert_no_leftover_placeholder(text)


if __name__ == '__main__':
    unittest.main()
