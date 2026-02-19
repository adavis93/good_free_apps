"""
parser.py — Document parsing and text extraction

Extracts clean, structured text from uploaded documents. Each parser
returns a ParseResult containing:
  - The full extracted text (newlines preserved)
  - A list of detected headings with their positions (for section chunking)
  - Any warnings (e.g., scanned PDF detected, partial extraction)
  - The document title if detectable

PDF extraction uses PyMuPDF (fitz) as the primary engine. PyMuPDF reads text
spans directly from the PDF's internal structure rather than reconstructing
text character-by-character from bounding boxes. This correctly handles
wide-kerned display type (e.g. "T A Y L O R  B E L L" stored internally as
the span "TAYLOR BELL"), bold/italic metadata, and multi-column layouts.
pdfplumber is retained as a fallback.

Design principles:
  - Files are processed entirely in memory. Nothing is written to disk.
  - Each parser is a standalone function — easy to swap or improve independently.
  - Universal heading exclusions (_is_never_heading) are shared across all
    file types for consistent behaviour.

Dependencies:
  pip install pymupdf python-docx beautifulsoup4 chardet
  (pdfplumber optional fallback: pip install pdfplumber)
"""

import io
import re
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
    text: str
    headings: list[Heading] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    title: Optional[str] = None
    page_count: Optional[int] = None
    is_likely_scanned: bool = False


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------

def parse_document(content: bytes, mime_type: str) -> ParseResult:
    """Dispatch to the appropriate parser based on MIME type."""
    if mime_type == "application/pdf":
        return _parse_pdf(content)
    if mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return _parse_docx(content)
    if mime_type in ("text/html",):
        return _parse_html(content)
    if mime_type in ("text/plain", "text/markdown", "text/csv"):
        return _parse_text(content)
    return _parse_text(content)


# ---------------------------------------------------------------------------
# Universal heading exclusion and cleaning (shared by all parsers)
# ---------------------------------------------------------------------------

# Lines matching ANY of these patterns are never headings, regardless of
# font size, caps, or position in the document.
#
# Rationale for each:
#   ^/{2,}$          — "///" page-continuation markers used in California and
#                      federal court briefs. Never a heading.
#   \.{4,}           — TOC dot leaders: "INTRODUCTION ......... 1". The presence
#                      of 4+ consecutive dots is an unambiguous TOC entry signal.
#   ^\d+$            — Bare page numbers.
#   ^[ivxlcdm]+$     — Bare roman-numeral page numbers (i, ii, iii, iv...).
#   Legal citations  — Lines containing legal reporter abbreviations
#                      (U.S., S.Ct., F.3d, F.Supp., etc.) are case citations,
#                      never headings. These appear bold in some PDFs, which
#                      would otherwise cause them to be misclassified.
#                      Pattern matches the short-form citation style used in
#                      federal and state court documents.
_NEVER_HEADING_PATTERNS = [
    re.compile(r"^/{2,}$"),
    re.compile(r"\.{4,}"),
    re.compile(r"^\d+$"),
    re.compile(r"^[ivxlcdmIVXLCDM]+$"),
    # Legal reporter citations: "477 U.S. 242", "134 S. Ct. 1744", "650 F.3d 915"
    re.compile(r"\d+\s+(?:U\.S\.|S\.\s*Ct\.|F\.\d[a-z]*|F\.\s*Supp\.|L\.\s*Ed\.|A\.\d[a-z]*)"),
    # Parenthetical year at end: "(2014)" or "(3d Cir. 2011)" — standalone citations
    re.compile(r"\(\d{4}\)\s*\.?\s*$"),
]


def _is_never_heading(text: str) -> bool:
    """Return True if this line should never be classified as a heading."""
    stripped = text.strip()
    return any(p.search(stripped) for p in _NEVER_HEADING_PATTERNS)


