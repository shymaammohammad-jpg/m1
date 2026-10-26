"""Production response restrictions; these are not antivirus verdicts."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend import app as service


class BrowserSecurityTests(unittest.TestCase):
    def test_frontend_restricts_scripts_connections_and_embedding(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'index.html').write_text('<!doctype html><html><body>synthetic</body></html>')
            with patch.object(service, 'FRONTEND', root):
                client=TestClient(service.app, follow_redirects=False)
                response=client.get('/')
                self.assertEqual(response.status_code,200)
                policy=response.headers['content-security-policy']
                self.assertIn("script-src 'self'",policy)
                self.assertIn("connect-src 'self'",policy)
                self.assertIn("object-src 'none'",policy)
                self.assertIn("base-uri 'none'",policy)
                self.assertNotIn("'unsafe-eval'",policy)
                self.assertIn("frame-ancestors 'self'",policy)
                self.assertEqual(response.headers['x-content-type-options'],'nosniff')
