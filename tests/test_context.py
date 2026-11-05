"""Offline tests for the context window taken from the dedicated key's catalog."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import vibe_provider as vp

def chat(model_id, window, aliases=None, **extra):
    row = {'id':model_id, 'max_context_length':window, 'capabilities':{'completion_chat':True}}
    if aliases is not None:
        row['aliases'] = aliases
    row.update(extra)
    return row

CATALOG = {'data':[
    chat('large', 1048576, ['large-4-0']),
    chat('large-4-0', 1048576, ['large']),
    chat('medium', 262144, ['medium-latest', 'shared']),
    chat('small', 262144, ['shared']),
    chat('glm', 1048576, ['glm-latest']),
    chat('latest', 131072),
    chat('medium-latest', 262144),
    {'id':'embed', 'max_context_length':8192, 'aliases':['embed-latest'],
     'capabilities':{'completion_chat':False}},
]}

class ContextWindowTests(unittest.TestCase):
    def setUp(self):
        vp._catalog_cache.clear()
        vp._context_cache.clear()

    def run_with(self, response, calls, key='dedicated', **kwargs):
        def fake(req):
            calls.append(req)
            return response(req) if callable(response) else response
        env = {'HERMES_HOME':self.home, 'MISTRAL_VIBE_API_KEY':key}
        with patch.dict(os.environ, env), patch('httpx.HTTPTransport',
                return_value=httpx.MockTransport(fake)):
            return vp.profile.live_context_length(**kwargs)

    def setup_home(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = folder.name

    def test_windows_come_from_ids_and_aliases_ids_win_and_ambiguity_is_dropped(self):
        self.setup_home()
        calls = []
        ok = httpx.Response(200, json=CATALOG)
        asked = lambda model: self.run_with(ok, calls, model=model, api_key='ordinary', base_url=vp.BASE)
        self.assertEqual(asked('large'), 1048576)
        self.assertEqual(asked('large-4-0'), 1048576)
        self.assertEqual(asked('medium'), 262144)
        self.assertEqual(asked('glm-latest'), 1048576)          # alias
        self.assertEqual(asked('latest'), 131072)               # an id, not an alias of anything
        self.assertEqual(asked('medium-latest'), 262144)        # id and alias agree
        self.assertEqual(asked('shared'), 262144)               # alias of two rows that agree is kept
        self.assertEqual(len(calls), 1, 'one /models request serves every lookup')

    def test_alias_claimed_with_different_windows_is_dropped(self):
        rows = [('a', 100, ['x', 'agree']), ('b', 200, ['x']), ('c', 100, ['agree']), ('x-real', 300, None)]
        windows = vp._context_windows(rows)
        self.assertNotIn('x', windows)
        self.assertEqual(windows['agree'], 100)
        self.assertEqual(windows['a'], 100)
        self.assertEqual(windows['x-real'], 300)

    def test_id_beats_an_alias_of_another_row(self):
        windows = vp._context_windows([('first', 100, ['second']), ('second', 200, [])])
        self.assertEqual(windows['second'], 200)

    def test_invalid_windows_are_ignored_per_model_without_invalidating_the_catalog(self):
        self.setup_home()
        payload = {'data':[
            chat('ok', 4096),
            chat('missing-window', None),
            chat('text-window', '262144'),
            chat('zero-window', 0),
            chat('negative-window', -1),
            chat('bool-window', True),
            chat('float-window', 1e6),
        ]}
        calls = []
        response = httpx.Response(200, json=payload)
        for model, expected in [('ok', 4096), ('missing-window', None), ('text-window', None),
                ('zero-window', None), ('negative-window', None), ('bool-window', None),
                ('float-window', None)]:
            with self.subTest(model=model):
                self.assertEqual(self.run_with(response, calls, model=model, base_url=vp.BASE), expected)
        self.assertEqual(len(calls), 1, 'bad windows must not invalidate the cached catalog')

    def test_non_chat_models_never_provide_a_window(self):
        self.setup_home()
        calls = []
        response = httpx.Response(200, json=CATALOG)
        self.assertIsNone(self.run_with(response, calls, model='embed', base_url=vp.BASE))
        self.assertIsNone(self.run_with(response, calls, model='embed-latest', base_url=vp.BASE))

    def test_request_uses_dedicated_key_and_ignores_the_key_hermes_passes(self):
        self.setup_home()
        calls = []
        self.run_with(httpx.Response(200, json=CATALOG), calls, key='dedicated',
            model='large', api_key='ordinary-mistral-key', base_url=vp.BASE)
        self.assertEqual(len(calls), 1)
        self.assertEqual(str(calls[0].url), vp.BASE + '/models')
        self.assertEqual(calls[0].headers['authorization'], 'Bearer dedicated')
        self.assertNotIn('ordinary-mistral-key', repr(calls[0].headers))

    def test_fails_closed_without_io_on_wrong_origin_missing_key_or_bad_model(self):
        self.setup_home()
        calls = []
        ok = httpx.Response(200, json=CATALOG)
        self.assertIsNone(self.run_with(ok, calls, model='large', base_url='https://evil.invalid/v1'))
        self.assertIsNone(self.run_with(ok, calls, key='', model='large', base_url=vp.BASE))
        self.assertIsNone(self.run_with(ok, calls, model=None, base_url=vp.BASE))
        self.assertEqual(calls, [])

    def test_fails_closed_on_http_error_redirect_and_malformed_catalog(self):
        cases = {
            'server-error': httpx.Response(503),
            'redirect': httpx.Response(302, headers={'location':'https://evil.invalid/models'}),
            'missing-data': httpx.Response(200, json={'models':[]}),
            'bad-row': httpx.Response(200, json={'data':[{'id':'x', 'max_context_length':1}]}),
        }
        for name, response in cases.items():
            vp._catalog_cache.clear()
            vp._context_cache.clear()
            self.setup_home()
            calls = []
            with self.subTest(name=name):
                self.assertIsNone(self.run_with(response, calls, model='x', base_url=vp.BASE))
                self.assertEqual(len(calls), 1)

    def test_unknown_model_is_none_not_a_guess(self):
        self.setup_home()
        self.assertIsNone(self.run_with(httpx.Response(200, json=CATALOG), [],
            model='not-in-catalog', base_url=vp.BASE))

    def test_cache_is_scoped_and_never_holds_the_key(self):
        calls = []
        def answer(req):
            window = 111 if req.headers['authorization'] == 'Bearer key-one' else 222
            return httpx.Response(200, json={'data':[chat('m', window)]})
        with tempfile.TemporaryDirectory() as home:
            self.home = home
            self.assertEqual(self.run_with(answer, calls, key='key-one', model='m', base_url=vp.BASE), 111)
            self.assertEqual(self.run_with(answer, calls, key='key-one', model='m', base_url=vp.BASE), 111)
            self.assertEqual(self.run_with(answer, calls, key='key-two', model='m', base_url=vp.BASE), 222)
        self.assertEqual(len(calls), 2)
        text = repr(vp._context_cache)
        self.assertNotIn('key-one', text)
        self.assertNotIn('key-two', text)

    def test_catalog_models_list_is_unchanged_by_the_window_data(self):
        self.setup_home()
        calls = []
        def fake(req):
            calls.append(req)
            return httpx.Response(200, json=CATALOG)
        with patch.dict(os.environ, {'HERMES_HOME':self.home, 'MISTRAL_VIBE_API_KEY':'dedicated'}), patch(
                'httpx.HTTPTransport', return_value=httpx.MockTransport(fake)):
            models = vp.profile.fetch_models(base_url=vp.BASE)
            self.assertEqual(vp.profile.live_context_length('large', base_url=vp.BASE), 1048576)
        self.assertEqual(models, ['large', 'large-4-0', 'medium', 'small', 'glm', 'latest', 'medium-latest'])
        self.assertEqual(len(calls), 1)

    def test_profile_claims_the_mistral_host_for_metadata_only(self):
        from providers import profile_for_host, register_provider
        register_provider(vp.profile)
        self.assertIs(profile_for_host(vp.BASE, metadata=True), vp.profile)
        self.assertIsNot(profile_for_host(vp.BASE), vp.profile, 'must not claim the host for wire routing')

    def test_real_hermes_resolution_uses_the_catalog_window(self):
        from agent.model_metadata import get_model_context_length
        from providers import register_provider
        register_provider(vp.profile)
        self.setup_home()
        calls = []
        def fake(req):
            calls.append(req)
            return httpx.Response(200, json=CATALOG)
        with patch.dict(os.environ, {'HERMES_HOME':self.home, 'MISTRAL_VIBE_API_KEY':'dedicated'}), patch(
                'httpx.HTTPTransport', return_value=httpx.MockTransport(fake)):
            self.assertEqual(get_model_context_length('large', base_url=vp.BASE, provider='mistral-vibe'), 1048576)
            self.assertEqual(get_model_context_length('medium', base_url=vp.BASE, provider='mistral-vibe'), 262144)
            self.assertEqual(get_model_context_length('glm-latest', base_url=vp.BASE, provider='mistral-vibe'), 1048576)
        self.assertEqual(len(calls), 1)

if __name__ == '__main__':
    unittest.main()