def _clean_heading_label(text: str) -> str:
    """
    Normalise a heading label for storage and display.

    Removes trailing dot leaders and page numbers that appear in TOC-style
    headings. Example: "INTRODUCTION ........ 1" → "INTRODUCTION"
    """
    # Remove dot leaders and everything after them
    text = re.sub(r"\s*\.{3,}.*$", "", text)
    # Remove any trailing digits that remain (bare page numbers)
    text = re.sub(r"\s+\d+\s*$", "", text)
    return text.strip()


# ---------------------------------------------------------------------------
# PDF parser — PyMuPDF primary, pdfplumber fallback
# ---------------------------------------------------------------------------

def _parse_pdf(content: bytes) -> ParseResult:
    """
    Extract text from a PDF, trying PyMuPDF first, pdfplumber as fallback.

    PyMuPDF (fitz) reads text spans directly from the PDF's internal object
    structure. Unlike pdfplumber's character-level bounding-box approach,
    PyMuPDF retrieves the text as the PDF author encoded it — so wide-kerned
    display type like a title set in tracked-out caps is returned as a single
    span ("TAYLOR BELL"), not as individual characters ("T", "A", "Y"...).
    """
    try:
        import fitz  # PyMuPDF
        return _parse_pdf_pymupdf(content, fitz)
    except ImportError:
        pass

    try:
        import pdfplumber
        return _parse_pdf_pdfplumber(content, pdfplumber)
    except ImportError:
        raise RuntimeError(
            "No PDF library found. Install PyMuPDF: pip install pymupdf"
        )


def _parse_pdf_pymupdf(content: bytes, fitz) -> ParseResult:
    """Primary PDF extraction via PyMuPDF."""
    result = ParseResult(text="")
    all_text_parts: list[str] = []
    all_font_sizes: list[float] = []
    page_line_data: list[list[dict]] = []

    try:
        doc = fitz.open(stream=content, filetype="pdf")
        result.page_count = len(doc)

        for page in doc:
            lines = _extract_pymupdf_lines(page)
            page_line_data.append(lines)
            for line in lines:
                if not line["is_blank"] and line["font_size"] > 0:
                    all_font_sizes.append(line["font_size"])

        doc.close()

    except Exception as e:
        raise ValueError(f"Could not open PDF: {e}")

    body_font_size = _modal_font_size(all_font_sizes) if all_font_sizes else 10.0
    char_offset = 0

    # Track whether we're inside the front-matter zone (TOC / TOA).
    # Heading detection is suppressed in this zone to prevent TOC entries
    # from creating spurious section split points.
    #
    # Zone starts: when we see "TABLE OF CONTENTS" as a heading candidate
    # Zone ends:   when we see any of the known top-level body headings
    #              (INTRODUCTION, STATEMENT, SUMMARY, ARGUMENT, CONCLUSION)
    _BODY_STARTERS = re.compile(
        r"^(INTRODUCTION|STATEMENT OF THE CASE|SUMMARY OF ARGUMENTS?|"
        r"STANDARD OF REVIEW|ARGUMENT|CONCLUSION)$",
        re.IGNORECASE,
    )
    in_front_matter_zone = False

    for lines in page_line_data:
        page_texts: list[str] = []

        for line_idx, line in enumerate(lines):
            if line["is_blank"]:
                page_texts.append("")
                char_offset += 1
                continue

            line_text = line["text"]
            stripped = line_text.strip()

            # Manage front-matter zone transitions.
            # TABLE OF CONTENTS / TABLE OF AUTHORITIES are themselves valid
            # section headings (they should create a split point), but every
            # entry *within* them (lines followed by dot leaders) should not.
            is_toc_header = stripped.upper() in ("TABLE OF CONTENTS", "TABLE OF AUTHORITIES")
            if is_toc_header:
                in_front_matter_zone = True
            elif in_front_matter_zone and _BODY_STARTERS.match(stripped):
                in_front_matter_zone = False

            # Lookahead: if the next 1-2 non-blank lines contain dot leaders,
            # this line is the first part of a multi-line TOC entry.
            next_has_dots = any(
                re.search(r"\.{4,}", lines[j]["text"])
                for j in range(line_idx + 1, min(line_idx + 3, len(lines)))
                if not lines[j]["is_blank"]
            )

            # Detect heading if:
            #   - not a dot-leader line itself (next_has_dots check)
            #     Exception: TOC/TOA headers are always valid even though the
            #     very next line after them is always a dot-leader entry.
            #   - not inside the front-matter zone (except TOC/TOA headers)
            #   - not in the universal exclusion list
            is_inside_toc_entries = in_front_matter_zone and not is_toc_header
            if not is_inside_toc_entries and (is_toc_header or not next_has_dots) and not _is_never_heading(line_text):
                clean_label = _clean_heading_label(line_text)
                level = _classify_pdf_heading(
                    clean_label, line["font_size"], line["is_bold"], body_font_size
                )
                if level is not None:
                    result.headings.append(Heading(
                        text=clean_label,
                        level=level,
                        char_offset=char_offset,
                    ))

            page_texts.append(line_text)
            char_offset += len(line_text) + 1

        page_block = "\n".join(page_texts)
        page_block = re.sub(r"\n{3,}", "\n\n", page_block)
        all_text_parts.append(page_block)

    result.text = "\n".join(all_text_parts)
    result.text = re.sub(r"\n{3,}", "\n\n", result.text).strip()

    # Deduplicate: keep body occurrence over TOC occurrence when both exist
    result.headings = _deduplicate_headings(result.headings)

    # Fix B: re-anchor offsets against the final assembled text to correct
    # drift caused by "\n".join() and re.sub() transformations.
    result.headings = _reanchor_headings(result.headings, result.text)

    _check_scanned(result)
    return result


