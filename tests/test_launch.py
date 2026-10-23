"""Regression coverage for Explorer/direct-file launch and Windows time data."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request


ROOT = Path(__file__).resolve().parents[1]


class LaunchTests(unittest.TestCase):
    def test_partial_zip_has_extraction_guidance_instead_of_import_traceback(self):
        with tempfile.TemporaryDirectory(prefix="partial-zip-") as directory:
            script = Path(directory) / "m1-main.zip.temporary" / "backend" / "app.py"
            script.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / "backend/app.py", script)
            result = subprocess.run([sys.executable, str(script)], cwd=directory, capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Extract the ENTIRE ZIP", result.stderr)
        self.assertNotIn("attempted relative import", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_windows_timezone_fallback_works_without_system_iana_data(self):
        result = subprocess.run(
            [sys.executable, "-c", "from backend.audit_engine import instruction_policy; assert instruction_policy('2024-01-01')['instruction_year'] == 2014; print('tzdata available')"],
            cwd=ROOT, env={**os.environ, "PYTHONTZPATH": ""}, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("tzdata available", result.stdout)

    @unittest.skipUnless((ROOT / "frontend/dist/index.html").is_file(), "Build the frontend to test full application launch.")
    def test_launcher_and_direct_backend_file_start_from_unrelated_working_directory(self):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for entry in [ROOT / "run.py", ROOT / "backend/app.py"]:
            with self.subTest(entry=entry.name), tempfile.TemporaryDirectory(prefix="launch test ") as directory:
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1", 0))
                    port = probe.getsockname()[1]
                address = f"http://127.0.0.1:{port}"
                with tempfile.TemporaryFile() as output:
                    process = subprocess.Popen(
                        [sys.executable, str(entry), "--no-browser", "--port", str(port)],
                        cwd=directory,
                        env={**os.environ, "AUDIT_DATA_DIR": str(Path(directory) / "بيانات الاختبار"), "PYTHONTZPATH": "", "PYTHONUTF8": "1"},
                        stdout=output, stderr=subprocess.STDOUT,
                    )
                    try:
                        deadline = time.monotonic() + 20
                        healthy = False
                        while time.monotonic() < deadline and process.poll() is None:
                            try:
                                with opener.open(address + "/api/health", timeout=1) as response:
                                    healthy = json.load(response) == {"status": "ok"}
                                if healthy:
                                    break
                            except OSError:
                                time.sleep(0.1)
                        if not healthy:
                            output.seek(0)
                            self.fail(output.read().decode("utf-8", errors="replace"))
                        with opener.open(address + "/api/bootstrap", timeout=5) as response:
                            self.assertEqual(len(json.load(response)["checklist_template"]), 43)
                        with opener.open(address, timeout=5) as response:
                            self.assertIn("<html", response.read().decode().lower())
                        request = urllib.request.Request(
                            address + "/api/cases", data=json.dumps({"title": "اختبار المشغل", "contract_date": "2024-01-01"}).encode(),
                            headers={"Content-Type": "application/json"},
                        )
                        with opener.open(request, timeout=5) as response:
                            self.assertEqual(json.load(response)["instruction_year"], 2014)
                    finally:
                        if process.poll() is None:
                            process.terminate()
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
