"""
converter.py — Document format conversion

Supported conversions:
  PDF  → TXT  (PyMuPDF/pdfplumber — reuses existing high-quality parser)
  PDF  → DOCX (pdf2docx — highest-fidelity Python-native PDF→Word conversion)
  DOCX → TXT  (python-docx — reuses existing parser)
  DOCX → PDF  (LibreOffice headless — near-Word-perfect output)
  TXT  → PDF  (reportlab — clean, properly-typeset output)
  TXT  → DOCX (python-docx — structured Word document)

Design notes:
  - All processing is done in-memory where possible.
  - pdf2docx and LibreOffice require file-path access, so those converters
    write to a NamedTemporaryFile and clean up in finally blocks.
  - LibreOffice is found via _find_libreoffice(), which searches common
    install paths across Linux, macOS, and nixpkgs.
  - The /api/convert endpoint in server.py calls convert_document() —
    this module has no Flask dependency and can be tested standalone.
"""

import io
import logging
import os
import subprocess
import tempfile
from typing import Tuple

logger = logging.getLogger("chunker.converter")


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------

class ConversionError(Exception):
    """Raised when a conversion fails in an expected, reportable way."""
    def __init__(self, message: str, code: str = "CONVERSION_ERROR", http_status: int = 422):
        self.message = message
        self.code = code
        self.http_status = http_status
        super().__init__(message)


# ---------------------------------------------------------------------------
# Conversion matrix
# ---------------------------------------------------------------------------

# Maps (source_format, target_format) → (converter_function, output_mime_type)
# Formats are normalised lowercase strings: "pdf", "docx", "txt"

_MIME_TYPES = {
    "pdf":  "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt":  "text/plain; charset=utf-8",
}

