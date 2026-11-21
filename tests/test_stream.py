"""Offline regression: stream=True inside a running loop serves both callers.

Hermes relay calls iter() on the factory result without awaiting it; aux code awaits it.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CHUNK = {'id': 'x', 'object': 'chat.completion.chunk', 'created': 0, 'model': 'mistral-vibe-cli-latest',
         'choices': [{'index': 0, 'delta': {'content': 'ok'}, 'finish_reason': 'stop'}]}


def sse(_request):
    return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                          content='data: ' + json.dumps(CHUNK) + '\n\ndata: [DONE]\n\n')


class StreamTests(unittest.TestCase):
    def test_relay_iter_and_aux_await_both_work_in_running_loop(self):
        import vibe_provider as vp
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {
                'HERMES_HOME': home, 'MISTRAL_VIBE_API_KEY': 'fake'}), patch(
                'httpx.HTTPTransport', return_value=httpx.MockTransport(sse)):
            client = vp.GuardedClient(base_url=vp.BASE)

            async def run():
                relay = [c.choices[0].delta.content for c in iter(client.create(
                    model=vp.MODEL, messages=[], stream=True))]
                stream = await client.create(model=vp.MODEL, messages=[], stream=True)
                aux = [c.choices[0].delta.content async for c in stream]
                return relay, aux

            self.assertEqual(asyncio.run(run()), (['ok'], ['ok']))


if __name__ == '__main__':
    unittest.main()
