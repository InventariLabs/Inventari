"""Unit tests for magic-byte / file-signature validation."""

import pytest
from fastapi import HTTPException

from app.core.file_signature import resolve_mime, sniff_mime, validate_signature
from app.i18n.service import get_error_message, set_current_lang


class TestValidateSignature:
    """validate_signature defends against Content-Type spoofing."""

    # --- Accepted formats (magic bytes match declared MIME) ---
    @pytest.mark.parametrize(
        ('content', 'mime'),
        [
            # PNG
            (b'\x89PNG\r\n\x1a\n' + b'\x00' * 64, 'image/png'),
            (b'\x89PNG\r\n\x1a\n', 'image/png'),  # exact magic bytes, no padding
            # JPEG
            (b'\xff\xd8\xff\xe0' + b'\x00' * 64, 'image/jpeg'),
            # GIF (both 87a and 89a revisions)
            (b'GIF87a' + b'\x00' * 64, 'image/gif'),
            (b'GIF89a' + b'\x00' * 64, 'image/gif'),
            # PDF
            (b'%PDF-1.4\n' + b'\x00' * 64, 'application/pdf'),
            # WEBP (RIFF container + WEBP fourcc)
            (b'RIFF\x00\x00\x00\x00WEBPVP8 ' + b'\x00' * 64, 'image/webp'),
            # ZIP / XLSX and OLE2 / XLS
            (
                b'PK\x03\x04' + b'\x00' * 64,
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            ),
            (
                b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1' + b'\x00' * 64,
                'application/vnd.ms-excel',
            ),
        ],
    )
    def test_matching_signature_accepted(self, content, mime):
        validate_signature(content, mime)  # must not raise

    # --- Text formats (no magic bytes — validation is skipped) ---
    @pytest.mark.parametrize(
        ('content', 'mime'),
        [
            (b'col1,col2\nval1,val2\n', 'text/csv'),  # CSV has no signature
            (b'hello world', 'text/plain'),
            (
                b'<svg></svg>',
                'image/svg+xml',
            ),  # XML text — relies on a separate sanitiser
        ],
    )
    def test_text_format_skips_signature_check(self, content, mime):
        validate_signature(content, mime)

    def test_exe_bytes_with_png_mime_rejected(self):
        evil = b'MZ\x90\x00' + b'\x00' * 64  # PE/EXE header
        with pytest.raises(HTTPException) as exc:
            validate_signature(evil, 'image/png')
        assert exc.value.status_code == 400
        assert 'does not match' in exc.value.detail['message']
        assert exc.value.detail['code'] == 'FILE_SIGNATURE_MISMATCH'

    def test_png_bytes_with_jpeg_mime_rejected(self):
        png = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
        with pytest.raises(HTTPException):
            validate_signature(png, 'image/jpeg')

    def test_html_bytes_with_pdf_mime_rejected(self):
        with pytest.raises(HTTPException):
            validate_signature(b'<html>' + b'\x00' * 64, 'application/pdf')

    def test_riff_but_not_webp_rejected(self):
        # RIFF container but 'WAVE' at offset 8 (not WEBP)
        wav = b'RIFF\x00\x00\x00\x00WAVEfmt ' + b'\x00' * 64
        with pytest.raises(HTTPException) as exc:
            validate_signature(wav, 'image/webp')
        assert exc.value.detail['message'] == get_error_message('file_not_webp', 'en')

    def test_exe_bytes_with_xlsx_mime_rejected(self):
        evil = b'MZ\x90\x00' + b'\x00' * 64
        with pytest.raises(HTTPException):
            validate_signature(
                evil,
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )

    # --- Edge cases ---
    def test_empty_content_rejected(self):
        with pytest.raises(HTTPException) as exc:
            validate_signature(b'', 'image/png')
        assert 'empty' in exc.value.detail['message'].lower()

    def test_missing_mime_rejected(self):
        with pytest.raises(HTTPException) as exc:
            validate_signature(b'\x89PNG\r\n\x1a\n', '')
        assert 'Content-Type' in exc.value.detail['message']

    def test_missing_content_type_is_said_in_the_readers_language(self):
        set_current_lang('pl')
        try:
            with pytest.raises(HTTPException) as exc:
                validate_signature(b'\x89PNG\r\n\x1a\n', '')
        finally:
            set_current_lang('en')
        assert exc.value.detail['message'] == get_error_message(
            'file_content_type_missing', 'pl'
        )
        assert exc.value.detail['message'].startswith('Plik nie podaje')
        assert exc.value.detail['code'] == 'FILE_CONTENT_TYPE_MISSING'

    def test_unknown_mime_rejected(self):
        with pytest.raises(HTTPException) as exc:
            validate_signature(b'\x00' * 64, 'application/x-unknown')
        assert exc.value.detail['message'] == get_error_message(
            'file_type_not_allowed', 'en'
        )


class TestResolveMime:
    """the stored MIME comes from the bytes, not from the client header."""

    def test_sniffs_png(self):
        assert sniff_mime(b'\x89PNG\r\n\x1a\n' + b'\x00' * 8) == 'image/png'

    def test_sniffs_webp_only_with_the_webp_tag(self):
        assert sniff_mime(b'RIFF\x00\x00\x00\x00WEBPxxxx') == 'image/webp'
        # Bare RIFF is a wav/avi container, not a webp.
        assert sniff_mime(b'RIFF\x00\x00\x00\x00WAVEfmt ') is None

    def test_unsignable_content_returns_none(self):
        assert sniff_mime(b'just some text') is None

    def test_bytes_win_over_a_mismatched_declaration(self):
        """Only reachable if validate_signature is skipped — still must not lie."""
        assert resolve_mime(b'%PDF-1.7\n', 'image/png') == 'application/pdf'

    def test_declaration_kept_when_bytes_cannot_be_more_specific(self):
        """Every OOXML file is a ZIP; 'xlsx' carries more than 'PK' does."""
        xlsx = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        assert resolve_mime(b'PK\x03\x04' + b'\x00' * 8, xlsx) == xlsx

    def test_plain_zip_stays_zip(self):
        assert (
            resolve_mime(b'PK\x03\x04' + b'\x00' * 8, 'application/zip')
            == 'application/zip'
        )

    def test_text_falls_back_to_the_declaration(self):
        assert resolve_mime(b'hello world', 'text/plain') == 'text/plain'
