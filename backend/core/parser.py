"""
parser.py — Document parsing and text extraction

Extracts clean, structured text from uploaded documents. Each parser
returns a ParseResult containing:
  - The full extracted text (newlines preserved)
  - A list of detected headings with their positions (for section chunking)
  - Any warnings (e.g., scanned PDF detected, partial extraction)
  - The document title if detectable

Design principles:
  - Files are processed entirely in memory. Nothing is written to disk.
  - Each parser is a standalone function — easy to swap or improve independently.
  - Heading metadata is extracted where available (DOCX paragraph styles are the
    gold standard; PDF falls back to heuristics; plain text uses pattern matching).

AI PLUGIN POINT (future enhancement):
  The _classify_headings_heuristic() function could be replaced or augmented
  with an AI model for higher-accuracy heading detection in PDFs. The interface
  would be identical: input list of (text, font_size, is_bold) → output list
  of Heading objects. Keep it optional so the tool stays free to use without
  an API key.

Dependencies:
  pip install pdfplumber python-docx beautifulsoup4 chardet
"""

import io
import re
import html as html_module
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class Heading:
    """A detected heading within the document."""
    text: str
    level: int          # 1 = top-level (H1/Title), 2 = H2, etc.
    char_offset: int    # Character offset in the full extracted text


@dataclass
class ParseResult:
    """The output of any parser function."""
    text: str                              # Full extracted text
    headings: list[Heading] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    title: Optional[str] = None
    page_count: Optional[int] = None      # PDFs only
    is_likely_scanned: bool = False       # True if PDF appears to be image-only


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------

def parse_document(content: bytes, mime_type: str) -> ParseResult:
    """
    Dispatch to the appropriate parser based on MIME type.

    Args:
        content:   Raw bytes of the document (in memory, never on disk).
        mime_type: Canonical MIME type (already validated by validators.py).

    Returns:
        ParseResult with extracted text and metadata.
    """
    if mime_type == "application/pdf":
        return _parse_pdf(content)

    if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return _parse_docx(content)

    if mime_type in ("text/html",):
        return _parse_html(content)

    if mime_type in ("text/plain", "text/markdown", "text/csv"):
        return _parse_text(content)

    # Fallback: attempt plain text parsing
    return _parse_text(content)


# ---------------------------------------------------------------------------
# PDF parser
# ---------------------------------------------------------------------------

def _parse_pdf(content: bytes) -> ParseResult:
    """
    Extract text from a PDF using pdfplumber.

    pdfplumber exposes character-level positioning data (x, y coordinates,
    font size, font name) which we use to:
      1. Reconstruct proper line breaks (rather than joining everything into
         one long string, which breaks section detection downstream)
      2. Detect headings via font-size and boldness heuristics
      3. Identify scanned PDFs (very low text yield per page)

    The Y-coordinate reconstruction logic here is more robust than the
    browser-side approach because pdfplumber normalises coordinates for us
    and provides reliable font metadata.
    """
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError(
            "pdfplumber is not installed. Run: pip install pdfplumber"
        )

    result = ParseResult(text="", headings=[], warnings=[])
    all_text_parts: list[str] = []

    # Track font sizes across all pages to identify headings relatively
    all_font_sizes: list[float] = []

    # First pass: collect font size statistics for heading detection
    # (We need the full distribution before we can classify any single line)
    page_line_data: list[list[dict]] = []  # [page][line] = {text, font_size, is_bold, y}

    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            result.page_count = len(pdf.pages)

            for page in pdf.pages:
                lines = _extract_pdf_page_lines(page)
                page_line_data.append(lines)

                for line in lines:
                    if line["font_size"] > 0:
                        all_font_sizes.append(line["font_size"])

    except Exception as e:
        raise ValueError(f"Could not open PDF: {e}")

    # Determine the "body text" font size (most common size = body)
    body_font_size = _modal_font_size(all_font_sizes) if all_font_sizes else 10.0

    # Second pass: reconstruct text and classify headings
    char_offset = 0

    for page_num, lines in enumerate(page_line_data):
        page_texts: list[str] = []
        page_char_start = char_offset

        for line in lines:
            line_text = line["text"]
            font_size = line["font_size"]
            is_bold = line["is_bold"]
            is_blank = line.get("is_blank", False)

            if is_blank:
                page_texts.append("")
                char_offset += 1  # for the newline
                continue

            # Detect heading by font size relative to body
            heading_level = _classify_heading(line_text, font_size, is_bold, body_font_size)
            if heading_level is not None:
                result.headings.append(Heading(
                    text=line_text,
                    level=heading_level,
                    char_offset=char_offset,
                ))

            page_texts.append(line_text)
            char_offset += len(line_text) + 1  # +1 for newline

        # Collapse runs of 3+ blank lines down to 2 within each page
        page_block = "\n".join(page_texts)
        page_block = re.sub(r"\n{3,}", "\n\n", page_block)
        all_text_parts.append(page_block)

    result.text = "\n".join(all_text_parts)
    result.text = re.sub(r"\n{3,}", "\n\n", result.text).strip()

    # Scanned PDF detection: if text yield is very low, warn the user
    words_extracted = len(result.text.split())
    if result.page_count and result.page_count > 0:
        avg_words_per_page = words_extracted / result.page_count
        if avg_words_per_page < 10:
            result.is_likely_scanned = True
            result.warnings.append(
                "This PDF appears to be a scanned image with little or no "
                "extractable text. OCR would be required for accurate results. "
                "The output may be empty or incomplete."
            )

    return result


