"""Reasoning-effort contract: top-level wire field, relay-verified vocabularies.

The relay at https://api.mistral.ai/v1 validates a top-level ``reasoning_effort``
per model (HTTP 400 code 3051 lists the supported set — live-verified 2026-10-03):
zai-glm-5-3 / zai-glm-5 / zai-glm-latest accept low/high/max, zai-glm-5-2 also
accepts medium. Thinking cannot be disabled on this wire ('none' is rejected).
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import httpx

from vibe_provider import profile, MODEL, BASE, UA
from providers import register_provider


class ReasoningExtrasTests(unittest.TestCase):
    """build_api_kwargs_extras: clamp the requested effort onto the relay vocabulary."""

    def test_glm_5_3_clamps_unsupported_medium_to_low(self):
        extra_body, top_level = profile.build_api_kwargs_extras(
            reasoning_config={'enabled': True, 'effort': 'medium'}, model='zai-glm-5-3')
        self.assertEqual(extra_body, {})
        self.assertEqual(top_level, {'reasoning_effort': 'low'})

    def test_glm_5_3_supported_levels_pass_verbatim(self):
        for effort in ('low', 'high', 'max'):
            with self.subTest(effort=effort):
                _, top_level = profile.build_api_kwargs_extras(
                    reasoning_config={'enabled': True, 'effort': effort}, model='zai-glm-5-3')
                self.assertEqual(top_level, {'reasoning_effort': effort})

    def test_glm_5_2_keeps_medium_verbatim(self):
        for effort in ('low', 'medium', 'high', 'max'):
            with self.subTest(effort=effort):
                _, top_level = profile.build_api_kwargs_extras(
                    reasoning_config={'enabled': True, 'effort': effort}, model='zai-glm-5-2')
                self.assertEqual(top_level, {'reasoning_effort': effort})

    def test_clamping_never_escalates(self):
        # xhigh follows the vendor top-tier convention (mirrors GLM53_OVERRIDES in
        # agent.reasoning_effort: xhigh requests the top tier, consulted before
        # the nearest-weaker clamp); every other unsupported level weakens.
        cases = [('xhigh', 'max'), ('minimal', 'low'), ('ultra', 'max')]
        for requested, expected in cases:
            with self.subTest(requested=requested):
                _, top_level = profile.build_api_kwargs_extras(
                    reasoning_config={'enabled': True, 'effort': requested}, model='zai-glm-5-3')
                self.assertEqual(top_level, {'reasoning_effort': expected})

    def test_disabled_unset_or_none_emits_nothing(self):
        for config in ({'enabled': False, 'effort': 'high'}, None,
                       {'enabled': True, 'effort': 'none'}):
            with self.subTest(config=config):
                self.assertEqual(profile.build_api_kwargs_extras(
                    reasoning_config=config, model='zai-glm-5-3'), ({}, {}))

    def test_only_verified_glm_models_emit(self):
        """Fail-closed: non-GLM and unverified GLM versions keep the relay default."""
        for model in (MODEL, 'mistral-medium-latest', 'zai-glm-6', 'zai-glm-4-5', 'some-model'):
            with self.subTest(model=model):
                self.assertEqual(profile.build_api_kwargs_extras(
                    reasoning_config={'enabled': True, 'effort': 'medium'}, model=model), ({}, {}))

    def test_glm_5_and_latest_share_the_5_3_vocabulary(self):
        for model in ('zai-glm-5', 'zai-glm-latest', 'zai-glm-5-3-900k'):
            with self.subTest(model=model):
                _, top_level = profile.build_api_kwargs_extras(
                    reasoning_config={'enabled': True, 'effort': 'medium'}, model=model)
                self.assertEqual(top_level, {'reasoning_effort': 'low'})


class ReasoningWireTests(unittest.TestCase):
    """The full request path: transport kwargs and the guarded client's wire body."""

    def test_transport_puts_clamped_effort_at_top_level(self):
        from agent.transports.chat_completions import ChatCompletionsTransport
        register_provider(profile)
        kwargs = ChatCompletionsTransport().build_kwargs(
            model='zai-glm-5-3',
            messages=[{'role': 'user', 'content': 'ping'}],
            tools=None,
            provider_profile=profile,
            reasoning_config={'enabled': True, 'effort': 'medium'},
            base_url=BASE,
            provider_name='mistral-vibe',
        )
        self.assertEqual(kwargs.get('reasoning_effort'), 'low')
        self.assertNotIn('reasoning_effort', kwargs.get('extra_body') or {})

    def test_guarded_client_sends_top_level_effort_without_extra_body(self):
        """The guard rejects extra_body but must pass a top-level reasoning_effort."""
        bodies = []

        def fake(req):
            bodies.append(json.loads(req.content))
            self.assertEqual(str(req.url), BASE + '/chat/completions')
            return httpx.Response(200, json={'id': 'fake', 'object': 'chat.completion',
                'created': 0, 'model': 'zai-glm-5-3',
                'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'ok'},
                             'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})

        catalog = {'data': [{'id': 'zai-glm-5-3', 'capabilities': {'completion_chat': True}}]}
        responses = {BASE + '/models': catalog}

        def transport(req):
            if str(req.url) == BASE + '/models':
                return httpx.Response(200, json=responses[str(req.url)])
            return fake(req)

        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {
                'HERMES_HOME': home, 'MISTRAL_VIBE_API_KEY': 'fake-key'}), patch(
                'httpx.HTTPTransport', return_value=httpx.MockTransport(transport)):
            client = profile.create_client(base_url=BASE)
            result = client.chat.completions.create(
                model='zai-glm-5-3', messages=[{'role': 'user', 'content': 'hi'}],
                reasoning_effort='low')
            client.close()
        self.assertEqual(result.choices[0].message.content, 'ok')
        self.assertEqual(bodies[-1]['reasoning_effort'], 'low')
        self.assertEqual(bodies[-1]['model'], 'zai-glm-5-3')
        self.assertNotIn('extra_body', bodies[-1])
        self.assertNotIn('thinking', bodies[-1])


if __name__ == '__main__':
    unittest.main()