def _extract_pymupdf_lines(page) -> list[dict]:
    """
    Extract structured lines from a PyMuPDF page object.

    PyMuPDF's get_text("dict") returns blocks → lines → spans. Each span
    is a run of text with uniform formatting (font, size, bold/italic flags).
    We join spans within a line, preserving the dominant font size and bold
    state across spans.

    Block gaps > 8pt are treated as paragraph separators (blank line inserted).
    This threshold works well for most PDFs; very tightly-spaced documents
    may need adjustment.
    """
    lines: list[dict] = []
    prev_block_bottom = None

    try:
        # TEXT_PRESERVE_WHITESPACE keeps intentional spaces within spans.
        # TEXT_MEDIABOX_CLIP discards text outside the visible page area
        # (headers/footers sometimes lurk there in scanned PDFs).
        flags = 0
        try:
            flags = page.fitz.TEXT_PRESERVE_WHITESPACE | page.fitz.TEXT_MEDIABOX_CLIP
        except AttributeError:
            pass  # fitz constants accessible differently in some versions

        page_dict = page.get_text("dict")
    except Exception:
        return lines

    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:  # 0 = text; 1 = image
            continue

        block_bbox = block.get("bbox", [0, 0, 0, 0])
        block_top = block_bbox[1]

        # Paragraph gap detection
        if prev_block_bottom is not None and (block_top - prev_block_bottom) > 8:
            lines.append({"text": "", "font_size": 0, "is_bold": False, "is_blank": True})

        for raw_line in block.get("lines", []):
            span_texts: list[str] = []
            font_sizes: list[float] = []
            is_bold = False

            for span in raw_line.get("spans", []):
                t = span.get("text", "")
                if t:
                    span_texts.append(t)
                sz = span.get("size", 0)
                if sz > 0:
                    font_sizes.append(sz)
                # Bold: PyMuPDF flags bit 4 (value 16) = bold weight
                if span.get("flags", 0) & 16:
                    is_bold = True
                if "bold" in span.get("font", "").lower():
                    is_bold = True

            line_text = "".join(span_texts).strip()
            if line_text:
                lines.append({
                    "text": line_text,
                    "font_size": max(font_sizes) if font_sizes else 0,
                    "is_bold": is_bold,
                    "is_blank": False,
                })

        prev_block_bottom = block_bbox[3]

    # Post-process: merge orphaned Roman numerals with the following line.
    #
    # Some PDFs (especially legal briefs with section numbering) lay out
    # sub-section headings across two lines:
    #   Line N:   "I."
    #   Line N+1: "Factual Background"
    # PyMuPDF extracts these as separate span/line objects. We detect and
    # merge them so the heading classifier sees "I. Factual Background".
    _ORPHAN_ROMAN = re.compile(r"^[IVXLCDM]{1,6}\.$")
    merged: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Orphan: non-blank line whose entire text is a Roman numeral + "."
        if (
            not line["is_blank"]
            and _ORPHAN_ROMAN.match(line["text"].strip())
            and i + 1 < len(lines)
            and not lines[i + 1]["is_blank"]
        ):
            next_line = lines[i + 1]
            merged.append({
                "text": line["text"].strip() + " " + next_line["text"].strip(),
                "font_size": max(line["font_size"], next_line["font_size"]),
                "is_bold": line["is_bold"] or next_line["is_bold"],
                "is_blank": False,
            })
            i += 2  # consume both lines
        else:
            merged.append(line)
            i += 1

    return merged


