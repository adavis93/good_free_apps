"""
sanitizer.py — Output sanitization

Sanitizes text before returning it to the client. This is essential
because document content may contain:
  - HTML/JavaScript that could execute if the output is rendered in a browser
  - Null bytes and control characters that could confuse parsers
  - Extremely long lines that could cause rendering issues

All sanitization is done on the extracted text BEFORE chunking and again
on the final chunk output. The goal is defence in depth.

No external dependencies.
"""

import re
import html as html_module
import unicodedata


def sanitize_text(text: str, context: str = "output") -> str:
    """
    Sanitize extracted text for safe return to the client.

    Args:
        text:    The text to sanitize.
        context: "output" (default) applies all sanitizers.
                 "internal" skips HTML escaping for intermediate processing.

    Returns:
        Sanitized text string.
    """
    if not text:
        return ""

    # 1. Remove null bytes and most control characters
    #    Keep: tab (\x09), newline (\x0a), carriage return (\x0d)
    #    These are legitimate in document text.
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # 2. Normalise Unicode to NFC form
    #    Prevents homoglyph attacks and ensures consistent text comparison
    text = unicodedata.normalize("NFC", text)

    # 3. Remove or replace private-use Unicode characters
    #    These can represent arbitrary rendering instructions in some contexts
    text = re.sub(r"[\ue000-\uf8ff]", "", text)  # BMP private use area
    text = re.sub(r"[\U000f0000-\U000fffff]", "", text)  # Supplementary private use

    # 4. Normalise line endings to \n
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 5. Collapse excessive whitespace
    #    Allow up to 2 consecutive newlines (paragraph separator)
    #    but no more (prevents large blank gaps in output)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Normalise spaces (preserve single/double space, remove runs of 3+)
    text = re.sub(r"[ \t]{3,}", "  ", text)

    # 6. HTML-escape for output context
    #    This prevents XSS if the chunk text is rendered directly in HTML.
    #    Note: this is applied to the TEXT content, not the JSON wrapper —
    #    the API returns JSON and the client is responsible for rendering.
    #    We escape here as a defence-in-depth measure.
    if context == "output":
        text = html_module.escape(text, quote=True)

    return text.strip()


def sanitize_chunk_list(chunks: list) -> list:
    """
    Apply sanitize_text to all chunks in a ChunkResult.chunks list.
    Modifies the text field of each Chunk in place and returns the list.
    """
    for chunk in chunks:
        chunk.text = sanitize_text(chunk.text, context="output")
        if chunk.heading:
            chunk.heading = sanitize_text(chunk.heading, context="output")
    return chunks


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename for safe logging (never for filesystem use).

    We log the filename for debugging purposes but must ensure it
    cannot be used for log injection or path traversal.
    Only alphanumeric characters, dots, hyphens, and underscores are kept.
    """
    sanitized = re.sub(r"[^a-zA-Z0-9._\-]", "_", filename)
    return sanitized[:100]  # Hard limit length


def sanitize_metadata(metadata: dict) -> dict:
    """
    Sanitize any metadata fields before returning them to the client.
    Ensures strings are truncated and safe.
    """
    safe = {}
    for key, value in metadata.items():
        if isinstance(value, str):
            safe[key] = html_module.escape(value[:1000])
        elif isinstance(value, (int, float, bool)) or value is None:
            safe[key] = value
        else:
            # Skip complex objects
            continue
    return safe