_SUPPORTED_CONVERSIONS = {
    ("pdf",  "txt"),
    ("pdf",  "docx"),
    ("docx", "txt"),
    ("docx", "pdf"),
    ("txt",  "pdf"),
    ("txt",  "docx"),
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def convert_document(
    content: bytes,
    source_format: str,
    target_format: str,
) -> Tuple[bytes, str]:
    """
    Convert a document from source_format to target_format.

    Args:
        content:       Raw file bytes.
        source_format: "pdf", "docx", or "txt" (case-insensitive, leading dot OK).
        target_format: "pdf", "docx", or "txt" (case-insensitive, leading dot OK).

    Returns:
        Tuple of (converted_bytes, mime_type_string).

    Raises:
        ConversionError: If the conversion is unsupported or fails.
    """
    source = source_format.lower().lstrip(".")
    target = target_format.lower().lstrip(".")

    # Normalise common aliases
    source = _normalise_format(source)
    target = _normalise_format(target)

    if source == target:
        raise ConversionError(
            f"Source and target formats are the same ({source.upper()}). "
            "No conversion is needed.",
            code="SAME_FORMAT",
            http_status=400,
        )

    if (source, target) not in _SUPPORTED_CONVERSIONS:
        supported = ", ".join(f"{a.upper()}→{b.upper()}" for a, b in sorted(_SUPPORTED_CONVERSIONS))
        raise ConversionError(
            f"Conversion from {source.upper()} to {target.upper()} is not supported. "
            f"Supported conversions: {supported}.",
            code="UNSUPPORTED_CONVERSION",
            http_status=400,
        )

    dispatch = {
        ("pdf",  "txt"):  _pdf_to_txt,
        ("pdf",  "docx"): _pdf_to_docx,
        ("docx", "txt"):  _docx_to_txt,
        ("docx", "pdf"):  _docx_to_pdf,
        ("txt",  "pdf"):  _txt_to_pdf,
        ("txt",  "docx"): _txt_to_docx,
    }

    converter_fn = dispatch[(source, target)]
    mime_type = _MIME_TYPES[target]

    try:
        result_bytes = converter_fn(content)
        return result_bytes, mime_type
    except ConversionError:
        raise
    except Exception as e:
        logger.error("Conversion %s→%s failed unexpectedly", source, target, exc_info=True)
        raise ConversionError(
            f"An unexpected error occurred during conversion: {e}",
            code="CONVERSION_ERROR",
            http_status=500,
        )


def get_supported_conversions() -> list[dict]:
    """Return a list of supported conversion pairs for API documentation."""
    return [
        {"from": src.upper(), "to": tgt.upper()}
        for src, tgt in sorted(_SUPPORTED_CONVERSIONS)
    ]


# ---------------------------------------------------------------------------
# Format normalisation
# ---------------------------------------------------------------------------

def _normalise_format(fmt: str) -> str:
    """Normalise format strings — handles aliases like 'doc' → 'docx'."""
    aliases = {
        "doc":      "docx",
        "word":     "docx",
        "text":     "txt",
        "plain":    "txt",
        "markdown": "txt",
        "md":       "txt",
    }
    return aliases.get(fmt, fmt)


def mime_to_format(mime: str) -> str | None:
    """Map a MIME type string to a normalised format string."""
    mapping = {
        "application/pdf":   "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/msword": "docx",
        "text/plain":        "txt",
        "text/markdown":     "txt",
    }
    return mapping.get(mime.split(";")[0].strip().lower())


def ext_to_format(filename: str) -> str | None:
    """Infer format from filename extension."""
    ext = os.path.splitext(filename)[1].lstrip(".").lower()
    return _normalise_format(ext) if ext else None


# ===========================================================================
# PDF → TXT
# ===========================================================================

def _pdf_to_txt(content: bytes) -> bytes:
    """
    Extract plain text from a PDF using the existing high-quality parser.

    Delegates to core.parser.parse_document, which uses PyMuPDF as the
    primary engine (handling wide-kerned text, bold/italic metadata, and
    multi-column layouts) with pdfplumber as a fallback.
    """
    from core.parser import parse_document

    result = parse_document(content, "application/pdf")

    if result.is_likely_scanned:
        raise ConversionError(
            "This PDF appears to be a scanned image. The pages are stored as "
            "pictures rather than searchable text, so text extraction is not "
            "possible without OCR (optical character recognition). "
            "Try a PDF that was created digitally (exported from Word, InDesign, etc.).",
            code="SCANNED_PDF",
            http_status=422,
        )

    if not result.text.strip():
        raise ConversionError(
            "No text could be extracted from this PDF. It may be encrypted, "
            "password-protected, or contain only images.",
            code="NO_TEXT_EXTRACTED",
            http_status=422,
        )

    return result.text.encode("utf-8")


# ===========================================================================
# PDF → DOCX
# ===========================================================================

def _pdf_to_docx(content: bytes) -> bytes:
    """
    Convert PDF to DOCX using pdf2docx.

    pdf2docx reconstructs Word elements from PDF page geometry:
      - Text runs with approximate font size, bold, and italic states
      - Tables (detected via line geometry)
      - Images (embedded as inline pictures)
      - Page layout (margins, columns)

    This is the best available Python-native PDF→DOCX conversion.
    Results are good for text-heavy documents and reasonable for tables;
    complex multi-column magazine layouts will be approximate.

    pdf2docx requires file paths (not byte streams), so we use temp files.
    """
    try:
        from pdf2docx import Converter as PDF2DocxConverter
    except ImportError:
        raise ConversionError(
            "The pdf2docx library is not installed. "
            "Run: pip install pdf2docx",
            code="DEPENDENCY_MISSING",
            http_status=503,
        )

    tmp_pdf_path: str | None = None
    tmp_docx_path: str | None = None

    try:
        # Write input PDF to a temp file
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(content)
            tmp_pdf_path = f.name

        tmp_docx_path = tmp_pdf_path[:-4] + ".docx"

        # Run conversion
        cv = PDF2DocxConverter(tmp_pdf_path)
        try:
            cv.convert(tmp_docx_path, start=0, end=None)
        finally:
            cv.close()

        if not os.path.exists(tmp_docx_path) or os.path.getsize(tmp_docx_path) == 0:
            raise ConversionError(
                "Conversion produced no output. The PDF may be encrypted, "
                "malformed, or contain only images.",
                code="NO_OUTPUT",
                http_status=422,
            )

        with open(tmp_docx_path, "rb") as f:
            return f.read()

    finally:
        _safe_unlink(tmp_pdf_path)
        _safe_unlink(tmp_docx_path)


# ===========================================================================
# DOCX → TXT
# ===========================================================================

def _docx_to_txt(content: bytes) -> bytes:
    """
    Extract plain text from a DOCX file using the existing parser.

    Preserves paragraph structure and extracts table cell content.
    Heading metadata is discarded (plain text output only).
    """
    from core.parser import parse_document

    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    result = parse_document(content, mime)

    if not result.text.strip():
        raise ConversionError(
            "No text could be extracted from this Word document. "
            "It may be empty or contain only images.",
            code="NO_TEXT_EXTRACTED",
            http_status=422,
        )

    return result.text.encode("utf-8")


# ===========================================================================
# DOCX → PDF  (LibreOffice headless)
# ===========================================================================

def _docx_to_pdf(content: bytes) -> bytes:
    """
    Convert DOCX to PDF using LibreOffice headless.

    LibreOffice produces the highest-quality DOCX→PDF conversion available
    in open source. It faithfully reproduces:
      - All paragraph and character styles
      - Tables, headers, footers, footnotes
      - Embedded images and charts
      - Page layout, margins, columns
      - Page numbering and section breaks

    The conversion quality is essentially identical to "Save as PDF"
    from within Microsoft Word or LibreOffice Writer.

    System requirement:
      - The `libreoffice` (or `soffice`) binary must be on PATH or at a
        known installation path. See nixpacks.toml for Railway deployment.
    """
    lo_bin = _find_libreoffice()
    if lo_bin is None:
        raise ConversionError(
            "LibreOffice is not installed on this server. "
            "DOCX to PDF conversion requires LibreOffice. "
            "See DEPLOYMENT.md for installation instructions.",
            code="DEPENDENCY_MISSING",
            http_status=503,
        )

    tmp_docx_path: str | None = None

    try:
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            f.write(content)
            tmp_docx_path = f.name

        tmp_dir = os.path.dirname(tmp_docx_path)

        # --norestore / --nofirststartwizard prevent LibreOffice from trying to
        # restore a previous session or show setup dialogs in a headless env.
        # HOME override is required on some systems where LibreOffice tries to
        # write user config to the system home directory.
        proc_env = {**os.environ, "HOME": tmp_dir}

        result = subprocess.run(
            [
                lo_bin,
                "--headless",
                "--norestore",
                "--nofirststartwizard",
                "--convert-to", "pdf",
                "--outdir", tmp_dir,
                tmp_docx_path,
            ],
            capture_output=True,
            timeout=180,
            env=proc_env,
        )

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            logger.error("LibreOffice exited %d: %s", result.returncode, stderr)
            raise ConversionError(
                "LibreOffice could not convert the document. "
                "The file may be corrupted, password-protected, or use "
                "formatting that is not supported in headless mode.",
                code="LIBREOFFICE_ERROR",
                http_status=422,
            )

        # LibreOffice names the output file after the input (same stem, .pdf extension)
        stem = os.path.splitext(os.path.basename(tmp_docx_path))[0]
        tmp_pdf_path = os.path.join(tmp_dir, stem + ".pdf")

        if not os.path.exists(tmp_pdf_path):
            raise ConversionError(
                "LibreOffice did not produce a PDF output file. "
                "The document may be empty or protected.",
                code="NO_OUTPUT",
                http_status=422,
            )

        try:
            with open(tmp_pdf_path, "rb") as f:
                return f.read()
        finally:
            _safe_unlink(tmp_pdf_path)

    finally:
        _safe_unlink(tmp_docx_path)


def _find_libreoffice() -> str | None:
    """
    Find a working LibreOffice binary.

    Returns the first binary path that responds successfully to --version,
    or None if LibreOffice is not found.
    """
    # Ordered by likelihood on a server environment
    candidates = [
        "libreoffice",                                           # nixpkgs, most Linux PATH
        "soffice",                                               # alternative name
        "/usr/bin/libreoffice",
        "/usr/bin/soffice",
        "/usr/lib/libreoffice/program/soffice",                  # Ubuntu/Debian apt install
        "/usr/lib64/libreoffice/program/soffice",
        "/opt/libreoffice/program/soffice",
        "/opt/libreoffice7.6/program/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",  # macOS
    ]

    for candidate in candidates:
        try:
            result = subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                logger.debug("Found LibreOffice at: %s", candidate)
                return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired, PermissionError):
            continue

    logger.warning("LibreOffice not found. DOCX→PDF conversion will be unavailable.")
    return None