def _parse_pdf_pdfplumber(content: bytes, pdfplumber) -> ParseResult:
    """Fallback PDF extraction via pdfplumber (character-level reconstruction)."""
    result = ParseResult(text="")
    all_text_parts: list[str] = []
    all_font_sizes: list[float] = []
    page_line_data: list[list[dict]] = []

    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            result.page_count = len(pdf.pages)
            for page in pdf.pages:
                lines = _extract_pdfplumber_lines(page)
                page_line_data.append(lines)
                for line in lines:
                    if not line["is_blank"] and line["font_size"] > 0:
                        all_font_sizes.append(line["font_size"])
    except Exception as e:
        raise ValueError(f"Could not open PDF: {e}")

    body_font_size = _modal_font_size(all_font_sizes) if all_font_sizes else 10.0
    char_offset = 0

    for lines in page_line_data:
        page_texts: list[str] = []
        for line in lines:
            if line["is_blank"]:
                page_texts.append("")
                char_offset += 1
                continue
            line_text = line["text"]
            if not _is_never_heading(line_text):
                clean_label = _clean_heading_label(line_text)
                level = _classify_pdf_heading(
                    clean_label, line["font_size"], line["is_bold"], body_font_size
                )
                if level is not None:
                    result.headings.append(Heading(
                        text=clean_label, level=level, char_offset=char_offset
                    ))
            page_texts.append(line_text)
            char_offset += len(line_text) + 1

        page_block = "\n".join(page_texts)
        page_block = re.sub(r"\n{3,}", "\n\n", page_block)
        all_text_parts.append(page_block)

    result.text = "\n".join(all_text_parts)
    result.text = re.sub(r"\n{3,}", "\n\n", result.text).strip()
    result.headings = _deduplicate_headings(result.headings)
    result.headings = _reanchor_headings(result.headings, result.text)
    _check_scanned(result)
    return result


def _extract_pdfplumber_lines(page) -> list[dict]:
    """Reconstruct lines from pdfplumber character data via Y-coordinate grouping."""
    chars = page.chars
    if not chars:
        return []

    chars_sorted = sorted(chars, key=lambda c: (-c["y0"], c["x0"]))
    lines: list[dict] = []
    current: list[dict] = []
    prev_y = None

    for char in chars_sorted:
        y = char["y0"]
        if prev_y is None:
            prev_y = y
            current.append(char)
            continue

        delta = abs(prev_y - y)
        h = char.get("height", 12)
        line_thresh = max(h * 0.4, 2.0)
        para_thresh = max(h * 1.5, 8.0)

        if delta > para_thresh:
            if current:
                lines.append(_pdfplumber_chars_to_line(current))
            lines.append({"text": "", "font_size": 0, "is_bold": False, "is_blank": True})
            current = []
        elif delta > line_thresh:
            if current:
                lines.append(_pdfplumber_chars_to_line(current))
            current = []

        current.append(char)
        prev_y = y

    if current:
        lines.append(_pdfplumber_chars_to_line(current))
    return lines


