"""Fetch only the public, visually verified Ministry PDFs with fixed SHA-256."""
from pathlib import Path
import hashlib
import json
import os
import tempfile
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
LIBRARY = Path(os.environ.get("AUDIT_DATA_DIR", ROOT / "data")) / "reference_library"


class MinistryRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        target = urlsplit(new_url)
        if target.scheme != "https" or target.hostname != "mop.gov.iq" or target.username or target.password:
            raise RuntimeError("Unexpected reference redirect; TLS verification is required")
        return super().redirect_request(request, fp, code, message, headers, new_url)


def main():
    LIBRARY.mkdir(parents=True, exist_ok=True)
    config = ROOT / "official_reference_manifest.json"
    entries = json.loads(config.read_text(encoding="utf-8"))
    manifest_path = LIBRARY / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    for item in entries:
        filename = item["filename"]
        if Path(filename).name != filename:
            raise ValueError("Invalid reference filename")
        source = urlsplit(item["source_url"])
        if source.scheme != "https" or source.hostname != "mop.gov.iq":
            raise ValueError("Only the verified HTTPS Ministry source is supported")
        target = LIBRARY / filename
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]:
                raise RuntimeError(f"Preserved unexpected existing file; review it before replacing: {filename}")
        else:
            temp = None
            try:
                with tempfile.NamedTemporaryFile(dir=LIBRARY, delete=False) as output:
                    temp = Path(output.name)
                    request = urllib.request.Request(item["source_url"], headers={"User-Agent": "ContractAuditReferences/1.0"})
                    with urllib.request.build_opener(MinistryRedirects()).open(request, timeout=45) as response:
                        final = urlsplit(response.url)
                        if final.scheme != "https" or final.hostname != "mop.gov.iq":
                            raise RuntimeError("Unexpected reference redirect")
                        size = 0
                        while block := response.read(1024 * 1024):
                            size += len(block)
                            if size > 100 * 1024 * 1024:
                                raise RuntimeError("Reference exceeds the 100 MB limit")
                            output.write(block)
                if hashlib.sha256(temp.read_bytes()).hexdigest() != item["sha256"]:
                    raise RuntimeError(f"Reference checksum mismatch; no unverified file installed: {filename}")
                temp.replace(target)
            finally:
                if temp is not None:
                    temp.unlink(missing_ok=True)
        if not any(old["filename"] == filename for old in manifest):
            manifest.append({k: v for k, v in item.items() if k != "sha256"})
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Verified {len(entries)} official references; existing user sources preserved.")


if __name__ == "__main__":
    main()