# ===========================================================================
# TXT → PDF  (reportlab)
# ===========================================================================

def _txt_to_pdf(content: bytes) -> bytes:
    """
    Convert plain text to a clean, professionally-typeset PDF using reportlab.

    Layout:
      - Letter page size, 1.1-inch side margins
      - Times New Roman 11pt body text, 16pt leading
      - Blank lines in the source become vertical spacers
      - Long lines are word-wrapped at the page boundary
      - Unicode characters are preserved
    """
    try:
        from reportlab.lib.pagesizes import LETTER
        from reportlab.lib.units import inch
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.enums import TA_LEFT
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.colors import HexColor
    except ImportError:
        raise ConversionError(
            "The reportlab library is not installed. "
            "Run: pip install reportlab",
            code="DEPENDENCY_MISSING",
            http_status=503,
        )

    # Decode — try UTF-8, fall back to latin-1
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = content.decode("latin-1")
        except UnicodeDecodeError:
            text = content.decode("utf-8", errors="replace")

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Build PDF in memory
    buf = io.BytesIO()

    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=1.1 * inch,
        rightMargin=1.1 * inch,
        topMargin=1.0 * inch,
        bottomMargin=1.0 * inch,
        title="Converted Document",
    )

    body_style = ParagraphStyle(
        "Body",
        fontName="Times-Roman",
        fontSize=11,
        leading=16,
        spaceBefore=0,
        spaceAfter=1,
        alignment=TA_LEFT,
        textColor=HexColor("#1a1a1a"),
        wordWrap="CJK",  # enables CJK + normal word wrapping
    )

    story = []
    lines = text.split("\n")

    for line in lines:
        # Escape XML metacharacters for reportlab's Paragraph parser
        safe = (
            line
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

        if safe.strip():
            story.append(Paragraph(safe, body_style))
        else:
            story.append(Spacer(1, 0.14 * inch))

    if not story:
        story.append(Paragraph("(empty document)", body_style))

    doc.build(story)
    buf.seek(0)
    return buf.read()


# ===========================================================================
# TXT → DOCX  (python-docx)
# ===========================================================================

def _txt_to_docx(content: bytes) -> bytes:
    """
    Convert plain text to a Word document using python-docx.

    Each line in the input becomes a paragraph. Blank lines produce
    empty paragraphs (preserving spacing). No heading detection is
    applied — the output is a flat, consistently-styled document.
    """
    try:
        from docx import Document
        from docx.shared import Pt, Inches
    except ImportError:
        raise ConversionError(
            "python-docx is not installed. Run: pip install python-docx",
            code="DEPENDENCY_MISSING",
            http_status=503,
        )

    # Decode
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1", errors="replace")

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    doc = Document()

    # Set margins on all sections
    for section in doc.sections:
        section.top_margin    = Inches(1.0)
        section.bottom_margin = Inches(1.0)
        section.left_margin   = Inches(1.1)
        section.right_margin  = Inches(1.1)

    # Configure default paragraph style
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(11)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after  = Pt(2)
    normal.paragraph_format.line_spacing = Pt(16)

    for line in text.split("\n"):
        para = doc.add_paragraph(line)
        para.style = doc.styles["Normal"]

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


# ===========================================================================
# Shared helpers
# ===========================================================================

def _safe_unlink(path: str | None) -> None:
    """Delete a file if it exists, silently ignoring errors."""
    if path and os.path.exists(path):
        try:
            os.unlink(path)
        except OSError as e:
            logger.debug("Could not delete temp file %s: %s", path, e)