def _extract_pdf_page_lines(page) -> list[dict]:
    """
    Reconstruct lines from a PDF page using Y-coordinate grouping.

    pdfplumber's page.chars gives us each character with its position.
    We group characters by their Y baseline (within a tolerance) to
    reconstruct the lines the author intended.

    Returns a list of dicts: {text, font_size, is_bold, is_blank, y}
    """
    chars = page.chars
    if not chars:
        return []

    # Sort characters by Y (top to bottom) then X (left to right)
    chars_sorted = sorted(chars, key=lambda c: (-c["y0"], c["x0"]))

    lines: list[dict] = []
    current_line_chars: list[dict] = []
    prev_y = None

    for char in chars_sorted:
        y = char["y0"]

        if prev_y is None:
            prev_y = y
            current_line_chars.append(char)
            continue

        y_delta = abs(prev_y - y)
        # Estimate line height from the character's height
        char_height = char.get("height", 12)
        line_threshold = max(char_height * 0.4, 2.0)
        para_threshold = max(char_height * 1.5, 8.0)

        if y_delta > para_threshold:
            # Large gap — blank line separator + new line
            if current_line_chars:
                lines.append(_chars_to_line(current_line_chars))
                lines.append({"text": "", "font_size": 0, "is_bold": False, "is_blank": True, "y": prev_y})
                current_line_chars = []
        elif y_delta > line_threshold:
            # Moderate gap — new line, no separator
            if current_line_chars:
                lines.append(_chars_to_line(current_line_chars))
                current_line_chars = []

        current_line_chars.append(char)
        prev_y = y

    if current_line_chars:
        lines.append(_chars_to_line(current_line_chars))

    return lines


def _chars_to_line(chars: list[dict]) -> dict:
    """Convert a list of character dicts into a single line dict."""
    text = "".join(c.get("text", "") for c in chars).strip()
    sizes = [c.get("size", 0) for c in chars if c.get("size", 0) > 0]
    font_size = max(sizes) if sizes else 0

    # Bold detection: pdfplumber exposes fontname which often contains "Bold"
    font_names = [c.get("fontname", "") for c in chars]
    is_bold = any("bold" in fn.lower() for fn in font_names if fn)

    y = chars[0].get("y0", 0)
    return {"text": text, "font_size": font_size, "is_bold": is_bold, "is_blank": False, "y": y}


def _modal_font_size(sizes: list[float]) -> float:
    """Return the most common (modal) font size, rounded to nearest point."""
    if not sizes:
        return 10.0
    # Round to nearest 0.5pt to group similar sizes
    rounded = [round(s * 2) / 2 for s in sizes]
    counts: dict[float, int] = {}
    for s in rounded:
        counts[s] = counts.get(s, 0) + 1
    return max(counts, key=counts.get)


def _classify_heading(text: str, font_size: float, is_bold: bool, body_size: float) -> Optional[int]:
    """
    Classify a PDF text line as a heading level (1, 2, 3) or None.

    Heuristics (in priority order):
      1. Font size significantly larger than body text → heading
      2. ALL CAPS short line with no sentence-ending punctuation → heading
      3. Bold text that is shorter than a typical body sentence → possible heading

    AI PLUGIN POINT: This function could call an AI classifier for higher
    accuracy. The signature would remain identical.

    Returns: 1, 2, 3, or None
    """
    if not text or len(text) < 2:
        return None

    # Skip lines that look like page numbers or footnotes
    if re.match(r"^\d+$", text.strip()):
        return None
    if re.match(r"^[ivxlcdmIVXLCDM]+$", text.strip()):
        return None

    # Font size classification
    if font_size > 0 and body_size > 0:
        ratio = font_size / body_size
        if ratio >= 1.5:
            return 1
        if ratio >= 1.2:
            return 2
        if ratio >= 1.05 and is_bold:
            return 3

    # All-caps short line heuristic
    stripped = text.strip()
    if (
        stripped == stripped.upper()
        and len(stripped) >= 3
        and len(stripped) <= 120
        and not stripped.endswith(".")
        and len(stripped.split()) >= 1
    ):
        return 2

    return None


