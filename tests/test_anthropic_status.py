"""
Anthropic Status Tests
=======================

Unit tests for fetch_status() and AnthropicStatusCache.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import requests

from usage_monitor_for_claude.anthropic_status import (
    STATUS_API_URL, STATUS_INCIDENTS_URL, STATUS_UNKNOWN, AnthropicStatus, AnthropicStatusCache, fetch_status,
)


def _response(payload: dict, status_code: int = 200) -> MagicMock:
    """Build a mocked requests.Response with the given JSON payload."""
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    if status_code >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
    else:
        response.raise_for_status.return_value = None
    return response


def _get_side_effect(status_payload: dict, incidents_payload: dict | Exception | None = None):
    """Return a requests.get side effect serving the status and incidents endpoints."""
    def side_effect(url, timeout):
        if url == STATUS_API_URL:
            return _response(status_payload)
        if url == STATUS_INCIDENTS_URL:
            if isinstance(incidents_payload, Exception):
                raise incidents_payload
            return _response(incidents_payload if incidents_payload is not None else {'incidents': []})
        raise AssertionError(f'unexpected URL: {url}')
    return side_effect


# ---------------------------------------------------------------------------
# fetch_status
# ---------------------------------------------------------------------------

class TestFetchStatus(unittest.TestCase):
    """Tests for fetch_status()."""

    def test_operational_status(self):
        """Indicator 'none' is parsed with its description; incidents are not requested."""
        with patch('usage_monitor_for_claude.anthropic_status.requests.get') as mock_get:
            mock_get.side_effect = _get_side_effect({'status': {'indicator': 'none', 'description': 'All Systems Operational'}})
            status = fetch_status()

        self.assertEqual(status, AnthropicStatus(indicator='none', description='All Systems Operational'))
        mock_get.assert_called_once()
        self.assertEqual(mock_get.call_args[0][0], STATUS_API_URL)

    def test_degraded_indicators_parsed(self):
        """Each degraded indicator is passed through unchanged."""
        for indicator in ('minor', 'major', 'critical'):
            with self.subTest(indicator=indicator):
                with patch('usage_monitor_for_claude.anthropic_status.requests.get') as mock_get:
                    mock_get.side_effect = _get_side_effect({'status': {'indicator': indicator, 'description': 'Some Outage'}})
                    status = fetch_status()

                self.assertEqual(status.indicator, indicator)
                self.assertEqual(status.description, 'Some Outage')

    def test_degraded_status_carries_incident_name(self):
        """A degraded indicator fetches the most recent unresolved incident's name."""
        with patch('usage_monitor_for_claude.anthropic_status.requests.get') as mock_get:
            mock_get.side_effect = _get_side_effect(
                {'status': {'indicator': 'major', 'description': 'Partial System Outage'}},
                {'incidents': [{'name': 'Elevated errors on Claude API'}, {'name': 'Older incident'}]},
            )
            status = fetch_status()

        self.assertEqual(status.incident_name, 'Elevated errors on Claude API')
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(mock_get.call_args_list[1][0][0], STATUS_INCIDENTS_URL)

    def test_incident_fetch_failure_keeps_status(self):
        """A failing incidents request degrades to incident_name=None, not to unknown."""
        with patch('usage_monitor_for_claude.anthropic_status.requests.get') as mock_get:
            mock_get.side_effect = _get_side_effect(
                {'status': {'indicator': 'minor', 'description': 'Minor Service Outage'}},
                requests.Timeout(),
            )
            status = fetch_status()

        self.assertEqual(status.indicator, 'minor')
        self.assertIsNone(status.incident_name)

    def test_empty_incident_list(self):
        """An empty unresolved-incidents list yields incident_name=None."""
        with patch('usage_monitor_for_claude.anthropic_status.requests.get') as mock_get:
            mock_get.side_effect = _get_side_effect({'status': {'indicator': 'minor', 'description': 'Minor Service Outage'}}, {'incidents': []})
            status = fetch_status()

        self.assertIsNone(status.incident_name)

    def test_timeout_returns_unknown(self):
        with patch('usage_monitor_for_claude.anthropic_status.requests.get', side_effect=requests.Timeout()):
            self.assertEqual(fetch_status(), STATUS_UNKNOWN)

    def test_connection_error_returns_unknown(self):
        with patch('usage_monitor_for_claude.anthropic_status.requests.get', side_effect=requests.ConnectionError()):
            self.assertEqual(fetch_status(), STATUS_UNKNOWN)

    def test_http_error_returns_unknown(self):
        with patch('usage_monitor_for_claude.anthropic_status.requests.get', return_value=_response({}, status_code=503)):
            self.assertEqual(fetch_status(), STATUS_UNKNOWN)

    def test_invalid_json_returns_unknown(self):
        response = _response({})
        response.json.side_effect = ValueError('invalid JSON')
        with patch('usage_monitor_for_claude.anthropic_status.requests.get', return_value=response):
            self.assertEqual(fetch_status(), STATUS_UNKNOWN)

    def test_missing_indicator_returns_unknown(self):
        with patch('usage_monitor_for_claude.anthropic_status.requests.get', return_value=_response({'status': {'description': 'text only'}})):
            self.assertEqual(fetch_status(), STATUS_UNKNOWN)

    def test_null_status_returns_unknown(self):
        with patch('usage_monitor_for_claude.anthropic_status.requests.get', return_value=_response({'status': None})):
            self.assertEqual(fetch_status(), STATUS_UNKNOWN)

    def test_non_string_description_becomes_empty(self):
        with patch('usage_monitor_for_claude.anthropic_status.requests.get') as mock_get:
            mock_get.side_effect = _get_side_effect({'status': {'indicator': 'none', 'description': None}})
            status = fetch_status()

        self.assertEqual(status.description, '')

    def test_request_uses_short_timeout(self):
        """The status request must never stall the poll loop on a slow feed."""
        with patch('usage_monitor_for_claude.anthropic_status.requests.get') as mock_get:
            mock_get.side_effect = _get_side_effect({'status': {'indicator': 'none', 'description': 'All Systems Operational'}})
            fetch_status()

        self.assertLessEqual(mock_get.call_args[1]['timeout'], 5)


