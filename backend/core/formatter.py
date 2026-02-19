"""
formatter.py — Output serialization

Converts ChunkResult objects into the three supported output formats:
  json    Structured JSON with per-chunk metadata (index, text, heading,
          token count, character offsets). The primary format.
  text    Plain text with separator lines between chunks. Human-readable.
  csv     Tab-separated values with one row per chunk. Suitable for
          spreadsheet import or downstream data pipelines.

All output is returned as a string. The API layer sets the appropriate
Content-Type header based on the chosen format.

No external dependencies for JSON or text. CSV uses the stdlib csv module.
"""

import csv
import io
import json
from typing import Optional

from .chunker import Chunk, ChunkResult


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def format_output(result: ChunkResult, output_format: str) -> tuple[str, str]:
    """
    Serialize a ChunkResult into the requested output format.

    Args:
        result:        The ChunkResult from chunk_text().
        output_format: "json", "text", or "csv".

    Returns:
        A tuple of (serialized_string, content_type).
    """
    if output_format == "json":
        return _format_json(result), "application/json; charset=utf-8"
    if output_format == "text":
        return _format_text(result), "text/plain; charset=utf-8"
    if output_format == "csv":
        return _format_csv(result), "text/csv; charset=utf-8"

    # Unknown format — default to JSON
    return _format_json(result), "application/json; charset=utf-8"


# ---------------------------------------------------------------------------
# JSON format
# ---------------------------------------------------------------------------

def _format_json(result: ChunkResult) -> str:
    """
    Produce a structured JSON response.

    Schema:
    {
      "ok": true,
      "method": "sections",
      "chunk_count": 8,
      "total_chars": 24301,
      "total_words": 3882,
      "warnings": [],
      "chunks": [
        {
          "index": 1,
          "text": "...",
          "heading": "QUESTIONS PRESENTED",  // or null
          "token_count": 214,
          "word_count": 162,
          "char_start": 0,
          "char_end": 847
        },
        ...
      ]
    }

    The top-level `ok: true` field makes it easy for the frontend to
    distinguish success responses from error responses without checking
    HTTP status codes (though the API also uses proper HTTP status codes).
    """
    payload = {
        "ok": True,
        "method": result.method,
        "chunk_count": len(result.chunks),
        "total_chars": result.total_chars,
        "total_words": result.total_words,
        "warnings": result.warnings,
        "chunks": [_chunk_to_dict(chunk) for chunk in result.chunks],
    }
    return json.dumps(payload, ensure_ascii=False, indent=None, separators=(",", ":"))


def _chunk_to_dict(chunk: Chunk) -> dict:
    """Convert a Chunk dataclass to a plain dict for JSON serialization."""
    return {
        "index": chunk.index,
        "text": chunk.text,
        "heading": chunk.heading,
        "token_count": chunk.token_count,
        "word_count": chunk.word_count,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
    }


# ---------------------------------------------------------------------------
# Plain text format
# ---------------------------------------------------------------------------

# Separator used between chunks in plain text output.
# 60 dashes is wide enough to be visible but not overwhelming.
TEXT_SEPARATOR = "─" * 60


def _format_text(result: ChunkResult) -> str:
    """
    Produce human-readable plain text output.

    Format:
        === CHUNK 1 OF 8 ===
        [heading: QUESTIONS PRESENTED]

        <chunk text>

        ────────────────────────────────────────────────────────────

        === CHUNK 2 OF 8 ===
        ...
    """
    total = len(result.chunks)
    parts: list[str] = []

    # Header with summary
    parts.append(f"Chunked with method: {result.method}")
    parts.append(f"Total chunks: {total} | Total chars: {result.total_chars:,} | "
                 f"Total words: {result.total_words:,}")

    if result.warnings:
        for w in result.warnings:
            parts.append(f"WARNING: {w}")

    parts.append("")

    for chunk in result.chunks:
        parts.append(f"=== CHUNK {chunk.index} OF {total} ===")
        if chunk.heading:
            parts.append(f"[section: {chunk.heading}]")
        parts.append("")
        parts.append(chunk.text)
        parts.append("")
        parts.append(TEXT_SEPARATOR)
        parts.append("")

    return "\n".join(parts).strip()


# ---------------------------------------------------------------------------
# CSV format
# ---------------------------------------------------------------------------

def _format_csv(result: ChunkResult) -> str:
    """
    Produce a CSV with one row per chunk.

    Columns: index, heading, word_count, token_count, char_start, char_end, text

    The text column is last because it may contain newlines and commas.
    All fields are properly quoted by the csv module.

    Note: CSV is inherently less rich than JSON — heading and text fields
    are stripped of any embedded newlines in the CSV representation to keep
    rows clean. The text field in CSV is intended for data pipeline use,
    not as the primary output format.
    """
    output = io.StringIO()
    writer = csv.writer(
        output,
        dialect="excel",
        quoting=csv.QUOTE_ALL,
    )

    # Header row
    writer.writerow([
        "index",
        "heading",
        "word_count",
        "token_count",
        "char_start",
        "char_end",
        "text",
    ])

    for chunk in result.chunks:
        # In CSV, collapse internal newlines to a space for clean row handling
        text_for_csv = chunk.text.replace("\n", " ").replace("\r", "")
        heading_for_csv = (chunk.heading or "").replace("\n", " ")

        writer.writerow([
            chunk.index,
            heading_for_csv,
            chunk.word_count,
            chunk.token_count or "",
            chunk.char_start,
            chunk.char_end,
            text_for_csv,
        ])

    return output.getvalue()


# ---------------------------------------------------------------------------
# Error response
# ---------------------------------------------------------------------------

def format_error(message: str, code: str = "ERROR") -> str:
    """
    Produce a standardised JSON error response body.

    The frontend checks `ok: false` to detect errors and displays `message`
    to the user. The `code` field is a machine-readable error identifier
    for client-side logic (e.g., "SIZE_LIMIT_EXCEEDED" triggers a specific
    UI hint rather than a generic error message).

    Schema:
    {
      "ok": false,
      "code": "VALIDATION_ERROR",
      "message": "File exceeds the 50 MB size limit."
    }
    """
    payload = {
        "ok": False,
        "code": code,
        "message": message,
    }
    return json.dumps(payload, ensure_ascii=False)
