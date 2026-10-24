"""Page-addressable local extraction and evidence retrieval for automated audits.

Reading a page is not a legal finding. ``complete`` records extraction coverage,
not correctness of OCR or completeness of an uploaded contract dossier. Word and
text files have logical sections, explicitly distinguished from PDF page numbers.
Uploaded text is data throughout this module; it is never executed.
"""
from __future__ import annotations

from collections import Counter
import base64
import csv
import hashlib
import io
from importlib import metadata as package_metadata
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
from xml.etree import ElementTree
import zipfile

from .extraction import MAX_EXPANDED, MAX_UPLOAD

EXTRACTOR_VERSION = "raqib-pages-1"
MAX_PAGE_TEXT = 100_000
MAX_DOCUMENT_TEXT = 4_000_000
LOGICAL_SECTION_CHARS = 12_000
DOCUMENT_TIMEOUT_SECONDS = 600
MAX_IMAGE_PIXELS = 40_000_000
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".webp"}
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_LETTERS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي",
                              "٫": ".", "٬": ",", "،": ",", "−": "-"})
_BIDI = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_STOPWORDS = {"في", "من", "على", "عن", "الى", "الي", "و", "او", "ان", "التي", "الذي", "هذا", "هذه",
              "هو", "هي", "مع", "كل", "ما", "تم", "يتم", "كما", "لا", "عند", "بين", "بعد", "قبل"}