# ---------------------------------------------------------------------------
# AnthropicStatusCache
# ---------------------------------------------------------------------------

class TestAnthropicStatusCache(unittest.TestCase):
    """Tests for AnthropicStatusCache poll-interval enforcement."""

    def test_first_call_fetches(self):
        operational = AnthropicStatus(indicator='none', description='All Systems Operational')
        cache = AnthropicStatusCache(300)
        with patch('usage_monitor_for_claude.anthropic_status.fetch_status', return_value=operational) as mock_fetch:
            self.assertEqual(cache.current(), operational)

        mock_fetch.assert_called_once()

    def test_within_interval_serves_cached_status(self):
        operational = AnthropicStatus(indicator='none', description='All Systems Operational')
        cache = AnthropicStatusCache(300)
        with patch('usage_monitor_for_claude.anthropic_status.fetch_status', return_value=operational) as mock_fetch, \
             patch('usage_monitor_for_claude.anthropic_status.time.time', side_effect=[1000.0, 1299.0]):
            cache.current()
            self.assertEqual(cache.current(), operational)

        mock_fetch.assert_called_once()

    def test_after_interval_refetches(self):
        operational = AnthropicStatus(indicator='none', description='All Systems Operational')
        degraded = AnthropicStatus(indicator='minor', description='Minor Service Outage')
        cache = AnthropicStatusCache(300)
        with patch('usage_monitor_for_claude.anthropic_status.fetch_status', side_effect=[operational, degraded]) as mock_fetch, \
             patch('usage_monitor_for_claude.anthropic_status.time.time', side_effect=[1000.0, 1300.0]):
            self.assertEqual(cache.current(), operational)
            self.assertEqual(cache.current(), degraded)

        self.assertEqual(mock_fetch.call_count, 2)

    def test_unknown_result_is_cached_like_any_other(self):
        """A failed fetch is not retried before the interval elapses (no hammering)."""
        cache = AnthropicStatusCache(300)
        with patch('usage_monitor_for_claude.anthropic_status.fetch_status', return_value=STATUS_UNKNOWN) as mock_fetch, \
             patch('usage_monitor_for_claude.anthropic_status.time.time', side_effect=[1000.0, 1100.0]):
            self.assertEqual(cache.current(), STATUS_UNKNOWN)
            self.assertEqual(cache.current(), STATUS_UNKNOWN)

        mock_fetch.assert_called_once()

    def test_backward_clock_jump_reanchors(self):
        """A backward clock jump refetches instead of waiting out the pre-jump timestamp."""
        operational = AnthropicStatus(indicator='none', description='All Systems Operational')
        cache = AnthropicStatusCache(300)
        with patch('usage_monitor_for_claude.anthropic_status.fetch_status', return_value=operational) as mock_fetch, \
             patch('usage_monitor_for_claude.anthropic_status.time.time', side_effect=[10000.0, 500.0]):
            cache.current()
            cache.current()

        self.assertEqual(mock_fetch.call_count, 2)

    def test_rejects_non_positive_interval(self):
        with self.assertRaises(AssertionError):
            AnthropicStatusCache(0)


if __name__ == '__main__':
    unittest.main()
