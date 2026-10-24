"""One-time, local-only Ollama/OCR setup for the 8 GB Windows workstation.

Model and language downloads require Internet during setup. Audit requests go
only to the loopback Ollama server; this script never uploads source documents.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
MODEL = "qwen2.5:3b"
LOCAL_URL = "http://127.0.0.1:11434"
OLLAMA_DOWNLOAD = "https://ollama.com/download/windows"
TESSERACT_GUIDE = "https://github.com/UB-Mannheim/tesseract/wiki"
ARABIC_URL = (
    "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/"
    "87416418657359cb625c412a48b6e1d6d41c29bd/ara.traineddata"
)
ARABIC_SHA256 = "e3206d3dc87fd50c24a0fb9f01838615911d25168f4e64415244b67d2bb3e729"
MAX_LANGUAGE_BYTES = 20 * 1024 * 1024


class _NoLocalRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def _candidate_paths(name: str) -> list[Path]:
    values = []
    if name == "ollama":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            values += [Path(local) / "Programs/Ollama/ollama.exe", Path(local) / "Ollama/ollama.exe"]
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        directory = os.environ.get(variable)
        if directory:
            values.append(Path(directory) / ("Ollama/ollama.exe" if name == "ollama" else "Tesseract-OCR/tesseract.exe"))
    return values


def find_program(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    return next((str(path) for path in _candidate_paths(name) if path.is_file()), None)


def local_status() -> dict | None:
    # Never send local setup requests through an Internet/corporate proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoLocalRedirect())
    try:
        with opener.open(LOCAL_URL + "/api/tags", timeout=2) as response:
            if response.status != 200 or response.geturl() != LOCAL_URL + "/api/tags":
                return None
            body = response.read(1_000_001)
            if len(body) > 1_000_000:
                return None
            payload = json.loads(body)
            return payload if isinstance(payload, dict) and isinstance(payload.get("models"), list) else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def _local_environment() -> dict:
    return {**os.environ, "OLLAMA_HOST": LOCAL_URL,
            "OLLAMA_NUM_PARALLEL": "1", "OLLAMA_MAX_LOADED_MODELS": "1"}


def ensure_server(executable: str) -> dict:
    state = local_status()
    if state is not None:
        return state
    print("بدء Ollama على الحاسبة نفسها؛ اترك نافذة الخادم مفتوحة أثناء العمل.")
    options = {"env": _local_environment()}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    process = subprocess.Popen([executable, "serve"], **options)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        state = local_status()
        if state is not None:
            return state
        if process.poll() is not None:
            break
        time.sleep(.5)
    raise RuntimeError("تعذر تشغيل Ollama المحلي. افتح تطبيق Ollama ثم أعد إعداد الذكاء المحلي.")


def model_available(state: dict) -> bool:
    return any(isinstance(item, dict) and (item.get("name") == MODEL or item.get("model") == MODEL)
               for item in state.get("models", []))


def ensure_model(executable: str, state: dict, skip_download=False):
    if model_available(state):
        print("النموذج المحلي موجود: " + MODEL)
        return
    if skip_download:
        raise RuntimeError("لم يُنزّل النموذج المحلي بعد؛ شغّل الإعداد دون --skip-model-download.")
    print("تنزيل النموذج المحلي مرة واحدة: " + MODEL)
    print("التنزيل بحجم غيغابايت وقد يستغرق وقتًا. سيظهر تقدم Ollama في هذه النافذة.")
    result = subprocess.run([executable, "pull", MODEL], env=_local_environment(), check=False)
    if result.returncode:
        raise RuntimeError("لم يكتمل تنزيل النموذج. افحص اتصال الإنترنت ثم أعد الإعداد؛ لا تحتاج إعادة تنزيل الملفات المكتملة.")
    state = local_status()
    if state is None or not model_available(state):
        raise RuntimeError("لم يؤكد Ollama وجود النموذج بعد التنزيل؛ افتح Ollama وأعد المحاولة.")


def ensure_arabic_data(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "ara.traineddata"
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == ARABIC_SHA256:
        return
    temporary = None
    try:
        request = urllib.request.Request(ARABIC_URL, headers={"User-Agent": "RaqibLocalSetup/2.0"})
        with urllib.request.urlopen(request, timeout=45) as response:
            if response.geturl() != ARABIC_URL:
                raise RuntimeError("رفض تحويل تنزيل نموذج اللغة إلى مصدر غير مثبت.")
            with tempfile.NamedTemporaryFile(dir=folder, prefix=".ara-", delete=False) as stream:
                temporary = Path(stream.name)
                total = 0
                while block := response.read(256 * 1024):
                    total += len(block)
                    if total > MAX_LANGUAGE_BYTES:
                        raise RuntimeError("حجم نموذج اللغة يتجاوز الحد المسموح.")
                    stream.write(block)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != ARABIC_SHA256:
            raise RuntimeError("بصمة نموذج OCR العربي غير مطابقة؛ لم يُعتمد التنزيل.")
        os.replace(temporary, target)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def copy_english_data(executable: str, folder: Path) -> bool:
    target = folder / "eng.traineddata"
    if target.is_file():
        return True
    candidates = [Path(executable).resolve().parent / "tessdata/eng.traineddata",
                  Path("/usr/share/tesseract-ocr/5/tessdata/eng.traineddata")]
    source = next((path for path in candidates if path.is_file()), None)
    if source:
        shutil.copyfile(source, target)
        return True
    return False


def setup_ocr(data_dir: Path, *, no_browser=False, no_install_prompt=False) -> bool:
    executable = find_program("tesseract")
    if not executable:
        print("قراءة ملفات PDF والصور الممسوحة تحتاج Tesseract OCR محليًا.")
        print("على Windows يمكن تثبيته بالأمر: winget install --id UB-Mannheim.TesseractOCR -e --source winget")
        winget = shutil.which("winget") if os.name == "nt" else None
        if winget and not no_install_prompt and sys.stdin.isatty():
            answer = input("هل تريد تشغيل مثبت Tesseract الآن؟ اكتب y للموافقة أو Enter لتأجيله: ").strip().lower()
            if answer == "y":
                result = subprocess.run([winget, "install", "--id", "UB-Mannheim.TesseractOCR", "-e", "--source", "winget"], check=False)
                if result.returncode == 0:
                    executable = find_program("tesseract")
        if not executable and not no_browser:
            webbrowser.open(TESSERACT_GUIDE)
    print("تجهيز نموذج القراءة العربية مع التحقق من بصمته...")
    ensure_arabic_data(data_dir / "tessdata")
    if not executable:
        print("نموذج اللغة محفوظ، لكن محرك OCR لم يُثبت. أعد هذا الإعداد بعد تثبيته لقراءة المستندات المصورة.")
        return False
    if not copy_english_data(executable, data_dir / "tessdata"):
        print("ملف اللغة الإنجليزية غير متاح؛ أضفه إلى data/tessdata لقراءة الصفحات المختلطة.")
        return False
    result = subprocess.run([executable, "--list-langs", "--tessdata-dir", str(data_dir / "tessdata")],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, check=False)
    languages = set(result.stdout.split())
    if result.returncode or not {"ara", "eng"} <= languages:
        print("لم ينجح تحقق لغتي OCR العربية والإنجليزية؛ راجع التثبيت ثم أعد المحاولة.")
        return False
    print("القراءة المحلية للملفات الممسوحة جاهزة بالعربية والإنجليزية.")
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Prepare local Ollama and Arabic OCR for Raqib.")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-install-prompt", action="store_true")
    parser.add_argument("--skip-model-download", action="store_true")
    arguments = parser.parse_args(argv)
    data_dir = (arguments.data_dir or Path(os.environ.get("AUDIT_DATA_DIR", ROOT / "data"))).resolve()
    print("رقيب — إعداد الذكاء الاصطناعي المحلي لحاسبة بذاكرة 8 غيغابايت")
    print("تحتاج مرحلة الإعداد للإنترنت لتنزيل النموذج واللغة. معالجة مستندات العقد تجري على الحاسبة.")
    try:
        executable = find_program("ollama")
        if not executable:
            print("ثبّت Ollama لويندوز من: " + OLLAMA_DOWNLOAD)
            print("بعد اكتمال تثبيته أعد فتح setup_local_ai_windows.bat.")
            if not arguments.no_browser:
                webbrowser.open(OLLAMA_DOWNLOAD)
            return 3
        ensure_model(executable, ensure_server(executable), arguments.skip_model_download)
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from backend.ai_provider import AISettingsStore
        public = AISettingsStore(data_dir).update_settings({"provider": "ollama", "model": MODEL,
                                                          "base_url": LOCAL_URL, "clear_api_key": True})
        if public["provider"] != "ollama":
            raise RuntimeError("متغير AUDIT_AI_PROVIDER في الجهاز يغير المزود؛ أزله أو اجعله ollama قبل التشغيل.")
        ready = setup_ocr(data_dir, no_browser=arguments.no_browser, no_install_prompt=arguments.no_install_prompt)
        print("إعداد رقيب المحفوظ: Ollama / " + MODEL)
        print("شغّل start_windows.bat، ثم ارفع العقد والأوليات واضغط بدء التدقيق الآلي.")
        print("النموذج خفيف ونتائجه تحتاج قراءة الأدلة والتحفظات؛ لا يعني اكتمال المعالجة ضمان صحة العقد.")
        return 0 if ready else 2
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print("تعذر إكمال الإعداد المحلي: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