# ---------------------------------------------------------------------------
# DOCX parser
# ---------------------------------------------------------------------------

def _parse_docx(content: bytes) -> ParseResult:
    """
    Extract text and headings from a Word document (.docx).

    python-docx exposes the paragraph style name (e.g. "Heading 1",
    "Heading 2") directly, which is far more reliable than font-size
    heuristics. This is the gold standard for heading detection.

    Tables are extracted as tab-separated rows. Images are skipped
    (we only process text).
    """
    try:
        from docx import Document
        from docx.oxml.ns import qn
    except ImportError:
        raise RuntimeError(
            "python-docx is not installed. Run: pip install python-docx"
        )

    result = ParseResult(text="", headings=[], warnings=[])
    text_parts: list[str] = []
    char_offset = 0

    try:
        doc = Document(io.BytesIO(content))
    except Exception as e:
        raise ValueError(f"Could not open Word document: {e}")

    # Extract document title from core properties if available
    try:
        if doc.core_properties.title:
            result.title = doc.core_properties.title
    except Exception:
        pass

    # Process paragraphs in document order
    for element in doc.element.body:
        tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

        if tag == "p":
            # Regular paragraph or heading
            para_text = element.text_content().strip() if hasattr(element, 'text_content') else ""
            # Get text from all runs in the paragraph
            para_text = "".join(
                run.text for run in element.findall(f".//{{{element.nsmap.get('w', 'http://schemas.openxmlformats.org/wordprocessingml/2006/main')}}}t")
                if run.text
            )
            para_text = para_text.strip()

            # Detect heading level from style
            style_name = _get_docx_style_name(element)
            heading_level = _docx_style_to_heading_level(style_name)

            if para_text:
                if heading_level is not None:
                    result.headings.append(Heading(
                        text=para_text,
                        level=heading_level,
                        char_offset=char_offset,
                    ))
                text_parts.append(para_text)
                char_offset += len(para_text) + 1
            else:
                # Blank paragraph — preserve as paragraph separator
                text_parts.append("")
                char_offset += 1

        elif tag == "tbl":
            # Table — extract as simple tab/newline separated text
            table_text = _extract_docx_table(element)
            if table_text:
                text_parts.append(table_text)
                char_offset += len(table_text) + 1

    result.text = "\n".join(text_parts)
    result.text = re.sub(r"\n{3,}", "\n\n", result.text).strip()
    return result


def _get_docx_style_name(para_element) -> str:
    """Extract the paragraph style name from a docx paragraph XML element."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    pPr = para_element.find(f"{{{ns}}}pPr")
    if pPr is None:
        return "Normal"
    pStyle = pPr.find(f"{{{ns}}}pStyle")
    if pStyle is None:
        return "Normal"
    return pStyle.get(f"{{{ns}}}val", "Normal")


def _docx_style_to_heading_level(style_name: str) -> Optional[int]:
    """Map a Word paragraph style name to a heading level (1-6) or None."""
    if not style_name:
        return None
    lower = style_name.lower().strip()
    # Standard heading styles: "Heading 1" through "Heading 6"
    match = re.match(r"heading\s*(\d)", lower)
    if match:
        return int(match.group(1))
    # Title and subtitle styles
    if lower in ("title", "documenttitle"):
        return 1
    if lower in ("subtitle",):
        return 2
    return None


def _extract_docx_table(table_element) -> str:
    """Extract table content as tab-separated rows."""
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    rows = []
    for row in table_element.findall(f".//{{{ns}}}tr"):
        cells = []
        for cell in row.findall(f".//{{{ns}}}tc"):
            cell_text = "".join(
                t.text or "" for t in cell.findall(f".//{{{ns}}}t")
            ).strip()
            cells.append(cell_text)
        rows.append("\t".join(cells))
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# HTML parser
# ---------------------------------------------------------------------------

def _parse_html(content: bytes) -> ParseResult:
    """
    Extract clean text and headings from an HTML document.

    Uses BeautifulSoup to parse the DOM. Heading elements (h1-h6) are
    detected directly, giving reliable structure. Script, style, and
    navigation elements are removed before text extraction.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise RuntimeError(
            "beautifulsoup4 is not installed. Run: pip install beautifulsoup4"
        )

    result = ParseResult(text="", headings=[], warnings=[])

    # Decode bytes to string
    encoding = _detect_encoding(content)
    try:
        html_str = content.decode(encoding, errors="replace")
    except Exception:
        html_str = content.decode("utf-8", errors="replace")

    soup = BeautifulSoup(html_str, "html.parser")

    # Extract title
    title_tag = soup.find("title")
    if title_tag:
        result.title = title_tag.get_text().strip()

    # Remove non-content elements
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()

    # Extract text with headings
    text_parts: list[str] = []
    char_offset = 0

    for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p",
                                   "li", "td", "th", "blockquote", "pre"]):
        text = element.get_text(separator=" ", strip=True)
        if not text:
            continue

        tag_name = element.name.lower()
        if tag_name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag_name[1])
            result.headings.append(Heading(
                text=text,
                level=level,
                char_offset=char_offset,
            ))
            # Add blank line before headings for better paragraph separation
            if text_parts:
                text_parts.append("")
                char_offset += 1

        text_parts.append(text)
        char_offset += len(text) + 1

    result.text = "\n".join(text_parts)
    result.text = re.sub(r"\n{3,}", "\n\n", result.text).strip()
    return result


