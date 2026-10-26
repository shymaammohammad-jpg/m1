"""Gemini protocol and nine-stage regression tests; no live API or real keys."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import httpx
from backend.ai_provider import AIClient, AIProviderError, AISettingsStore, DEFAULTS
from backend.automation import AuditManager
from test_ai_provider import SCHEMA, image_data_url, ENVIRONMENT
import test_ai_workflow as workflow

KEY = 'synthetic-gemini-key'
OPENAI_KEY = 'synthetic-openai-key'
ENV = {**ENVIRONMENT, 'GEMINI_API_KEY': '', 'GEMINI_BASE_URL': ''}


def result(answer=None, finish='STOP'):
    return {'candidates': [{'finishReason': finish, 'content': {'parts': [
        {'text': json.dumps({'ok': True} if answer is None else answer)}]}}]}


def settings():
    return {'provider': 'gemini', **DEFAULTS['gemini'], 'api_key': KEY}


class GeminiTransportTests(unittest.TestCase):
    def test_native_protocol_schema_images_and_header_only_key(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=result())
        client = AIClient(settings(), transport=httpx.MockTransport(handler))
        self.assertEqual(client.complete('افحص', {'text': 'دليل اصطناعي'}, SCHEMA,
            images=[{'data_url': image_data_url()}]), {'ok': True})
        req = requests[0]; body = json.loads(req.content)
        self.assertEqual(str(req.url), 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent')
        self.assertEqual(req.headers['x-goog-api-key'], KEY)
        self.assertNotIn('Authorization', req.headers)
        self.assertNotIn(KEY, req.content.decode())
        self.assertEqual(body['generationConfig']['responseJsonSchema'], SCHEMA)
        self.assertEqual(body['generationConfig']['thinkingConfig'], {'thinkingBudget': 0})
        self.assertEqual(body['contents'][0]['parts'][1]['inlineData']['mimeType'], 'image/png')
        self.assertNotIn('candidateCount', body)
        self.assertEqual(body['generationConfig']['candidateCount'], 1)

    def test_partial_blocked_and_malformed_responses_never_become_success(self):
        cases = [(result(finish='MAX_TOKENS'), 'incomplete'),
                 (result(finish='SAFETY'), 'refusal'),
                 ({'promptFeedback': {'blockReason': 'SAFETY'}}, 'refusal'),
                 ({'candidates': []}, 'response'), ({'promptFeedback': []}, 'response'),
                 (result({'ok': 'wrong-type'}), 'schema')]
        for body, code in cases:
            with self.subTest(code=code):
                client = AIClient(settings(), max_attempts=1,
                    transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body)))
                with self.assertRaises(AIProviderError) as caught:
                    client.test_connection()
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn(KEY, str(caught.exception))

    def test_http_errors_are_sanitized_and_never_fall_back_to_another_service(self):
        for status, code, count in [(401, 'auth', 1), (403, 'auth', 1), (404, 'model_missing', 1),
                                     (429, 'rate_limit', 3), (503, 'network', 3), (302, 'network', 1)]:
            calls = []
            def handler(request):
                calls.append(request)
                return httpx.Response(status, json={'error': {'message': KEY}}, headers={'Location': 'https://evil.invalid'})
            with self.subTest(status=status):
                client = AIClient(settings(), transport=httpx.MockTransport(handler), sleep=lambda _: None)
                with self.assertRaises(AIProviderError) as caught:
                    client.test_connection()
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(len(calls), count)
                self.assertTrue(all(r.url.host == 'generativelanguage.googleapis.com' for r in calls))
                self.assertNotIn(KEY, str(caught.exception))

    def test_missing_key_stops_before_network(self):
        with self.assertRaises(AIProviderError) as caught:
            AIClient({**settings(), 'api_key': ''})
        self.assertEqual(caught.exception.code, 'not_configured')


class GeminiSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, ENV); self.env.start()
        self.store = AISettingsStore(Path(self.temp.name))
    def tearDown(self):
        self.env.stop(); self.temp.cleanup()

    def test_provider_keys_are_isolated_retained_and_clearable(self):
        self.store.update_settings({'provider': 'openai', 'api_key': OPENAI_KEY})
        public = self.store.update_settings({'provider': 'gemini'})
        self.assertFalse(public['configured'])
        self.assertEqual(self.store.settings_snapshot()['api_key'], '')
        public = self.store.update_settings({'api_key': KEY})
        self.assertTrue(public['configured']); self.assertTrue(public['supports_images'])
        self.assertNotIn(KEY, json.dumps(public)); self.assertNotIn(OPENAI_KEY, json.dumps(public))
        self.store.update_settings({'api_key': ''})
        self.assertEqual(self.store.settings_snapshot()['api_key'], KEY)
        self.store.update_settings({'provider': 'openai'})
        self.assertEqual(self.store.settings_snapshot()['api_key'], OPENAI_KEY)
        self.store.update_settings({'provider': 'gemini', 'clear_api_key': True})
        self.assertNotIn(KEY, self.store.path.read_text())
        self.store.update_settings({'provider': 'openai'})
        self.assertEqual(self.store.settings_snapshot()['api_key'], OPENAI_KEY)

    def test_environment_selects_only_the_correct_provider_key(self):
        self.store.update_settings({'provider': 'openai', 'api_key': OPENAI_KEY})
        with patch.dict(os.environ, {'AUDIT_AI_PROVIDER': 'gemini'}):
            self.assertFalse(self.store.public_settings()['configured'])
        with patch.dict(os.environ, {'AUDIT_AI_PROVIDER': 'gemini', 'GEMINI_API_KEY': KEY}):
            self.assertEqual(self.store.settings_snapshot()['api_key'], KEY)
            self.assertEqual(self.store.public_settings()['key_source'], 'environment')
            self.assertNotIn(KEY, json.dumps(self.store.public_settings()))
        self.assertNotIn(KEY, self.store.path.read_text())

    def test_old_openai_key_with_selected_ollama_is_not_sent_to_google(self):
        self.store.path.write_text(json.dumps({'provider': 'ollama', **DEFAULTS['ollama'], 'api_key': OPENAI_KEY}))
        self.assertFalse(self.store.update_settings({'provider': 'gemini'})['configured'])
        self.store.update_settings({'provider': 'openai'})
        self.assertEqual(self.store.settings_snapshot()['api_key'], OPENAI_KEY)

    def test_untrusted_urls_and_model_paths_are_rejected_before_write(self):
        for values in [{'base_url': 'https://generativelanguage.googleapis.com.evil.invalid/v1beta'},
                       {'base_url': 'http://generativelanguage.googleapis.com/v1beta'},
                       {'base_url': 'https://generativelanguage.googleapis.com/v1beta?key=secret'},
                       {'model': '../other'}, {'model': 'models/gemini-2.5-flash'}]:
            with self.subTest(values=values), self.assertRaises(AIProviderError):
                self.store.update_settings({'provider': 'gemini', **values})
        self.assertFalse(self.store.path.exists())


class GeminiWorkflowTests(unittest.TestCase):
    setUp = workflow.AutomatedAuditWorkflowTests.setUp
    tearDown = workflow.AutomatedAuditWorkflowTests.tearDown
    document = workflow.AutomatedAuditWorkflowTests.document
    extractor = workflow.AutomatedAuditWorkflowTests.extractor
    blacklist = workflow.AutomatedAuditWorkflowTests.blacklist

    def test_nine_stages_use_native_gemini_transport_and_verified_evidence(self):
        calls = []
        class StoreSettings:
            def settings_snapshot(self):
                return settings()
        def factory(snapshot):
            fake = workflow.FakeAI(snapshot)
            def handler(request):
                calls.append(request)
                wire = json.loads(request.content)
                data = json.loads(wire['contents'][0]['parts'][0]['text'])
                if data['task'] == 'connection_test':
                    return httpx.Response(200, json=result())
                answer = fake.complete(wire['systemInstruction']['parts'][0]['text'], data['data'],
                    wire['generationConfig']['responseJsonSchema'], task=data['task'])
                return httpx.Response(200, json=result(answer))
            return AIClient(snapshot, transport=httpx.MockTransport(handler))
        manager = AuditManager(self.store, StoreSettings(), client_factory=factory,
            extractor=self.extractor, blacklist_runner=self.blacklist, build_pdf=False)
        self.managers.append(manager)
        manager.start(self.case['id'])
        outcome = manager.wait(self.case['id'], timeout=30)
        self.assertEqual(outcome['job']['status'], 'completed', outcome['job'])
        self.assertEqual(outcome['job']['provider'], 'gemini')
        self.assertEqual(outcome['facts']['contract_number']['value'], 'SYNTH-001')
        self.assertEqual(len(outcome['job']['stages']), 9)
        self.assertTrue(calls)
        self.assertTrue(all(r.url.host == 'generativelanguage.googleapis.com' for r in calls))
        self.assertNotIn(KEY, json.dumps(outcome))


class GeminiCooldownTests(unittest.TestCase):
    def test_retry_after_is_respected_and_excessive_wait_stops(self):
        for cooldown, expected_calls, expected_delays in [('12', 3, [12, 12]), ('120', 1, [])]:
            calls, delays = [], []
            def handler(request):
                calls.append(1)
                return httpx.Response(429, headers={'Retry-After': cooldown})
            client = AIClient(settings(), transport=httpx.MockTransport(handler), sleep=delays.append)
            with self.assertRaises(AIProviderError) as caught:
                client.test_connection()
            self.assertEqual(caught.exception.code, 'rate_limit')
            self.assertEqual(len(calls), expected_calls)
            self.assertEqual(delays, expected_delays)
