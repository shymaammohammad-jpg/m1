"""Local setup tests use temporary files and fake processes, never installations."""
from contextlib import redirect_stdout, redirect_stderr
from io import BytesIO, StringIO
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import setup_local_ai as setup


class Download(BytesIO):
    def __init__(self, data, url=None):
        super().__init__(data)
        self.url = url or setup.ARABIC_URL

    def geturl(self):
        return self.url


class LocalSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="raqib-local-setup-test-")
        self.root = Path(self.temp.name)
        self.stdout = redirect_stdout(StringIO())
        self.stderr = redirect_stderr(StringIO())
        self.stdout.__enter__()
        self.stderr.__enter__()

    def tearDown(self):
        self.stderr.__exit__(None, None, None)
        self.stdout.__exit__(None, None, None)
        self.temp.cleanup()

    def test_finds_installed_ollama_outside_path(self):
        local = self.root / "LocalAppData"
        executable = local / "Programs/Ollama/ollama.exe"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"synthetic-test-only")
        with patch.dict(os.environ, {"LOCALAPPDATA": str(local)}), patch.object(setup.shutil, "which", return_value=None):
            self.assertEqual(setup.find_program("ollama"), str(executable))

    def test_local_requests_explicitly_ignore_proxies(self):
        opener = Mock()
        response = Download(b'{"models":[]}', setup.LOCAL_URL + "/api/tags")
        response.status = 200
        opener.open.return_value.__enter__ = Mock(return_value=response)
        opener.open.return_value.__exit__ = Mock(return_value=False)
        with patch.object(setup.urllib.request, "ProxyHandler", return_value="no-proxy") as proxy, \
                patch.object(setup.urllib.request, "build_opener", return_value=opener):
            self.assertEqual(setup.local_status(), {"models": []})
        proxy.assert_called_once_with({})
        opener.open.assert_called_once_with("http://127.0.0.1:11434/api/tags", timeout=2)

    def test_unrelated_local_http_response_is_not_ready(self):
        opener = Mock()
        response = Download(b'{"something":"else"}', setup.LOCAL_URL + "/api/tags")
        response.status = 200
        opener.open.return_value.__enter__ = Mock(return_value=response)
        opener.open.return_value.__exit__ = Mock(return_value=False)
        with patch.object(setup.urllib.request, "build_opener", return_value=opener):
            self.assertIsNone(setup.local_status())

    def test_local_http_redirects_are_never_followed(self):
        handler = setup._NoLocalRedirect()
        request = setup.urllib.request.Request(setup.LOCAL_URL + "/api/tags")
        self.assertIsNone(handler.redirect_request(request, None, 302, "redirect", {}, "https://outside.example"))
        self.assertIsNone(handler.redirect_request(request, None, 302, "redirect", {}, setup.LOCAL_URL + "/other"))

    def test_model_download_uses_only_fixed_loopback_host(self):
        with patch.dict(os.environ, {"OLLAMA_HOST": "https://untrusted.example"}), \
                patch.object(setup.subprocess, "run", return_value=Mock(returncode=0)) as run, \
                patch.object(setup, "local_status", return_value={"models": [{"name": setup.MODEL}]}):
            setup.ensure_model("/fake/ollama", {"models": []})
        command = run.call_args.args[0]
        self.assertEqual(command, ["/fake/ollama", "pull", "qwen2.5:3b"])
        self.assertEqual(run.call_args.kwargs["env"]["OLLAMA_HOST"], setup.LOCAL_URL)
        self.assertEqual(run.call_args.kwargs["env"]["OLLAMA_NUM_PARALLEL"], "1")
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_existing_model_does_not_download_again(self):
        with patch.object(setup.subprocess, "run") as run:
            setup.ensure_model("/fake/ollama", {"models": [{"name": setup.MODEL}]})
        run.assert_not_called()

    def test_skip_download_does_not_pretend_model_exists(self):
        with patch.object(setup.subprocess, "run") as run:
            with self.assertRaises(RuntimeError):
                setup.ensure_model("/fake/ollama", {"models": []}, skip_download=True)
        run.assert_not_called()

    def test_missing_ollama_opens_only_official_page_and_stops(self):
        with patch.object(setup, "find_program", return_value=None), \
                patch.object(setup.webbrowser, "open") as browser, \
                patch.object(setup, "ensure_arabic_data") as language:
            result = setup.main(["--data-dir", str(self.root / "data")])
        self.assertEqual(result, 3)
        browser.assert_called_once_with("https://ollama.com/download/windows")
        language.assert_not_called()
        self.assertFalse((self.root / "data/ai_settings.json").exists())

    def test_verified_language_cache_avoids_download(self):
        self.root.joinpath("ara.traineddata").write_bytes(b"synthetic-language")
        digest = hashlib.sha256(b"synthetic-language").hexdigest()
        with patch.object(setup, "ARABIC_SHA256", digest), patch.object(setup.urllib.request, "urlopen") as request:
            setup.ensure_arabic_data(self.root)
        request.assert_not_called()

    def test_language_hash_failure_preserves_existing_file(self):
        target = self.root / "ara.traineddata"
        target.write_bytes(b"previous-language")
        with patch.object(setup.urllib.request, "urlopen", return_value=Download(b"untrusted-content")):
            with self.assertRaisesRegex(RuntimeError, "بصمة"):
                setup.ensure_arabic_data(self.root)
        self.assertEqual(target.read_bytes(), b"previous-language")
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["ara.traineddata"])

    def test_language_unexpected_redirect_is_rejected(self):
        with patch.object(setup.urllib.request, "urlopen", return_value=Download(b"content", "https://other.example/model")):
            with self.assertRaisesRegex(RuntimeError, "تحويل"):
                setup.ensure_arabic_data(self.root)
        self.assertFalse((self.root / "ara.traineddata").exists())

    def test_language_verified_atomic_write(self):
        content = b"synthetic-verified-language-data"
        with patch.object(setup, "ARABIC_SHA256", hashlib.sha256(content).hexdigest()), \
                patch.object(setup.urllib.request, "urlopen", return_value=Download(content)):
            setup.ensure_arabic_data(self.root)
        self.assertEqual((self.root / "ara.traineddata").read_bytes(), content)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["ara.traineddata"])

    def test_language_size_is_bounded(self):
        with patch.object(setup, "MAX_LANGUAGE_BYTES", 4), \
                patch.object(setup.urllib.request, "urlopen", return_value=Download(b"too-many-bytes")):
            with self.assertRaisesRegex(RuntimeError, "حجم"):
                setup.ensure_arabic_data(self.root)

    def test_main_persists_local_settings_without_cloud_key(self):
        data = self.root / "data"
        data.mkdir()
        (data / "ai_settings.json").write_text(json.dumps({"provider": "openai", "model": "gpt-5.2", "base_url": "https://api.openai.com/v1", "api_key": "synthetic-old-secret"}))
        with patch.dict(os.environ, {"AUDIT_AI_PROVIDER": "", "AUDIT_AI_MODEL": "", "OPENAI_API_KEY": "", "OLLAMA_HOST": ""}), \
                patch.object(setup, "find_program", return_value="/fake/ollama"), \
                patch.object(setup, "ensure_server", return_value={"models": [{"name": setup.MODEL}]}), \
                patch.object(setup, "ensure_model") as model, \
                patch.object(setup, "setup_ocr", return_value=True):
            result = setup.main(["--data-dir", str(data), "--no-browser", "--no-install-prompt"])
        self.assertEqual(result, 0)
        stored = json.loads((data / "ai_settings.json").read_text())
        self.assertEqual(stored["provider"], "ollama")
        self.assertEqual(stored["model"], "qwen2.5:3b")
        self.assertEqual(stored["base_url"], setup.LOCAL_URL)
        self.assertEqual(stored["api_key"], "")

    def test_ocr_missing_does_not_report_full_readiness(self):
        with patch.object(setup, "find_program", return_value=None), \
                patch.object(setup, "ensure_arabic_data") as language, \
                patch.object(setup.webbrowser, "open") as browser:
            self.assertFalse(setup.setup_ocr(self.root, no_browser=True, no_install_prompt=True))
        language.assert_called_once_with(self.root / "tessdata")
        browser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