def _pdfplumber_chars_to_line(chars: list[dict]) -> dict:
    text = "".join(c.get("text", "") for c in chars).strip()
    sizes = [c.get("size", 0) for c in chars if c.get("size", 0) > 0]
    font_size = max(sizes) if sizes else 0
    is_bold = any("bold" in c.get("fontname", "").lower() for c in chars)
    return {"text": text, "font_size": font_size, "is_bold": is_bold, "is_blank": False}


def _modal_font_size(sizes: list[float]) -> float:
    """Return the most common font size (body text size) across the document."""
    if not sizes:
        return 10.0
    rounded = [round(s * 2) / 2 for s in sizes]
    counts: dict[float, int] = {}
    for s in rounded:
        counts[s] = counts.get(s, 0) + 1
    return max(counts, key=counts.get)


def _check_scanned(result: ParseResult) -> None:
    """Warn if the PDF appears to be a scanned image with little text."""
    if result.page_count and result.page_count > 0:
        avg = len(result.text.split()) / result.page_count
        if avg < 10:
            result.is_likely_scanned = True
            result.warnings.append(
                "This PDF appears to be a scanned image with little or no "
                "extractable text. OCR would be required for accurate results."
            )


def _deduplicate_headings(headings: list[Heading]) -> list[Heading]:
    """
    Remove duplicate headings that appear in both a TOC and the document body.

    PDFs with a Table of Contents cause the same heading text to appear twice:
    once at a low char_offset (the TOC entry) and once at a high char_offset
    (the actual body section). When this happens we keep the LAST occurrence,
    which is always the body — the position where the section actually starts.

    Two headings are considered duplicates when their normalised text matches
    (case-insensitive, whitespace-collapsed).

    Headings that appear only once are always kept.
    """
    if not headings:
        return headings

    # Normalise: lowercase + collapse whitespace
    def normalise(text: str) -> str:
        return re.sub(r"\s+", " ", text.lower().strip())

    # Walk backwards; first time we see a normalised label we keep it,
    # subsequent (earlier) occurrences are TOC duplicates and are dropped.
    seen: set[str] = set()
    result: list[Heading] = []
    for h in reversed(headings):
        key = normalise(h.text)
        if key not in seen:
            seen.add(key)
            result.append(h)

    result.reverse()
    return result


def _reanchor_headings(headings: list[Heading], text: str) -> list[Heading]:
    """
    Fix offset drift by re-finding each heading's true position in the
    assembled text.

    During parsing, char_offset is incremented line-by-line, but the final
    text goes through '\n'.join() and re.sub() transformations that shift
    positions. Stored offsets can be a few characters off — enough to land
    a section split mid-word ('RODUCTION' instead of 'INTRODUCTION').

    For each heading we search a tolerance window around the stored offset.
    We search forward (not from 0) so the body occurrence is found even when
    the same text also appears in a TOC near the start of the document.
    """
    if not headings or not text:
        return headings

    TOLERANCE = 200  # chars to search before/after the stored offset

    anchored: list[Heading] = []
    for h in headings:
        search_from = max(0, h.char_offset - TOLERANCE)
        search_to = min(len(text), h.char_offset + TOLERANCE + len(h.text))
        window = text[search_from:search_to]

        idx = window.find(h.text)
        if idx != -1:
            true_offset = search_from + idx
        else:
            # Wider case-insensitive fallback
            wider_start = max(0, h.char_offset - 500)
            wider = text[wider_start:min(len(text), h.char_offset + 500)]
            lower_idx = wider.lower().find(h.text.lower())
            true_offset = wider_start + lower_idx if lower_idx != -1 else h.char_offset

        anchored.append(Heading(text=h.text, level=h.level, char_offset=true_offset))

    return anchored


