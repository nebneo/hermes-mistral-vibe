"""Offline contract tests for the /usage hook: billing budget to usage windows."""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class UsageTests(unittest.TestCase):
    def test_budgets_map_to_windows_and_skip_malformed(self):
        from vibe_provider import _budget_windows
        data = {'vibe_budget': {'usage_percentage': 7.5, 'reset_at': '2026-12-01T00:00:00Z'},
                'api_budget': {'usage_percentage': 'n/a'}}
        windows = _budget_windows(data)
        self.assertEqual([(w.label, w.used_percent) for w in windows], [('Vibe monthly', 7.5)])
        self.assertEqual(windows[0].reset_at.isoformat(), '2026-12-01T00:00:00+00:00')
        self.assertEqual(_budget_windows(['not', 'a', 'dict']), [])

    def test_fetch_sends_bearer_key_to_fixed_origin_and_fails_open(self):
        from unittest.mock import patch
        import tempfile
        import httpx
        from vibe_provider import profile, BASE
        seen = []
        payload = {'vibe_budget': {'usage_percentage': 10.0, 'reset_at': '2026-12-01T00:00:00Z'}}

        def fake(req):
            seen.append(req)
            return httpx.Response(200, json=payload)

        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {
                'HERMES_HOME': home, 'MISTRAL_VIBE_API_KEY': 'dedicated'}), patch(
                'httpx.HTTPTransport', return_value=httpx.MockTransport(fake)):
            snap = profile.fetch_account_usage(base_url=BASE, api_key='dedicated')
            self.assertIsNotNone(snap)
            self.assertEqual(snap.windows[0].used_percent, 10.0)
            self.assertEqual(str(seen[0].url), BASE + '/billing/budget')
            self.assertEqual(seen[0].headers['Authorization'], 'Bearer dedicated')
            self.assertIsNone(profile.fetch_account_usage(base_url='https://evil.example/v1', api_key='x'))


if __name__ == '__main__':
    unittest.main()
