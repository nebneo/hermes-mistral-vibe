"""Actual Hermes transport/aux wrappers, with HTTP replaced by fake responses."""
import asyncio, json, os, tempfile, unittest
from unittest.mock import patch
import httpx
from vibe_provider import profile, MODEL, BASE, UA
from providers import register_provider

class RuntimeTests(unittest.TestCase):
    def test_real_transport_normal_request_and_aux_sync_async(self):
        from agent.transports.chat_completions import ChatCompletionsTransport
        from agent.auxiliary_client import resolve_provider_client
        register_provider(profile)
        seen = []
        def fake(req):
            data = json.loads(req.content)
            seen.append(data)
            self.assertEqual(str(req.url), BASE+'/chat/completions')
            self.assertEqual(req.headers['authorization'], 'Bearer fake-key')
            self.assertEqual(req.headers['user-agent'], UA)
            return httpx.Response(200, json={'id':'fake','object':'chat.completion','created':0,'model':MODEL,
                'choices':[{'index':0,'message':{'role':'assistant','content':'{"ok":true}'},'finish_reason':'stop'}],
                'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}})
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HERMES_HOME':home, 'MISTRAL_VIBE_API_KEY':'fake-key'}), patch('httpx.HTTPTransport', return_value=httpx.MockTransport(fake)):
            transport = ChatCompletionsTransport()
            kwargs = transport.build_kwargs(MODEL, [{'role':'user','content':'test'}],
                provider_profile=profile, base_url=BASE, reasoning_config={'enabled':False})
            client = profile.create_client(base_url=BASE)
            self.assertEqual(transport.normalize_response(client.chat.completions.create(**kwargs)).content, '{"ok":true}')
            client.close()
            client, model = resolve_provider_client('mistral-vibe', MODEL)
            self.assertIsNotNone(client)
            result = client.chat.completions.create(model=model, messages=[{'role':'user','content':'json'}],
                extra_body={'response_format':{'type':'json_object'}})
            self.assertEqual(result.choices[0].message.content, '{"ok":true}')
            client.close()
            async_client, model = resolve_provider_client('mistral-vibe', MODEL, async_mode=True)
            async def request():
                return await async_client.chat.completions.create(model=model, messages=[{'role':'user','content':'test'}])
            result = asyncio.run(request())
            self.assertEqual(result.choices[0].message.content, '{"ok":true}')
            self.assertEqual(len(seen), 3)
            async_client.close()

    def test_aux_async_stream_preserves_guard(self):
        from agent.auxiliary_client import resolve_provider_client
        register_provider(profile)
        chunk = {'id':'fake','object':'chat.completion.chunk','created':0,'model':MODEL,
            'choices':[{'index':0,'delta':{'content':'ok'},'finish_reason':'stop'}]}
        def fake(req):
            return httpx.Response(200, headers={'content-type':'text/event-stream'},
                content='data: '+json.dumps(chunk)+'\n\ndata: [DONE]\n\n')
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HERMES_HOME':home, 'MISTRAL_VIBE_API_KEY':'fake'}), patch('httpx.HTTPTransport', return_value=httpx.MockTransport(fake)):
            client, model = resolve_provider_client('mistral-vibe', MODEL, async_mode=True)
            async def request():
                with self.assertRaisesRegex(RuntimeError, 'current dedicated key catalog'):
                    await client.chat.completions.create(model='wrong', messages=[])
                stream = await client.chat.completions.create(model=model, messages=[], stream=True)
                return [part.choices[0].delta.content async for part in stream]
            self.assertEqual(asyncio.run(request()), ['ok'])
            client.close()

class FallbackBindingTests(unittest.TestCase):
    def test_guarded_client_exposes_attributes_hermes_reads_on_fallback(self):
        from types import SimpleNamespace
        from agent.client_lifecycle import _swap_fallback_clients
        from vibe_provider import GuardedClient
        client = GuardedClient(base_url=BASE)
        self.assertEqual(client.base_url, BASE)
        self.assertEqual(GuardedClient().base_url, BASE)
        self.assertEqual(client.api_key, '')
        agent = SimpleNamespace(model='x', _replace_primary_openai_client=lambda **k: None)
        _swap_fallback_clients(agent, client, 'mistral-vibe', MODEL, BASE, 'chat_completions')
        self.assertIs(agent.client, client)
        self.assertEqual(agent._client_kwargs['base_url'], BASE)
