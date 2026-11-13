"""Offline tests for what the profile declares to Hermes: reasoning support and effort picker."""
import dataclasses
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import vibe_provider as vp

VERIFIED = vp._REASONING_MODEL_IDS
UNDECLARED = ('mistral-medium-3.5', 'mistral-vibe-cli-latest', 'mistral-large-latest',
              'mistral-small-latest', 'codestral-latest', 'magistral-medium-latest')
CONFIGS = [None, {'enabled': False}] + [{'enabled': True, 'effort': effort} for effort in
    ('minimal', 'low', 'medium', 'high', 'xhigh', 'max')]


def bare_profile():
    """The same profile without the declarations this change adds."""
    return dataclasses.replace(vp.profile, model_capabilities={}, setup_reasoning_efforts=None)


class DeclarationTests(unittest.TestCase):
    def test_only_relay_verified_models_are_declared_as_reasoning_capable(self):
        capabilities = vp.profile.model_capabilities
        self.assertEqual(set(capabilities), set(VERIFIED))
        for model in VERIFIED:
            with self.subTest(model=model):
                self.assertEqual(capabilities[model], {'supports_reasoning': True})
                self.assertIsNotNone(vp._relay_effort_set(model), 'declared without a verified vocabulary')
        for model in UNDECLARED:
            with self.subTest(model=model):
                self.assertNotIn(model, capabilities)
                self.assertIsNone(vp.profile.setup_reasoning_efforts(model))
        self.assertIsNone(vp.profile.setup_reasoning_efforts(None))

    def test_picker_levels_are_the_wire_levels_and_are_sent_verbatim(self):
        expected = {'mistral-large-4': ('low', 'medium', 'high'), 'zai-glm-5-3': ('low', 'high', 'max'),
                    'zai-glm-5-2': ('low', 'medium', 'high', 'max')}
        for model, levels in expected.items():
            self.assertEqual(vp.profile.setup_reasoning_efforts(model), levels)
        for model in VERIFIED:
            for level in vp.profile.setup_reasoning_efforts(model):
                with self.subTest(model=model, level=level):
                    _, top_level = vp.profile.build_api_kwargs_extras(
                        reasoning_config={'enabled': True, 'effort': level}, model=model)
                    self.assertEqual(top_level, {'reasoning_effort': level})

    def test_declarations_do_not_change_the_request(self):
        from agent.transports.chat_completions import ChatCompletionsTransport
        transport, messages, bare = ChatCompletionsTransport(), [{'role': 'user', 'content': 'test'}], bare_profile()
        for model in VERIFIED + UNDECLARED:
            for config in CONFIGS:
                with self.subTest(model=model, config=config):
                    declared = transport.build_kwargs(model, messages, provider_profile=vp.profile,
                        base_url=vp.BASE, reasoning_config=config)
                    plain = transport.build_kwargs(model, messages, provider_profile=bare,
                        base_url=vp.BASE, reasoning_config=config)
                    self.assertEqual(declared, plain)

    def test_declarations_do_not_add_a_default_effort(self):
        # Hermes sends a default effort only when the profile answers default_reasoning_config.
        from agent.reasoning_params import unset_reasoning_default
        from providers import register_provider
        register_provider(vp.profile)
        for model in VERIFIED + UNDECLARED:
            with self.subTest(model=model):
                agent = SimpleNamespace(api_mode='chat_completions', provider='mistral-vibe', model=model)
                self.assertIsNone(unset_reasoning_default(agent))

    def test_declarations_do_not_change_context_resolution_without_a_catalog(self):
        from agent.model_metadata import get_model_context_length
        from providers import register_provider
        seen = {}
        for label, profile in (('declared', vp.profile), ('bare', bare_profile())):
            register_provider(profile)
            with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HERMES_HOME': home}):
                os.environ.pop('MISTRAL_VIBE_API_KEY', None)
                seen[label] = {model: get_model_context_length(model, base_url=vp.BASE, provider='mistral-vibe')
                               for model in VERIFIED}
        register_provider(vp.profile)
        self.assertEqual(seen['declared'], seen['bare'])

    def test_hermes_reads_the_declaration(self):
        from agent.models_dev import get_model_capabilities
        from providers import register_provider
        register_provider(vp.profile)
        with tempfile.TemporaryDirectory() as home, patch.dict(os.environ, {'HERMES_HOME': home}):
            for model in VERIFIED:
                with self.subTest(model=model):
                    capabilities = get_model_capabilities('mistral-vibe', model)
                    self.assertIsNotNone(capabilities)
                    self.assertIs(capabilities.supports_reasoning, True)
            for model in UNDECLARED:
                with self.subTest(model=model):
                    capabilities = get_model_capabilities('mistral-vibe', model)
                    self.assertTrue(capabilities is None or capabilities.supports_reasoning is not True)

    def test_fields_an_older_hermes_lacks_are_not_passed(self):
        self.assertEqual(vp._hermes_profile_fields(names={'name', 'base_url'}), {})
        self.assertEqual(list(vp._hermes_profile_fields(names={'metadata_hostnames'})), ['metadata_hostnames'])
        everything = {'metadata_hostnames', 'model_capabilities', 'setup_reasoning_efforts'}
        self.assertEqual(set(vp._hermes_profile_fields(names=everything)), everything)
        self.assertEqual(set(vp._hermes_profile_fields()), set(vp._hermes_profile_fields(
            names={field.name for field in dataclasses.fields(type(vp.profile))})))


if __name__ == '__main__':
    unittest.main()
