"""
engine.py — Processing pipeline orchestrator

This is the single entry point for all document processing. Platform adapters
(Flask route, FastAPI endpoint, Cloudflare Worker, Lambda handler, etc.)
call process_request() or process_text() and get back a formatted string
ready to return to the client.

The pipeline:
    1. validate_upload()   — size, MIME, magic bytes
    2. validate_options()  — chunk settings
    3. parse_document()    — extract text + headings
    4. sanitize_text()     — clean extracted text
    5. chunk_text()        — split into chunks
    6. sanitize_chunk_list() — clean chunk output
    7. format_output()     — serialize to JSON/text/CSV

Errors at any stage are caught and re-raised as ProcessingError, which
carries both a user-facing message and an HTTP status code so the adapter
can respond appropriately without knowing the internals.

No document content is ever logged. The only things logged are:
  - Sanitized filename (for request tracing)
  - MIME type determined
  - Chunk count and method (for analytics)
  - Processing time
  - Error codes (never error messages that might contain document text)
"""

import logging
import time
from typing import Optional

from .validators import validate_upload, validate_options, ValidationError
from .parser import parse_document
from .chunker import chunk_text
from .sanitizer import sanitize_text, sanitize_chunk_list, sanitize_filename
from .formatter import format_output, format_error

# Logger for this module — structured, no document content ever written
logger = logging.getLogger("chunker.engine")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ProcessingError(Exception):
    """
    Raised when any step of the processing pipeline fails in a way that
    should produce an error response to the client.

    Attributes:
        message:     User-facing error message (safe to display in the UI).
        code:        Machine-readable error code (e.g., "VALIDATION_ERROR").
        http_status: Suggested HTTP status code for the response.
    """
    def __init__(self, message: str, code: str = "PROCESSING_ERROR", http_status: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def process_request(
    content: bytes,
    filename: str,
    declared_mime: Optional[str],
    options: dict,
) -> tuple[str, str]:
    """
    Process an uploaded file end-to-end.

    Args:
        content:       Raw bytes of the uploaded file.
        filename:      Original filename from the upload (used for extension
                       hint and sanitized logging only — never stored).
        declared_mime: Content-Type the client declared, if any.
        options:       Raw options dict from the request body. Will be
                       validated and normalised internally.

    Returns:
        Tuple of (serialized_output, content_type_header_value).

    Raises:
        ProcessingError on validation failure, parse error, or any other
        problem. The caller should catch this and return an error response.
    """
    t_start = time.monotonic()
    safe_filename = sanitize_filename(filename)

    # ── Step 1: Validate upload ───────────────────────────────────────────
    try:
        validation = validate_upload(
            content=content,
            filename=filename,
            declared_mime=declared_mime,
        )
    except ValidationError as e:
        raise ProcessingError(str(e), code="VALIDATION_ERROR", http_status=400)

    logger.info(
        "Processing upload",
        extra={
            "upload_filename": safe_filename,
            "mime": validation.canonical_mime,
            "size_bytes": len(content),
        }
    )

    # ── Step 2: Validate options ──────────────────────────────────────────
    try:
        opts = validate_options(options)
    except ValidationError as e:
        raise ProcessingError(str(e), code="OPTION_ERROR", http_status=400)

    # ── Step 3: Parse document ────────────────────────────────────────────
    try:
        parse_result = parse_document(
            content=content,
            mime_type=validation.canonical_mime,
        )
    except ValueError as e:
        # Parser returns ValueError for malformed documents
        raise ProcessingError(
            f"Could not parse the document: {e}",
            code="PARSE_ERROR",
            http_status=422,
        )
    except RuntimeError as e:
        # Parser raises RuntimeError when a required library is missing
        raise ProcessingError(
            f"Server configuration error: {e}",
            code="SERVER_ERROR",
            http_status=500,
        )

    # Warn the user if this looks like a scanned PDF
    extra_warnings: list[str] = list(parse_result.warnings)

    if not parse_result.text or not parse_result.text.strip():
        raise ProcessingError(
            "No text could be extracted from this document. "
            "If this is a scanned PDF, OCR processing would be required.",
            code="NO_TEXT_EXTRACTED",
            http_status=422,
        )

    # ── Step 4: Sanitize extracted text ──────────────────────────────────
    # Sanitize for internal processing (no HTML escaping yet — that comes
    # after chunking so we don't escape text that will be re-processed)
    clean_text = sanitize_text(parse_result.text, context="internal")
    clean_headings = parse_result.headings  # Heading objects, text sanitized below

    # ── Step 5: Chunk ─────────────────────────────────────────────────────
    chunk_result = chunk_text(
        text=clean_text,
        headings=clean_headings,
        options=opts,
    )
    chunk_result.warnings.extend(extra_warnings)

    # ── Step 6: Sanitize output chunks ───────────────────────────────────
    sanitize_chunk_list(chunk_result.chunks)

    # ── Step 7: Format output ─────────────────────────────────────────────
    output_str, content_type = format_output(
        result=chunk_result,
        output_format=opts["output_format"],
    )

    elapsed_ms = int((time.monotonic() - t_start) * 1000)
    logger.info(
        "Processing complete",
        extra={
            "method": opts["method"],
            "chunk_count": len(chunk_result.chunks),
            "elapsed_ms": elapsed_ms,
        }
    )

    return output_str, content_type


def process_text(
    text: str,
    options: dict,
) -> tuple[str, str]:
    """
    Process a plain text string (pasted text, no file upload).

    This skips the file validation and parsing steps and goes straight
    to sanitization → chunking → formatting.

    Args:
        text:    The raw text string submitted by the user.
        options: Raw options dict (same format as process_request).

    Returns:
        Tuple of (serialized_output, content_type_header_value).

    Raises:
        ProcessingError on validation failure or processing error.
    """
    if not text or not text.strip():
        raise ProcessingError(
            "No text was provided.",
            code="NO_TEXT",
            http_status=400,
        )

    if len(text) > 10_000_000:  # 10 MB of raw text
        raise ProcessingError(
            "Text input exceeds the 10 MB limit. Please upload a file instead.",
            code="SIZE_LIMIT_EXCEEDED",
            http_status=413,
        )

    try:
        opts = validate_options(options)
    except ValidationError as e:
        raise ProcessingError(str(e), code="OPTION_ERROR", http_status=400)

    clean_text = sanitize_text(text, context="internal")

    # For plain text input, detect headings inline
    from .parser import _detect_text_headings
    headings = _detect_text_headings(clean_text)

    chunk_result = chunk_text(
        text=clean_text,
        headings=headings,
        options=opts,
    )

    sanitize_chunk_list(chunk_result.chunks)

    output_str, content_type = format_output(
        result=chunk_result,
        output_format=opts["output_format"],
    )

    return output_str, content_type