# ---------------------------------------------------------------------------
# Plain text parser
# ---------------------------------------------------------------------------

def _parse_text(content: bytes) -> ParseResult:
    """
    Parse plain text, Markdown, CSV, or any other text-based format.

    For plain text we attempt to detect headings using the same heuristic
    patterns as the original client-side chunker (ALL CAPS lines, Markdown
    ATX headers, Roman numerals, etc.). This is the weakest parser since we
    have no structural metadata to rely on — heading detection is best-effort.

    AI PLUGIN POINT: For better section detection in plain text and PDFs,
    a lightweight text classification model could replace or augment
    _detect_text_headings() below.
    """
    result = ParseResult(text="", headings=[], warnings=[])

    # Encoding detection
    encoding = _detect_encoding(content)
    try:
        text = content.decode(encoding, errors="replace")
    except Exception:
        text = content.decode("utf-8", errors="replace")

    # Normalise line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    result.text = text
    result.headings = _detect_text_headings(text)
    return result


def _detect_text_headings(text: str) -> list[Heading]:
    """
    Detect headings in plain text using pattern matching.

    This is intentionally conservative to avoid false positives.
    It recognises:
      - Markdown ATX headers (# Heading)
      - ALL CAPS short lines (legal/legislative documents)
      - Numbered section headings (1. Title, I. Title, A. Title)
    """
    headings = []
    lines = text.split("\n")
    char_offset = 0

    for line in lines:
        stripped = line.strip()

        if stripped:
            heading_level = _classify_text_heading(stripped)
            if heading_level is not None:
                headings.append(Heading(
                    text=stripped,
                    level=heading_level,
                    char_offset=char_offset,
                ))

        char_offset += len(line) + 1  # +1 for the newline

    return headings


def _classify_text_heading(line: str) -> Optional[int]:
    """Classify a plain text line as a heading level or None."""
    # Markdown ATX headers
    md_match = re.match(r"^(#{1,6})\s+\S", line)
    if md_match:
        return len(md_match.group(1))

    # ALL CAPS line (legal/legislative convention)
    if (
        line == line.upper()
        and len(line) >= 3
        and len(line) <= 120
        and not line.endswith(".")
        and re.search(r"[A-Z]", line)
    ):
        # Heuristic: shorter all-caps lines tend to be higher-level headings
        return 1 if len(line) <= 40 else 2

    # Roman numeral section (I. Introduction, IV. Background)
    if re.match(r"^[IVXLCDM]{1,6}\.\s+[A-Z]", line):
        return 2

    # Capital letter section (A. General, B. Scope)
    if re.match(r"^[A-Z]\.\s+[A-Z]", line):
        return 3

    return None


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def _detect_encoding(content: bytes) -> str:
    """
    Detect the text encoding of a byte sequence.
    Falls back to UTF-8 if detection fails or chardet is not installed.
    """
    # Check for BOM first (most reliable)
    if content.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if content.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if content.startswith(b"\xfe\xff"):
        return "utf-16-be"

    # Try chardet for statistical detection
    try:
        import chardet
        detected = chardet.detect(content[:10_000])  # Sample first 10KB
        encoding = detected.get("encoding")
        confidence = detected.get("confidence", 0)
        if encoding and confidence > 0.7:
            return encoding
    except ImportError:
        pass

    # Default to UTF-8
    return "utf-8"
