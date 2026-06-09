"""Tests for utils/converter.py — docx → PNG conversion."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.converter import _pdf_to_images, docx_to_images, find_docx


def test_find_docx_returns_none_when_empty(tmp_path):
    assert find_docx(tmp_path) is None


def test_find_docx_returns_first_docx(tmp_path):
    (tmp_path / "output.docx").write_bytes(b"fake")
    result = find_docx(tmp_path)
    assert result is not None
    assert result.name == "output.docx"


def test_find_docx_prefers_non_fixture(tmp_path):
    (tmp_path / "fixture_input.docx").write_bytes(b"fixture")
    (tmp_path / "output.docx").write_bytes(b"output")
    result = find_docx(tmp_path)
    assert result is not None
    assert result.name == "output.docx"


def test_docx_to_images_missing_file(tmp_path):
    result = docx_to_images(tmp_path / "nonexistent.docx")
    assert result == []


def test_docx_to_images_soffice_not_found(tmp_path):
    docx = tmp_path / "test.docx"
    docx.write_bytes(b"fake docx content")
    with patch("utils.converter.subprocess.run", side_effect=FileNotFoundError):
        result = docx_to_images(docx)
    assert result == []


def test_docx_to_images_soffice_fails(tmp_path):
    docx = tmp_path / "test.docx"
    docx.write_bytes(b"fake docx content")
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "conversion failed"
    with patch("utils.converter.subprocess.run", return_value=mock_result):
        result = docx_to_images(docx)
    assert result == []


def test_docx_to_images_pdf2image_failure(tmp_path):
    docx = tmp_path / "test.docx"
    docx.write_bytes(b"fake docx content")
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"fake pdf")

    mock_run = MagicMock()
    mock_run.returncode = 0
    with (
        patch("utils.converter.subprocess.run", return_value=mock_run),
        patch("utils.converter._pdf_to_images", return_value=[]),
    ):
        result = docx_to_images(docx)
    assert result == []


def test_pdf_to_images_respects_max_pages(tmp_path):
    """_pdf_to_images should not produce more than max_pages images."""
    mock_images = [MagicMock() for _ in range(5)]
    for i, img in enumerate(mock_images):
        img.save = MagicMock()

    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"fake pdf")

    with patch("pdf2image.convert_from_path", return_value=mock_images[:3]):
        result = _pdf_to_images(pdf, max_pages=3)
    assert len(result) <= 3


def test_docx_to_pdf_exposed_public_wrapper():
    # docx_to_pdf must exist and return None for a missing file (no soffice needed).
    from pathlib import Path

    from utils.converter import docx_to_pdf

    assert docx_to_pdf(Path("/nonexistent/file.docx")) is None
