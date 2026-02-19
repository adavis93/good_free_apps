"""
validators.py — File and input validation

Validates uploaded files before any parsing occurs. Checks:
  1. File size against configurable limit
  2. MIME type (from the Content-Type header the client sends)
  3. Magic bytes (actual file signature — cannot be spoofed by renaming)

Validating magic bytes is critical for security: a malicious user could
rename a file to "document.pdf" to bypass extension checks. We read the
first few bytes of the file content to confirm it matches the declared type.

No external dependencies — uses only the Python standard library.
"""

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Maximum upload size in bytes. 50 MB is generous for text documents.
# Adjust downward if your hosting plan has tight memory constraints.
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

# Allowed MIME types and the file signatures (magic bytes) that must match.
# Each entry maps a MIME type to one or more byte sequences that may appear
# at the start of a valid file of that type.
#
# References:
#   https://en.wikipedia.org/wiki/List_of_file_signatures
#   https://www.garykessler.net/library/file_sigs.html
ALLOWED_TYPES: dict[str, dict] = {
    "application/pdf": {
        "extensions": [".pdf"],
        "magic": [b"%PDF-"],
        "description": "PDF document",
    },
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {
        "extensions": [".docx"],
        # DOCX is a ZIP archive. All ZIP files start with PK\x03\x04.
        # We do a deeper check in the parser to confirm it contains Word XML.
        "magic": [b"PK\x03\x04"],
        "description": "Word document (DOCX)",
    },
    "text/plain": {
        "extensions": [".txt", ".md", ".log", ".csv", ".tsv"],
        # Plain text has no universal magic bytes. We accept any content
        # and validate that it decodes as UTF-8 (or a supported encoding)
        # in the parser instead.
        "magic": [],
        "description": "Plain text",
    },
    "text/html": {
        "extensions": [".html", ".htm"],
        "magic": [],  # HTML is text; validated by content heuristic below
        "description": "HTML document",
    },
    "text/markdown": {
        "extensions": [".md", ".markdown"],
        "magic": [],
        "description": "Markdown document",
    },
    "text/csv": {
        "extensions": [".csv"],
        "magic": [],
        "description": "CSV file",
    },
}

# Additional MIME aliases that browsers or OS file pickers sometimes send.
# Maps the alias to the canonical key in ALLOWED_TYPES above.
MIME_ALIASES: dict[str, str] = {
    "application/msword": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/octet-stream": None,  # Require magic-byte confirmation; no alias
    "text/x-markdown": "text/markdown",
    "text/x-csv": "text/csv",
}


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

class ValidationError(Exception):
    """Raised when a file fails any validation check."""
    pass