def _classify_pdf_heading(
    text: str, font_size: float, is_bold: bool, body_size: float
) -> Optional[int]:
    """
    Classify a PDF text line as heading level 1, 2, 3, or None.

    Checks universal exclusions first, then applies font-size ratios and
    text-pattern heuristics.
    """
    if not text or len(text) < 2:
        return None
    if _is_never_heading(text):
        return None

    stripped = text.strip()

    # Font size vs body text (most reliable signal in PDFs)
    if font_size > 0 and body_size > 0:
        ratio = font_size / body_size
        if ratio >= 1.5:
            return 1
        if ratio >= 1.2:
            return 2
        # Bold + moderately larger (≥1.15×) → level 3.
        # Threshold is intentionally conservative: bold body text (case names,
        # defined terms) often appears at 1.0-1.1× and must not be mistaken
        # for a heading. A true sub-heading is usually at least 1.15× body size.
        if ratio >= 1.15 and is_bold:
            return 3

    # ALL CAPS short line (legal/academic convention)
    if (
        stripped == stripped.upper()
        and len(stripped) >= 3
        and len(stripped) <= 120
        and not stripped.endswith(".")
        and re.search(r"[A-Z]", stripped)
    ):
        return 1 if len(stripped) <= 40 else 2

    # Roman numeral section heading: "I. Factual Background"
    if re.match(r"^[IVXLCDM]{1,6}\.\s+[A-Z]", stripped):
        return 2

    # Letter section heading: "A. Established Principles"
    # Require at least 3 lowercase chars after the initial capital to avoid
    # matching citation abbreviations like "S. Ct." or "N.Y." where the
    # word after the initial is itself an abbreviation.
    if re.match(r"^[A-Z]\.\s+[A-Z][a-z]{2,}", stripped):
        return 3

    return None


# ---------------------------------------------------------------------------
# DOCX parser
# ---------------------------------------------------------------------------

def _parse_docx(content: bytes) -> ParseResult:
    """
    Extract text and headings from a Word document (.docx).

    Uses python-docx paragraph style names ("Heading 1", "Heading 2", etc.)
    for reliable heading detection — far more accurate than font heuristics.
    """
    try:
        from docx import Document
    except ImportError:
        raise RuntimeError("python-docx is not installed. Run: pip install python-docx")

    result = ParseResult(text="")
    text_parts: list[str] = []
    char_offset = 0

    try:
        doc = Document(io.BytesIO(content))
    except Exception as e:
        raise ValueError(f"Could not open Word document: {e}")

    try:
        if doc.core_properties.title:
            result.title = doc.core_properties.title
    except Exception:
        pass

    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    for element in doc.element.body:
        tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

        if tag == "p":
            para_text = "".join(
                run.text for run in element.findall(f".//{{{ns}}}t") if run.text
            ).strip()

            style_name = _get_docx_style_name(element, ns)
            heading_level = _docx_style_to_heading_level(style_name)

            if para_text:
                if heading_level is not None and not _is_never_heading(para_text):
                    clean_label = _clean_heading_label(para_text)
                    result.headings.append(Heading(
                        text=clean_label, level=heading_level, char_offset=char_offset
                    ))
                text_parts.append(para_text)
                char_offset += len(para_text) + 1
            else:
                text_parts.append("")
                char_offset += 1

        elif tag == "tbl":
            table_text = _extract_docx_table(element, ns)
            if table_text:
                text_parts.append(table_text)
                char_offset += len(table_text) + 1

    result.text = "\n".join(text_parts)
    result.text = re.sub(r"\n{3,}", "\n\n", result.text).strip()
    return result


def _get_docx_style_name(para_element, ns: str) -> str:
    pPr = para_element.find(f"{{{ns}}}pPr")
    if pPr is None:
        return "Normal"
    pStyle = pPr.find(f"{{{ns}}}pStyle")
    if pStyle is None:
        return "Normal"
    return pStyle.get(f"{{{ns}}}val", "Normal")


