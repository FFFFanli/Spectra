"""
Regression tests for /api/upload after the file-type extension fix.

Covers:
  - CSV / Excel happy paths (table)
  - PDF / PPTX / image / audio / video / json (file-as-attachment paths)
  - Unsupported types return 400 with friendly message
  - Excel parse errors map to 400 (not 500)
"""

import io
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.api import app
    return TestClient(app)


class TestUploadHappyPaths:
    def test_csv_uploads_to_duckdb(self, client):
        files = {"file": ("t.csv", b"a,b\n1,2\n", "text/csv")}
        r = client.post("/api/upload", files=files)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["file_type"] == "table"
        assert "table_name" in body

    def test_pdf_uploads_as_attachment(self, client):
        files = {"file": ("t.pdf", b"%PDF-1.4\n%fake\n", "application/pdf")}
        r = client.post("/api/upload", files=files)
        assert r.status_code == 200
        body = r.json()
        assert body["file_type"] == "pdf_template"
        assert body["path"].endswith(".pdf")

    def test_pptx_uploads_as_attachment(self, client):
        # PPTX must be accepted (Team mode FileParser handles it)
        files = {"file": ("t.pptx", b"PK\x03\x04fake",
                          "application/vnd.openxmlformats-officedocument.presentationml.presentation")}
        r = client.post("/api/upload", files=files)
        assert r.status_code == 200
        body = r.json()
        assert body["file_type"] == "presentation"
        assert body["path"].endswith(".pptx")

    def test_png_uploads_as_attachment(self, client):
        files = {"file": ("t.png", b"\x89PNG\r\n\x1a\nfake", "image/png")}
        r = client.post("/api/upload", files=files)
        assert r.status_code == 200
        body = r.json()
        assert body["file_type"] == "image"

    def test_jpg_uploads_as_attachment(self, client):
        files = {"file": ("t.jpg", b"\xff\xd8\xff\xe0fake", "image/jpeg")}
        r = client.post("/api/upload", files=files)
        assert r.status_code == 200

    def test_audio_uploads_as_attachment(self, client):
        files = {"file": ("t.mp3", b"ID3fake", "audio/mpeg")}
        r = client.post("/api/upload", files=files)
        assert r.status_code == 200
        assert r.json()["file_type"] == "audio"

    def test_video_uploads_as_attachment(self, client):
        files = {"file": ("t.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")}
        r = client.post("/api/upload", files=files)
        assert r.status_code == 200
        assert r.json()["file_type"] == "video"

    def test_json_uploads_as_context(self, client):
        files = {"file": ("ctx.json", b'{"a":1}', "application/json")}
        r = client.post("/api/upload", files=files)
        assert r.status_code == 200
        assert r.json()["file_type"] == "json_context"


class TestUploadErrorPaths:
    def test_unsupported_extension_returns_400(self, client):
        files = {"file": ("evil.exe", b"MZ\x90\x00", "application/octet-stream")}
        r = client.post("/api/upload", files=files)
        assert r.status_code == 400
        # Friendly message, not generic 500
        assert "不支持的文件类型" in r.json()["detail"]

    def test_excel_import_error_maps_to_400_not_500(self, client):
        """When pandas/openpyxl version mismatch raises ImportError, return 400."""
        with patch("backend.api.save_file_to_duckdb",
                   side_effect=ImportError("Pandas requires openpyxl 3.1.5")):
            files = {"file": ("t.xlsx", b"PKfake", "application/vnd.ms-excel")}
            r = client.post("/api/upload", files=files)
            assert r.status_code == 400, r.text
            assert "openpyxl" in r.json()["detail"] or "依赖" in r.json()["detail"]

    def test_excel_generic_error_maps_to_400(self, client):
        with patch("backend.api.save_file_to_duckdb",
                   side_effect=ValueError("malformed file")):
            files = {"file": ("t.xlsx", b"PKfake",
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
            r = client.post("/api/upload", files=files)
            assert r.status_code == 400
            assert "解析表格失败" in r.json()["detail"]

    def test_missing_filename_returns_400(self, client):
        # Some clients send empty filename
        files = {"file": ("", b"hello", "text/plain")}
        r = client.post("/api/upload", files=files)
        # FastAPI may treat empty filename differently; accept 400 or 422
        assert r.status_code in (400, 422)