def normalize_quote(value: str) -> str:
    """Normalize orthography/spacing without dropping signs or numeric separators."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = _BIDI.sub("", text).translate(_DIGITS).translate(_LETTERS)
    text = "".join(c for c in text if c != "ـ" and unicodedata.category(c) != "Mn")
    return " ".join(text.split()).casefold()


def quote_exists(quote: str, text: str, min_length: int = 12) -> bool:
    """Exact normalized containment; short/common fragments are not evidence."""
    needle = normalize_quote(quote)
    return (sum(c.isalnum() for c in needle) >= max(1, int(min_length))
            and needle in normalize_quote(text))


def _tokens(text: str) -> list[str]:
    values = re.findall(r"[^\W_]+", normalize_quote(text), re.UNICODE)
    return [token[2:] if token.startswith("ال") and len(token) > 5 else token
            for token in values if len(token) > 1 and token not in _STOPWORDS]


def _readability(text: str) -> float:
    content = [c for c in text if not c.isspace()]
    if not content:
        return 0.0
    acceptable = sum(c.isalnum() or unicodedata.category(c).startswith(("P", "S")) for c in content)
    return round(acceptable / len(content), 3)


def _notify(progress, document_id: str, page: int, page_count: int, method: str):
    if progress:
        progress({"document_id": document_id, "page": page, "page_count": page_count, "method": method})


def _remaining(deadline: float, maximum: float) -> float:
    seconds = min(maximum, deadline - time.monotonic())
    if seconds <= 0:
        raise TimeoutError("انتهت مهلة قراءة المستند")
    return seconds


def _ocr_image(image: Path, folder: Path, deadline: float) -> tuple[str, float | None]:
    executable = shutil.which("tesseract")
    if not executable:
        raise RuntimeError("محرك OCR غير مثبت؛ يلزم Tesseract مع اللغتين العربية والإنكليزية")
    prefix = folder / "ocr"
    args = [executable, str(image), str(prefix), "-l", "ara+eng", "--psm", "3"]
    tessdata = os.environ.get("AUDIT_TESSDATA_DIR")
    if tessdata:
        args += ["--tessdata-dir", tessdata]
    args += ["txt", "tsv"]
    process = subprocess.run(args, capture_output=True, timeout=_remaining(deadline, 60),
                             env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    text_path, tsv_path = prefix.with_suffix(".txt"), prefix.with_suffix(".tsv")
    if process.returncode or not text_path.is_file():
        raise RuntimeError("تعذر OCR؛ تحقق من تثبيت ملفات اللغة العربية والإنكليزية وسلامة الصورة")
    text = text_path.read_text("utf-8", errors="replace")[:MAX_PAGE_TEXT + 1]
    weighted, weight = 0.0, 0
    if tsv_path.is_file() and tsv_path.stat().st_size < 20_000_000:
        for row in csv.DictReader(io.StringIO(tsv_path.read_text("utf-8", errors="replace")), delimiter="\t"):
            try:
                confidence = float(row.get("conf", -1))
            except (ValueError, TypeError):
                continue
            token = str(row.get("text") or "").strip()
            if token and 0 <= confidence <= 100:
                n = len(token)
                weighted += confidence * n
                weight += n
    return text, round(weighted / (100 * weight), 3) if weight else None


def _pdf_has_images(page) -> bool:
    """Inspect resource dictionaries, without decoding potentially large images."""
    seen: set[int] = set()

    def visit(resources, depth=0):
        if depth > 3 or resources is None:
            return False
        resources = resources.get_object()
        objects = resources.get("/XObject")
        if not objects:
            return False
        for indirect in list(objects.get_object().values())[:100]:
            obj = indirect.get_object()
            if id(obj) in seen:
                continue
            seen.add(id(obj))
            if obj.get("/Subtype") == "/Image":
                return True
            if obj.get("/Subtype") == "/Form" and visit(obj.get("/Resources"), depth + 1):
                return True
        return False

    return visit(page.get("/Resources"))


def _pdf_ocr(path: Path, page_number: int, folder: Path, deadline: float) -> tuple[str, float | None]:
    image = _render_pdf_page(path, page_number, folder, 2400, deadline)
    return _ocr_image(image, folder, deadline)


def _render_pdf_page(path: Path, page_number: int, folder: Path, max_dimension: int,
                     deadline: float | None = None) -> Path:
    """Use the packaged PDFium wheel on Windows, or installed Poppler elsewhere."""
    image_path = folder / "page.png"
    try:
        import pypdfium2 as pdfium
    except ImportError:
        pdfium = None
    if pdfium is not None:
        pdf = pdfium.PdfDocument(str(path))
        try:
            if not 1 <= page_number <= len(pdf):
                raise ValueError("رقم الصفحة خارج حدود المستند")
            page = pdf[page_number - 1]
            try:
                width, height = page.get_size()
                if width <= 0 or height <= 0:
                    raise ValueError("أبعاد صفحة PDF غير صالحة")
                scale = min(4.0, max_dimension / max(width, height))
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil()
                    image.save(image_path, format="PNG")
                finally:
                    bitmap.close()
            finally:
                page.close()
        finally:
            pdf.close()
        return image_path
    executable = shutil.which("pdftoppm")
    if not executable:
        raise RuntimeError("تحويل صفحات PDF إلى صور غير متاح؛ ثبّت pypdfium2 أو Poppler لقراءة الصفحات الممسوحة")
    prefix = folder / "page"
    process = subprocess.run([executable, "-f", str(page_number), "-l", str(page_number), "-singlefile",
                              "-r", "170", "-scale-to", str(max_dimension), "-png", str(path), str(prefix)],
                             capture_output=True, timeout=_remaining(deadline, 40) if deadline else 40)
    image = prefix.with_suffix(".png")
    if process.returncode or not image.is_file():
        raise RuntimeError("تعذر تحويل صفحة PDF إلى صورة للقراءة")
    return image


def render_document_page(document: dict, page: int, max_dimension: int = 2200) -> dict:
    """Return one bounded local PDF/image page for an explicitly configured vision client.

    This function has no network access and creates no provider uploads. The caller
    decides whether any returned image is sent to its configured AI service.
    """
    from PIL import Image
    path = Path(document.get("_path") or "")
    if not document.get("_path") or not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_UPLOAD:
        raise ValueError("أصل المستند غير متاح أو يتجاوز حدود العرض")
    if document.get("sha256"):
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != document["sha256"]:
                raise ValueError("بصمة الأصل تغيرت؛ تعذر عرض صفحة موثوقة")
    page = int(page)
    max_dimension = min(3000, max(256, int(max_dimension)))
    extension = Path(document.get("original_name") or path.name).suffix.lower()
    try:
        with tempfile.TemporaryDirectory(prefix="raqib-ai-vision-") as temp:
            if extension == ".pdf":
                from pypdf import PdfReader
                reader = PdfReader(str(path), strict=False)
                if reader.is_encrypted and not reader.decrypt(""):
                    raise ValueError("ملف PDF محمي بكلمة مرور")
                if not 1 <= page <= len(reader.pages):
                    raise ValueError("رقم الصفحة خارج حدود المستند")
                image_path = _render_pdf_page(path, page, Path(temp), max_dimension)
                with Image.open(image_path) as original:
                    image = original.convert("RGB")
            elif extension in IMAGE_EXTENSIONS:
                with Image.open(path) as original:
                    if not 1 <= page <= int(getattr(original, "n_frames", 1)):
                        raise ValueError("رقم إطار الصورة خارج حدود المستند")
                    original.seek(page - 1)
                    if original.width * original.height > MAX_IMAGE_PIXELS:
                        raise ValueError("أبعاد الصورة تتجاوز الحد المسموح")
                    image = original.convert("RGB")
            else:
                raise ValueError("عرض الرؤية يدعم صفحات PDF والصور؛ ترقيم Word منطقي ولا يمثل صورة صفحة")
            image.thumbnail((max_dimension, max_dimension))
            output = io.BytesIO()
            image.save(output, format="PNG")
            content, media_type = output.getvalue(), "image/png"
            if len(content) > 8 * 1024 * 1024:
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=90)
                content, media_type = output.getvalue(), "image/jpeg"
            image.close()
            if len(content) > 10 * 1024 * 1024:
                raise ValueError("حجم صورة الصفحة يتجاوز حد الرؤية")
            return {"page": page, "data_url": f"data:{media_type};base64," + base64.b64encode(content).decode("ascii")}
    except (ValueError, RuntimeError):
        raise
    except Exception as exc:
        raise RuntimeError("تعذر عرض الصفحة للرؤية؛ تحقق من تثبيت pypdfium2 أو Poppler وسلامة الأصل") from exc


def _decode_text(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16")
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1256")
    if "\x00" in text or sum(ord(c) < 32 and c not in "\r\n\t\f" for c in text) > max(2, len(text) * .02):
        raise ValueError("الملف النصي يحتوي بيانات ثنائية غير صالحة للقراءة")
    return text


def extract_document_pages(document: dict, *, progress=None, max_pages: int = 300, cancelled=None) -> dict:
    """Read every source page within explicit limits, preserving all coverage gaps.

    ``progress`` receives a dictionary after each visited page. ``cancelled`` is a
    callable returning a bool. Neither callback receives source filesystem paths.
    Native PDF text and image text are both inspected, including mixed PDFs.
    """
    max_pages = min(1000, max(1, int(max_pages)))
    result = {"document_id": str(document.get("id", "")), "name": document.get("name", "مستند"),
              "category": document.get("category", "supporting"), "sha256": "",
              "page_count": 0, "pages": [], "complete": False, "warnings": [],
              "unreadable_pages": [], "unprocessed_pages": [], "truncated": False,
              "cancelled": False, "pagination": "physical", "integrity_verified": False,
              "quality_note": "درجة جودة استخراج النص أو ثقة OCR ليست احتمال صحة النتيجة القانونية"}
    warnings = result["warnings"]
    path = Path(document.get("_path") or "")
    if not document.get("_path") or not path.is_file() or path.is_symlink():
        warnings.append("أصل المستند غير متاح للقراءة؛ لا يُستخدم نص مخزن جزئياً بديلاً عن الأصل")
        return result
    if path.stat().st_size > MAX_UPLOAD:
        warnings.append("حجم المستند يتجاوز الحد المسموح للقراءة")
        return result
    with path.open("rb") as source:
        result["sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
    if document.get("sha256") and result["sha256"] != document["sha256"]:
        warnings.append("بصمة أصل المستند لا تطابق البصمة المحفوظة؛ يلزم إعادة رفعه")
        return result
    result["integrity_verified"] = True
    extension = Path(document.get("original_name") or path.name).suffix.lower()
    deadline = time.monotonic() + DOCUMENT_TIMEOUT_SECONDS
    used_characters = 0
    unreadable: set[int] = set()

    def stop() -> bool:
        if cancelled and cancelled():
            result["cancelled"] = True
            return True
        if time.monotonic() >= deadline or used_characters >= MAX_DOCUMENT_TEXT:
            result["truncated"] = True
            return True
        return False

    def append(number, text, method, quality=None, *, bad=False):
        nonlocal used_characters
        available = max(0, min(MAX_PAGE_TEXT, MAX_DOCUMENT_TEXT - used_characters))
        clipped = len(text) > available
        text = text[:available]
        if clipped:
            result["truncated"] = True
        used_characters += len(text)
        page = {"page": number, "text": text, "method": method,
                "quality": quality if quality is not None else _readability(text),
                "quality_metric": "ocr_word_confidence" if "ocr" in method and quality is not None else "character_readability",
                "truncated": clipped, "pagination": result["pagination"]}
        result["pages"].append(page)
        if bad:
            unreadable.add(number)
        _notify(progress, result["document_id"], number, result["page_count"], method)

    def logical_text(text: str):
        result["pagination"] = "logical"
        # Split at a nearby line boundary; these are sections, not Word print pages.
        chunks = []
        offset = 0
        while offset < len(text):
            end = min(offset + LOGICAL_SECTION_CHARS, len(text))
            if end < len(text):
                newline = text.rfind("\n", max(offset, end - 1000), end)
                if newline > offset:
                    end = newline + 1
            chunks.append(text[offset:end])
            offset = end
        result["page_count"] = max(1, len(chunks))
        for number, chunk in enumerate(chunks or [""], 1):
            if number > max_pages or stop():
                break
            append(number, chunk, "text", bad=not bool(chunk.strip()))
        warnings.append("الترقيم مقاطع نصية منطقية، وليس أرقام صفحات الطباعة؛ راجع الأصل عند الإحالة إلى صفحة Word أو ملف نصي")

    try:
        if extension == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(path), strict=False)
            if reader.is_encrypted and not reader.decrypt(""):
                raise ValueError("ملف PDF محمي بكلمة مرور")
            result["page_count"] = len(reader.pages)
            for index in range(min(result["page_count"], max_pages)):
                if stop():
                    break
                number, page = index + 1, reader.pages[index]
                text, native_error = "", False
                try:
                    text = page.extract_text() or ""
                    images = _pdf_has_images(page)
                    has_content = bool(page.get("/Contents"))
                except Exception:
                    images, has_content, native_error = True, True, True
                needs_ocr = images or native_error or (not text.strip() and has_content)
                if not needs_ocr:
                    append(number, text, "text" if text.strip() else "blank")
                    continue
                try:
                    with tempfile.TemporaryDirectory(prefix="raqib-ai-ocr-") as temp:
                        ocr, confidence = _pdf_ocr(path, number, Path(temp), deadline)
                    combined = text
                    if ocr.strip() and normalize_quote(ocr) not in normalize_quote(text):
                        combined = text + ("\n\n" if text.strip() else "") + ocr
                    bad = not combined.strip() or confidence is not None and confidence < .35
                    append(number, combined, "text+ocr" if text.strip() else "ocr", confidence, bad=bad)
                    if bad:
                        warnings.append(f"قراءة الصفحة {number} ضعيفة أو فارغة؛ لا تكفي لإثبات الامتثال")
                except Exception as exc:
                    append(number, text, "text_partial" if text.strip() else "unreadable", bad=True)
                    message = str(exc) if type(exc) in {RuntimeError, TimeoutError} else "تعذرت القراءة الضوئية ضمن المهلة المحددة"
                    warnings.append(f"الصفحة {number}: {message}")
        elif extension in {".txt", ".csv", ".json"}:
            logical_text(_decode_text(path.read_bytes()))
        elif extension == ".docx":
            from docx import Document
            from docx.table import Table
            from docx.text.paragraph import Paragraph
            with zipfile.ZipFile(path) as archive:
                members = archive.infolist()
                if len(members) > 3000 or sum(i.file_size for i in members) > MAX_EXPANDED:
                    raise ValueError("حجم محتوى Word بعد فك الضغط يتجاوز الحد المسموح")
                media = [m for m in members if m.filename.startswith("word/media/") and not m.is_dir()]
                doc = Document(str(path))
                pieces = []

                def table_rows(table):
                    def cell_text(cell):
                        return "\n".join(part.text if isinstance(part, Paragraph) else "\n".join(table_rows(part))
                                         for part in cell.iter_inner_content())
                    return [" | ".join(cell_text(cell) for cell in row.cells) for row in table.rows]

                for item in doc.iter_inner_content():
                    if isinstance(item, Paragraph):
                        pieces.append(item.text)
                    elif isinstance(item, Table):
                        pieces.extend(table_rows(item))
                seen_headers = set()
                for section in doc.sections:
                    for part in (section.header, section.footer, section.first_page_header, section.first_page_footer,
                                 section.even_page_header, section.even_page_footer):
                        fragment = "\n".join(p.text for p in part.paragraphs)
                        fragment += "\n" + "\n".join(row for table in part.tables for row in table_rows(table))
                        if fragment.strip() and fragment not in seen_headers:
                            pieces.append(fragment)
                            seen_headers.add(fragment)
                complex_parts = any(m.filename in {"word/footnotes.xml", "word/endnotes.xml", "word/comments.xml"}
                                    for m in members)
                xml_body = ElementTree.fromstring(archive.read("word/document.xml"))
                complex_parts |= any(e.tag.rsplit("}", 1)[-1] in {"txbxContent", "altChunk", "del", "moveFrom", "sdt"}
                                     for e in xml_body.iter())
                if complex_parts:
                    result["truncated"] = True
                    warnings.append("يتضمن Word حواشي أو تعليقات أو مربعات نص أو تعديلات متعقبة؛ القراءة الحالية لا تثبت جميع أجزائه أو نسخته النهائية، ويُفضّل رفع PDF مكتمل")
                # Read embedded image text too, while keeping pagination explicitly logical.
                for number, member in enumerate(media, 1):
                    if stop():
                        warnings.append("لم تُستكمل قراءة صور Word بسبب حدود الوقت")
                        break
                    try:
                        from PIL import Image
                        data = archive.read(member)
                        with Image.open(io.BytesIO(data)) as image:
                            if image.width * image.height > MAX_IMAGE_PIXELS:
                                raise ValueError("أبعاد صورة Word كبيرة جداً")
                            with tempfile.TemporaryDirectory(prefix="raqib-ai-docx-") as temp:
                                image_path = Path(temp) / "image.png"
                                image.convert("RGB").save(image_path)
                                text, confidence = _ocr_image(image_path, Path(temp), deadline)
                        if not text.strip() or confidence is not None and confidence < .35:
                            raise ValueError("النص الضوئي لصورة Word غير مقروء بثقة كافية")
                        pieces.append(text)
                    except Exception:
                        warnings.append(f"تعذرت قراءة الصورة {number} داخل Word؛ قد تتضمن أدلة لم تُستخرج")
                        result["truncated"] = True
                logical_text("\n".join(pieces))
                if media:
                    result["contains_ocr"] = True
                    for page in result["pages"]:
                        page["method"] = "text+ocr"
        elif extension in IMAGE_EXTENSIONS:
            from PIL import Image
            with Image.open(path) as image:
                result["page_count"] = int(getattr(image, "n_frames", 1))
                for index in range(min(result["page_count"], max_pages)):
                    if stop():
                        break
                    try:
                        image.seek(index)
                        if image.width * image.height > MAX_IMAGE_PIXELS:
                            raise ValueError("أبعاد الصورة تتجاوز 40 مليون بكسل")
                        with tempfile.TemporaryDirectory(prefix="raqib-ai-image-") as temp:
                            image_path = Path(temp) / "image.png"
                            image.convert("RGB").save(image_path)
                            text, confidence = _ocr_image(image_path, Path(temp), deadline)
                        bad = not text.strip() or confidence is not None and confidence < .35
                        append(index + 1, text, "ocr", confidence, bad=bad)
                    except Exception:
                        append(index + 1, "", "unreadable", bad=True)
                        warnings.append(f"تعذر OCR للصورة / الإطار {index + 1}")
        else:
            warnings.append("نوع الملف غير مدعوم للقراءة الآلية")
            return result
    except Exception as exc:
        warnings.append(str(exc) if isinstance(exc, ValueError) else "تعذرت قراءة أصل المستند؛ لا يمكن اعتباره مفحوصاً بالكامل")

    visited = {p["page"] for p in result["pages"]}
    unprocessed = set(range(1, result["page_count"] + 1)) - visited
    result["unprocessed_pages"] = sorted(unprocessed)
    if unprocessed:
        result["truncated"] = True
        unreadable |= unprocessed
    if result["truncated"]:
        warnings.append("القراءة غير مكتملة بسبب حدود الصفحات أو الحروف أو الوقت؛ لم تُراجع الأجزاء المحذوفة")
    if result["cancelled"]:
        warnings.append("أُلغيت القراءة قبل اكتمال المستند")
    if not any(p["text"].strip() for p in result["pages"]):
        warnings.append("لم يُستخرج نص قابل للفحص من المستند")
    result["unreadable_pages"] = sorted(unreadable)
    result["complete"] = bool(result["pages"] and any(p["text"].strip() for p in result["pages"])
                              and not unreadable and not result["truncated"] and not result["cancelled"])
    result["warnings"] = list(dict.fromkeys(warnings))
    return result


def _cache_key(document: dict, max_pages: int) -> str | None:
    path = Path(document.get("_path") or "")
    if not document.get("_path") or not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_UPLOAD:
        return None
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if document.get("sha256") and digest != document["sha256"]:
        return None
    tools = {}
    for command in ("tesseract", "pdftoppm"):
        executable = shutil.which(command)
        tools[command] = (executable, Path(executable).stat().st_mtime_ns if executable else None)
    try:
        tools["pypdfium2"] = package_metadata.version("pypdfium2")
    except package_metadata.PackageNotFoundError:
        tools["pypdfium2"] = None
    tessdata = os.environ.get("AUDIT_TESSDATA_DIR", "")
    models = {}
    for language in ("ara", "eng"):
        model = Path(tessdata) / f"{language}.traineddata" if tessdata else None
        models[language] = (model.stat().st_size, model.stat().st_mtime_ns) if model and model.is_file() else None
    settings = {"version": EXTRACTOR_VERSION, "sha256": digest, "max_pages": max_pages,
                "page_chars": MAX_PAGE_TEXT, "document_chars": MAX_DOCUMENT_TEXT,
                "extension": Path(document.get("original_name") or path.name).suffix.lower(),
                "tessdata": tessdata, "models": models, "tools": tools}
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()


def cached_extract_document(document: dict, cache_dir: Path, **kwargs) -> dict:
    """Reuse only complete extractions; retry failures after OCR/tools are fixed."""
    if kwargs.get("cancelled") and kwargs["cancelled"]():
        return extract_document_pages(document, **kwargs)
    key = _cache_key(document, min(1000, max(1, int(kwargs.get("max_pages", 300)))))
    cache_dir = Path(cache_dir)
    target = cache_dir / f"{key}.json" if key else None
    if target and target.is_file() and target.stat().st_size <= MAX_DOCUMENT_TEXT * 6 + 1_000_000:
        try:
            cached = json.loads(target.read_text("utf-8"))
            if isinstance(cached, dict) and cached.get("complete") and cached.get("pages") and sum(len(p["text"]) for p in cached["pages"]) <= MAX_DOCUMENT_TEXT:
                cached.update(document_id=str(document.get("id", "")), name=document.get("name", "مستند"),
                              category=document.get("category", "supporting"), cached=True)
                _notify(kwargs.get("progress"), cached["document_id"], cached["page_count"], cached["page_count"], "cache")
                return cached
        except (OSError, ValueError, TypeError, KeyError):
            pass
    result = extract_document_pages(document, **kwargs)
    if target and result["complete"]:
        cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", dir=cache_dir, prefix=".pages-", suffix=".tmp",
                                             encoding="utf-8", delete=False) as file:
                temporary = Path(file.name)
                json.dump(result, file, ensure_ascii=False)
            temporary.chmod(0o600)
            os.replace(temporary, target)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
    return result


def page_lookup(documents: list[dict]) -> dict[tuple[str, int], dict]:
    """Full source-page index for validating citations, never retrieval excerpts."""
    return {(str(doc.get("document_id", doc.get("id", ""))), int(page["page"])): page
            for doc in documents for page in doc.get("pages", []) if page.get("page")}


def _excerpt(text: str, query_tokens: list[str], budget: int) -> str:
    if len(text) <= budget:
        return text
    # Find an exact source token; normalizing is only for ranking, not for quoting.
    positions = [m.start() for token in query_tokens for m in list(re.finditer(re.escape(token), text, re.IGNORECASE))[:8]]
    center = min(positions) if positions else 0
    start = max(0, min(len(text) - budget, center - budget // 3))
    return text[start:start + budget]


def retrieve_pages(documents: list[dict], query: str, *, limit: int = 12, max_chars: int = 40_000) -> list[dict]:
    """Deterministic lexical retrieval with contract/supporting/reference coverage.

    Returned text may be a contiguous excerpt. Validate quotations against
    ``page_lookup(documents)``, and do not mistake retrieved pages for full review.
    """
    limit, max_chars = max(0, min(int(limit), 100)), max(0, min(int(max_chars), 500_000))
    if not limit or not max_chars:
        return []
    query_tokens = list(dict.fromkeys(_tokens(query)))[:300]
    candidates = []
    frequencies: Counter = Counter()
    for index, document in enumerate(documents):
        for page in document.get("pages", []):
            text = page.get("text", "")
            if not isinstance(text, str) or not text.strip():
                continue
            tokens = Counter(_tokens(text))
            frequencies.update(set(tokens))
            candidates.append({"document_id": str(document.get("document_id", document.get("id", ""))),
                               "name": document.get("name", ""), "category": document.get("category", ""),
                               "page": int(page["page"]), "text": text, "quality": page.get("quality"),
                               "method": page.get("method"), "pagination": document.get("pagination", "physical"),
                               "document_complete": bool(document.get("complete")), "_tokens": tokens, "_order": index})
    for candidate in candidates:
        tokens = candidate["_tokens"]
        score = sum((1 + math.log((1 + len(candidates)) / (1 + frequencies[token])))
                    * min(3, math.sqrt(tokens[token])) for token in query_tokens if tokens[token])
        candidate["score"] = round(score / (1 + .08 * math.log(1 + sum(tokens.values()))), 5)
    candidates.sort(key=lambda p: (-p["score"], p["_order"], p["page"]))
    chosen = []
    # Each evidence type remains represented when present, even for legal queries.
    for predicate in (lambda p: p["category"] == "contract",
                      lambda p: p["category"] not in {"contract", "supporting"},
                      lambda p: p["category"] == "supporting"):
        first = next((p for p in candidates if predicate(p) and p not in chosen), None)
        if first and len(chosen) < limit:
            chosen.append(first)
    for candidate in candidates:
        if len(chosen) >= min(limit, max_chars):
            break
        if candidate not in chosen:
            chosen.append(candidate)
    chosen = chosen[:max_chars]
    budget, remainder = divmod(max_chars, max(1, len(chosen)))
    output = []
    for index, candidate in enumerate(chosen):
        item = {k: v for k, v in candidate.items() if not k.startswith("_")}
        text = _excerpt(item["text"], query_tokens, budget + int(index < remainder))
        item.update(text=text, excerpted=len(text) < len(item["text"]))
        output.append(item)
    return output