def _docx_style_to_heading_level(style_name: str) -> Optional[int]:
    if not style_name:
        return None
    lower = style_name.lower().strip()
    m = re.match(r"heading\s*(\d)", lower)
    if m:
        return int(m.group(1))
    if lower in ("title", "documenttitle"):
        return 1
    if lower == "subtitle":
        return 2
    return None


def _extract_docx_table(table_element, ns: str) -> str:
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
    """Extract clean text and headings from an HTML document via BeautifulSoup."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise RuntimeError("beautifulsoup4 is not installed. Run: pip install beautifulsoup4")

    result = ParseResult(text="")
    encoding = _detect_encoding(content)
    html_str = content.decode(encoding, errors="replace")
    soup = BeautifulSoup(html_str, "html.parser")

    title_tag = soup.find("title")
    if title_tag:
        result.title = title_tag.get_text().strip()

    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()

    text_parts: list[str] = []
    char_offset = 0

    for element in soup.find_all(["h1","h2","h3","h4","h5","h6","p","li","td","th","blockquote","pre"]):
        text = element.get_text(separator=" ", strip=True)
        if not text:
            continue

        tag_name = element.name.lower()
        if tag_name in ("h1","h2","h3","h4","h5","h6"):
            level = int(tag_name[1])
            if not _is_never_heading(text):
                clean_label = _clean_heading_label(text)
                result.headings.append(Heading(text=clean_label, level=level, char_offset=char_offset))
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
    """Parse plain text, Markdown, CSV, or any text-based format."""
    result = ParseResult(text="")
    encoding = _detect_encoding(content)
    text = content.decode(encoding, errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    result.text = text
    result.headings = _detect_text_headings(text)
    return result


def _detect_text_headings(text: str) -> list[Heading]:
    """
    Detect headings in plain text via pattern matching.

    Applies the same universal exclusions as the PDF parser.
    """
    headings = []
    lines = text.split("\n")
    char_offset = 0
    prev_blank = True

    for line in lines:
        stripped = line.strip()
        if stripped:
            level = _classify_text_heading(stripped, prev_blank)
            if level is not None:
                clean_label = _clean_heading_label(stripped)
                headings.append(Heading(text=clean_label, level=level, char_offset=char_offset))
        prev_blank = not stripped
        char_offset += len(line) + 1

    return headings


def _classify_text_heading(line: str, prev_blank: bool = True) -> Optional[int]:
    """Classify a plain text line as a heading level or None."""
    if _is_never_heading(line):
        return None

    stripped = line.strip()

    # Markdown ATX
    m = re.match(r"^(#{1,6})\s+\S", stripped)
    if m:
        return len(m.group(1))

    # ALL CAPS
    if (
        stripped == stripped.upper()
        and 3 <= len(stripped) <= 120
        and not stripped.endswith(".")
        and re.search(r"[A-Z]", stripped)
    ):
        return 1 if len(stripped) <= 40 else 2

    # Roman numeral section
    if re.match(r"^[IVXLCDM]{1,6}\.\s+[A-Z]", stripped):
        return 2

    # Letter section (require preceding blank to reduce false positives)
    if re.match(r"^[A-Z]\.\s+[A-Z]", stripped) and prev_blank:
        return 3

    # Numbered section: "1. Title", "1.1. Scope"
    if re.match(r"^\d{1,3}(\.\d{1,3})*\.\s+[A-Z]", stripped) and prev_blank:
        return 2

    return None


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------

def _detect_encoding(content: bytes) -> str:
    """Detect byte encoding, falling back to UTF-8."""
    if content.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if content.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if content.startswith(b"\xfe\xff"):
        return "utf-16-be"
    try:
        import chardet
        detected = chardet.detect(content[:10_000])
        enc = detected.get("encoding")
        if enc and detected.get("confidence", 0) > 0.7:
            return enc
    except ImportError:
        pass
    return "utf-8"