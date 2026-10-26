"""Recovery invariants; synthetic responses do not measure model speed."""
from copy import deepcopy
import unittest
from backend.ai_provider import AIProviderError
from backend.automation import _map_with_recovery


class RecoveryTests(unittest.TestCase):
    def payload(self, text='أبجد' * 300):
        return {'pages': [{'document_id': 'synthetic', 'page': 12, 'text': text}], 'request': 'extract'}

    def test_overflow_retries_both_halves_and_preserves_page_and_original(self):
        payload = self.payload()
        original = deepcopy(payload)
        calls = []
        def ask(data, schema, task):
            calls.append(data)
            if len(calls) == 1:
                raise AIProviderError('truncated', 'incomplete')
            return {'facts': [{'value': 'same'}], 'documents': []}
        result = _map_with_recovery(ask, payload)
        self.assertEqual(len(calls), 3)
        self.assertEqual(result['facts'], [{'value': 'same'}])
        self.assertEqual(payload, original)
        halves = [c['pages'][0] for c in calls[1:]]
        self.assertTrue(all(p['page'] == 12 and p['document_id'] == 'synthetic' for p in halves))
        self.assertEqual(halves[0]['text'] + halves[1]['text'][200:], original['pages'][0]['text'])

    def test_multiple_pages_keep_all_sources(self):
        data = self.payload()
        data['pages'].append({**data['pages'][0], 'page': 13})
        seen = []
        def ask(payload, *_):
            if len(payload['pages']) > 1:
                raise AIProviderError('truncated', 'incomplete')
            seen.append(payload['pages'][0]['page'])
            return {'facts': [], 'documents': []}
        _map_with_recovery(ask, data)
        self.assertEqual(seen, [12, 13])

    def test_non_length_errors_and_short_packets_are_not_retried(self):
        for code, payload in [('schema', self.payload()), ('cancelled', self.payload()),
                              ('incomplete', self.payload('short'))]:
            calls = []
            def ask(*args):
                calls.append(1)
                raise AIProviderError('failure', code)
            with self.assertRaises(AIProviderError) as caught:
                _map_with_recovery(ask, payload)
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(len(calls), 1)

    def test_persistent_overflow_is_bounded_and_does_not_return_partial_results(self):
        calls = []
        def ask(*args):
            calls.append(1)
            raise AIProviderError('truncated', 'incomplete')
        with self.assertRaises(AIProviderError):
            _map_with_recovery(ask, self.payload('x' * 20000))
        self.assertEqual(len(calls), 4)


class LocalMemoryTests(unittest.TestCase):
    def test_context_grows_and_metrics_never_include_text(self):
        import json
        import httpx
        from backend.ai_provider import AIClient
        bodies = []
        def handler(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={'done': True, 'message': {'content': '{"ok":true}'},
                'eval_count': 4, 'eval_duration': 2000000000, 'load_duration': 'untrusted'})
        schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}},
                  'required': ['ok'], 'additionalProperties': False}
        client = AIClient({'provider': 'ollama'}, transport=httpx.MockTransport(handler))
        client.complete('check', {'text': 'a' * 5000}, schema)
        self.assertEqual(bodies[-1]['options']['num_ctx'], 16384)
        self.assertEqual(client.last_metrics, {'eval_count': 4, 'eval_duration': 2000000000})
        client.test_connection()
        self.assertEqual(bodies[-1]['options']['num_predict'], 128)
        self.assertEqual(bodies[-1]['options']['num_ctx'], 8192)