class ValidationResult:
    """Holds the outcome of a successful validation."""
    def __init__(self, canonical_mime: str, description: str):
        self.canonical_mime = canonical_mime
        self.description = description


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_upload(
    content: bytes,
    filename: str,
    declared_mime: Optional[str] = None,
) -> ValidationResult:
    """
    Validate an uploaded file before parsing.

    Args:
        content:       Raw bytes of the uploaded file (already in memory).
        filename:      Original filename (used for extension hint only).
        declared_mime: Content-Type the client declared, if any.

    Returns:
        ValidationResult with the confirmed canonical MIME type.

    Raises:
        ValidationError with a user-facing message on any failure.
    """
    # ── 1. Size check ────────────────────────────────────────────────────────
    if len(content) == 0:
        raise ValidationError("The uploaded file is empty.")
    if len(content) > MAX_FILE_SIZE_BYTES:
        limit_mb = MAX_FILE_SIZE_BYTES // (1024 * 1024)
        raise ValidationError(
            f"File exceeds the {limit_mb} MB size limit "
            f"({len(content) // (1024 * 1024)} MB received)."
        )

    # ── 2. Resolve the canonical MIME type ───────────────────────────────────
    # Start from the declared MIME, resolve aliases, then fall back to
    # extension sniffing if the client sent nothing useful.
    canonical = _resolve_mime(declared_mime, filename)

    if canonical is None:
        raise ValidationError(
            "Could not determine the file type. "
            "Please upload a PDF, DOCX, TXT, HTML, or Markdown file."
        )

    if canonical not in ALLOWED_TYPES:
        raise ValidationError(
            f"File type '{canonical}' is not supported. "
            f"Supported types: PDF, DOCX, TXT, HTML, Markdown."
        )

    # ── 3. Magic bytes check ─────────────────────────────────────────────────
    type_def = ALLOWED_TYPES[canonical]
    magic_signatures = type_def["magic"]

    if magic_signatures:
        # This type has known magic bytes — the file must match at least one.
        matched = any(content.startswith(sig) for sig in magic_signatures)
        if not matched:
            raise ValidationError(
                f"The file does not appear to be a valid {type_def['description']}. "
                "The file signature does not match the expected format."
            )
    else:
        # Text-based types: verify the content is valid UTF-8 (or close to it).
        # This catches binary files uploaded with a text MIME type.
        _validate_text_content(content, canonical)

    return ValidationResult(
        canonical_mime=canonical,
        description=type_def["description"],
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_mime(declared_mime: Optional[str], filename: str) -> Optional[str]:
    """
    Determine the canonical MIME type from the declared MIME and/or filename.
    Returns None if the type cannot be determined.
    """
    candidates = []

    # Try declared MIME first
    if declared_mime:
        # Strip parameters (e.g. "text/html; charset=utf-8" → "text/html")
        base_mime = declared_mime.split(";")[0].strip().lower()

        if base_mime in ALLOWED_TYPES:
            candidates.append(base_mime)
        elif base_mime in MIME_ALIASES:
            resolved = MIME_ALIASES[base_mime]
            if resolved:
                candidates.append(resolved)

    # Try extension fallback
    ext = _get_extension(filename)
    for mime, type_def in ALLOWED_TYPES.items():
        if ext in type_def["extensions"]:
            if mime not in candidates:
                candidates.append(mime)

    return candidates[0] if candidates else None


def _get_extension(filename: str) -> str:
    """Extract and normalise the file extension."""
    parts = filename.rsplit(".", 1)
    if len(parts) == 2:
        return "." + parts[1].lower()
    return ""


def _validate_text_content(content: bytes, mime: str) -> None:
    """
    For text-based formats, verify the content can be decoded as text
    AND does not look like binary data.

    The challenge: latin-1 decodes all 256 byte values without error, so
    simple "can it decode?" is not sufficient. We also check the ratio of
    non-printable bytes as a binary-content signal.

    Text documents (even with accented characters) have essentially zero
    non-printable bytes. Binary files (executables, images, encrypted data)
    typically have >5% non-printable bytes. We use 5% as the threshold.
    """
    sample = content[:100_000]  # Check first 100KB only (fast + sufficient)

    # Count bytes that are non-printable and not legitimate whitespace.
    # Legitimate: tab (0x09), LF (0x0A), CR (0x0D), and printable ASCII/UTF-8
    non_printable = sum(
        1 for b in sample
        if b < 9 or (0x0B <= b <= 0x0C) or (0x0E <= b <= 0x1F) or b == 0x7F
    )
    ratio = non_printable / len(sample) if sample else 0

    if ratio > 0.05:
        raise ValidationError(
            "The file appears to contain binary data, not text. "
            "Please ensure the file is a plain text document (UTF-8 or similar encoding)."
        )

    # Try UTF-8 first, then latin-1 as a fallback for legacy Western European text
    for encoding in ("utf-8", "latin-1"):
        try:
            content.decode(encoding)
            return  # Successfully decoded — it's text
        except (UnicodeDecodeError, ValueError):
            continue

    raise ValidationError(
        "The file does not appear to contain valid text. "
        "Please ensure the file is a plain text document."
    )


def validate_options(options: dict) -> dict:
    """
    Validate and normalise the chunking options dictionary.
    Returns the options dict with defaults filled in and values clamped.

    This is called separately from file validation so that plain-text
    paste requests (no file upload) still get their options validated.
    """
    VALID_METHODS = {"characters", "words", "sections", "sentences", "tokens", "delimiter"}
    VALID_FORMATS = {"json", "text", "csv"}

    method = options.get("method", "characters")
    if method not in VALID_METHODS:
        raise ValidationError(
            f"Unknown chunking method '{method}'. "
            f"Valid options: {', '.join(sorted(VALID_METHODS))}"
        )

    output_format = options.get("output_format", "json")
    if output_format not in VALID_FORMATS:
        raise ValidationError(
            f"Unknown output format '{output_format}'. "
            f"Valid options: {', '.join(sorted(VALID_FORMATS))}"
        )

    # Clamp numeric options to safe ranges
    size = int(options.get("size", 4000))
    size = max(50, min(size, 500_000))

    overlap = int(options.get("overlap", 0))
    overlap = max(0, min(overlap, size // 2))  # Overlap can't exceed half the chunk size

    max_section_size = int(options.get("max_section_size", 8000))
    max_section_size = max(200, min(max_section_size, 500_000))

    min_chunk_size = int(options.get("min_chunk_size", 400))
    min_chunk_size = max(0, min(min_chunk_size, 10_000))

    # Custom delimiter: limit length to prevent abuse
    delimiter = options.get("delimiter", None)
    if delimiter is not None:
        delimiter = str(delimiter)[:100]  # Max 100 chars

    return {
        "method": method,
        "size": size,
        "overlap": overlap,
        "max_section_size": max_section_size,
        "min_chunk_size": min_chunk_size,
        "delimiter": delimiter,
        "output_format": output_format,
        "preserve_headings": bool(options.get("preserve_headings", True)),
        "strip_page_numbers": bool(options.get("strip_page_numbers", False)),
    }
