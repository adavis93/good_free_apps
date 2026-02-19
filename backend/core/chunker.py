"""
chunker.py — Chunking strategies

Splits extracted document text into chunks suitable for AI consumption or
other downstream processing. All strategies operate on plain text strings
and a list of Heading objects from the parser.

Available strategies:
  characters   Split at a target character count, breaking at paragraph/sentence
               boundaries where possible to avoid mid-sentence cuts.
  words        Split at a target word count with the same smart-break logic.
  tokens       Split at a target token count using the cl100k_base tokenizer
               (the tokenizer used by GPT-4 and later OpenAI models, also a
               reasonable proxy for other LLMs). Falls back to word count
               if tiktoken is not installed.
  sentences    Split into groups of N sentences. Uses spaCy if available,
               falls back to a robust regex sentence splitter.
  sections     Split at document section boundaries detected by the parser's
               heading metadata (DOCX/HTML) or heuristic patterns (PDF/TXT).
  delimiter    Split on a user-specified string delimiter.

All strategies support:
  overlap      Repeat N characters/words/tokens from the end of the previous
               chunk at the start of the next one, for context continuity.
  min_size     Merge any chunk smaller than this back into its predecessor.
  max_size     Hard cap: force-split any chunk that exceeds this limit.

AI PLUGIN POINT: The 'sentences' strategy could be improved with a proper
NLP model for sentence boundary detection in technical/legal text. The
_split_sentences() function is the swap point — same input/output contract.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from .parser import Heading


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    """A single output chunk."""
    index: int                             # 1-based chunk number
    text: str                              # The chunk content
    char_start: int                        # Start offset in original text
    char_end: int                          # End offset in original text
    heading: Optional[str] = None         # Section heading this chunk falls under
    token_count: Optional[int] = None     # Estimated token count (if available)
    word_count: int = 0


@dataclass
class ChunkResult:
    """The full output of a chunking operation."""
    chunks: list[Chunk]
    method: str
    total_chars: int
    total_words: int
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------

def chunk_text(
    text: str,
    headings: list[Heading],
    options: dict,
) -> ChunkResult:
    """
    Split text into chunks according to the provided options.

    Args:
        text:     The full extracted document text.
        headings: Heading objects from the parser (for 'sections' mode).
        options:  Validated options dict from validators.validate_options().

    Returns:
        ChunkResult with a list of Chunk objects and summary metadata.
    """
    method = options["method"]
    warnings: list[str] = []

    # Dispatch to the appropriate strategy
    if method == "characters":
        raw_chunks = _split_by_characters(
            text,
            size=options["size"],
            overlap=options["overlap"],
        )
    elif method == "words":
        raw_chunks = _split_by_words(
            text,
            word_count=options["size"],
            overlap_words=options["overlap"],
        )
    elif method == "tokens":
        raw_chunks, tok_warning = _split_by_tokens(
            text,
            token_count=options["size"],
            overlap_tokens=options["overlap"],
        )
        if tok_warning:
            warnings.append(tok_warning)
    elif method == "sentences":
        raw_chunks = _split_by_sentences(
            text,
            sentences_per_chunk=options["size"],
        )
    elif method == "sections":
        raw_chunks = _split_by_sections(
            text,
            headings=headings,
            max_section_size=options["max_section_size"],
        )
        if not raw_chunks or len(raw_chunks) <= 1:
            warnings.append(
                "No section headings were detected. Falling back to character-based "
                "splitting at 4,000 characters per chunk. Try a different method, "
                "or ensure your document contains structured headings."
            )
            raw_chunks = _split_by_characters(text, size=4000, overlap=0)
    elif method == "delimiter":
        delimiter = options.get("delimiter") or "\n\n"
        raw_chunks = _split_by_delimiter(text, delimiter=delimiter)
    else:
        raw_chunks = _split_by_characters(text, size=4000, overlap=0)

    # Post-processing: merge small chunks, build Chunk objects
    if options.get("min_chunk_size", 0) > 0:
        raw_chunks = _merge_small_chunks(
            raw_chunks,
            min_size=options["min_chunk_size"],
            max_size=options.get("max_section_size", 500_000) if method == "sections" else None,
        )

    chunks = _build_chunk_objects(raw_chunks, text, headings)

    return ChunkResult(
        chunks=chunks,
        method=method,
        total_chars=len(text),
        total_words=len(text.split()),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Strategy: character count
# ---------------------------------------------------------------------------

def _split_by_characters(text: str, size: int, overlap: int) -> list[str]:
    """
    Split text at a target character count, preferring natural break points.

    Break-point priority: paragraph break > sentence boundary > word boundary.
    This avoids cutting sentences in half, which degrades AI performance.
    """
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0

    while start < len(text):
        end = start + size

        if end >= len(text):
            # Last chunk — take everything remaining
            chunk = text[start:].strip()
            if chunk:
                chunks.append(chunk)
            break

        # Search window: look back up to 20% of chunk size for a good break
        window_start = max(start, end - size // 5)
        window = text[window_start:end + 200]

        break_at = _find_break_point(window, end - window_start)
        break_at = window_start + break_at

        chunk = text[start:break_at].strip()
        if chunk:
            chunks.append(chunk)

        # Apply overlap: next chunk starts before the current end
        start = max(start + 1, break_at - overlap) if overlap > 0 else break_at

    return chunks


def _find_break_point(window: str, preferred_offset: int) -> int:
    """
    Find the best character offset within `window` to break at.

    Searches backward from `preferred_offset` for paragraph, sentence,
    then word boundaries. Returns `preferred_offset` if none found.
    """
    # 1. Paragraph break (double newline)
    idx = window.rfind("\n\n", 0, preferred_offset + 100)
    if idx > preferred_offset // 3:
        return idx + 2

    # 2. Single newline
    idx = window.rfind("\n", 0, preferred_offset + 50)
    if idx > preferred_offset // 3:
        return idx + 1

    # 3. Sentence boundary (period/!/? followed by space or end)
    for pattern in (r"[.!?]\s+", r"[.!?]$"):
        matches = list(re.finditer(pattern, window[:preferred_offset + 50]))
        if matches:
            m = matches[-1]
            if m.start() > preferred_offset // 3:
                return m.end()

    # 4. Word boundary
    idx = window.rfind(" ", 0, preferred_offset + 20)
    if idx > preferred_offset // 3:
        return idx + 1

    # No good break found — hard cut at preferred offset
    return preferred_offset


# ---------------------------------------------------------------------------
# Strategy: word count
# ---------------------------------------------------------------------------

def _split_by_words(text: str, word_count: int, overlap_words: int) -> list[str]:
    """Split text into groups of approximately `word_count` words."""
    words = text.split()
    if len(words) <= word_count:
        return [text]

    chunks: list[str] = []
    start = 0

    while start < len(words):
        end = min(start + word_count, len(words))
        chunk = " ".join(words[start:end])
        if chunk.strip():
            chunks.append(chunk.strip())

        if end >= len(words):
            break

        step = max(1, word_count - overlap_words) if overlap_words > 0 else word_count
        start += step

    return chunks


# ---------------------------------------------------------------------------
# Strategy: token count
# ---------------------------------------------------------------------------

def _split_by_tokens(
    text: str,
    token_count: int,
    overlap_tokens: int,
) -> tuple[list[str], Optional[str]]:
    """
    Split text at a target token count using tiktoken (cl100k_base).

    cl100k_base is the tokenizer for GPT-4 and is a reasonable approximation
    for other LLMs (Anthropic Claude, Gemini, etc.). Token counts will vary
    slightly between models but are generally within 10%.

    Falls back to word-based splitting if tiktoken is not installed,
    using a rough 0.75 words-per-token estimate.

    Returns: (chunks, warning_message_or_None)
    """
    warning = None

    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        token_ids = enc.encode(text)

        if len(token_ids) <= token_count:
            return [text], None

        chunks: list[str] = []
        start = 0

        while start < len(token_ids):
            end = min(start + token_count, len(token_ids))
            chunk_tokens = token_ids[start:end]
            chunk_text = enc.decode(chunk_tokens)

            if chunk_text.strip():
                chunks.append(chunk_text.strip())

            if end >= len(token_ids):
                break

            step = max(1, token_count - overlap_tokens) if overlap_tokens > 0 else token_count
            start += step

        return chunks, None

    except ImportError:
        # tiktoken not available — fall back to word count with approximation
        approx_words = int(token_count * 0.75)
        approx_overlap = int(overlap_tokens * 0.75)
        warning = (
            "tiktoken is not installed; token counting used an approximation "
            "(0.75 words per token). Install tiktoken for accurate token counts: "
            "pip install tiktoken"
        )
        return _split_by_words(text, approx_words, approx_overlap), warning


# ---------------------------------------------------------------------------
# Strategy: sentences
# ---------------------------------------------------------------------------

def _split_by_sentences(text: str, sentences_per_chunk: int) -> list[str]:
    """
    Split text into groups of `sentences_per_chunk` sentences.

    Uses spaCy if available (much better sentence boundary detection,
    especially for legal and technical text). Falls back to a regex
    sentence splitter that handles most common cases.

    AI PLUGIN POINT: The sentence detection here is the weakest link.
    For high-accuracy sentence splitting in legal or scientific text,
    a domain-specific NLP model would improve results significantly.
    """
    sentences = _split_sentences(text)

    if not sentences:
        return [text]

    chunks: list[str] = []
    for i in range(0, len(sentences), sentences_per_chunk):
        group = sentences[i:i + sentences_per_chunk]
        chunk = " ".join(s.strip() for s in group if s.strip())
        if chunk:
            chunks.append(chunk)

    return chunks


def _split_sentences(text: str) -> list[str]:
    """
    Split text into individual sentences.

    Tries spaCy first, falls back to regex.
    """
    # Try spaCy (much better accuracy)
    try:
        import spacy
        # Use the smallest English model — accurate enough for sentence splitting
        try:
            nlp = spacy.load("en_core_web_sm", disable=["ner", "tagger", "lemmatizer"])
        except OSError:
            # Model not downloaded — fall through to regex
            raise ImportError("spaCy model not found")

        # Process in chunks to handle very long documents within spaCy's limits
        doc = nlp(text[:1_000_000])  # spaCy has a default max length
        return [sent.text for sent in doc.sents]

    except (ImportError, Exception):
        pass

    # Regex sentence splitter fallback
    # Handles common abbreviations, initials, and decimal numbers
    sentence_endings = re.compile(
        r"(?<!\w\.\w.)"           # Not an abbreviation like U.S.A.
        r"(?<![A-Z][a-z]\.)"      # Not a name initial like Dr.
        r"(?<=\.|\!|\?)"          # After sentence-ending punctuation
        r"(?=\s+[A-Z\"'\u201c])"  # Followed by whitespace and capital letter
    )
    sentences = sentence_endings.split(text)
    return [s.strip() for s in sentences if s.strip()]


# ---------------------------------------------------------------------------
# Strategy: logical sections
# ---------------------------------------------------------------------------

def _split_by_sections(
    text: str,
    headings: list[Heading],
    max_section_size: int,
) -> list[str]:
    """
    Split text at document section boundaries using heading metadata.

    When the parser provides reliable heading data (DOCX, HTML), this is
    highly accurate. For PDFs and plain text the headings come from
    heuristic detection and may be less reliable.

    The strategy:
      1. Use heading char_offsets to define split points
      2. If no headings found, fall back to character splitting
      3. Apply max_section_size: force-split any section that is too long
    """
    if not headings:
        # No structural headings — return the whole text as one "section"
        # and let the caller decide to fall back
        return [text.strip()] if text.strip() else []

    # Filter out headings with very shallow content after them
    # (prevents a heading at the very end of the document creating an empty chunk)
    split_points = [0]
    for h in headings:
        if h.char_offset > 0:
            split_points.append(h.char_offset)
    split_points.append(len(text))
    split_points = sorted(set(split_points))

    raw_sections: list[str] = []
    for i in range(len(split_points) - 1):
        section = text[split_points[i]:split_points[i + 1]].strip()
        if section:
            raw_sections.append(section)

    # Enforce max section size by force-splitting oversized sections.
    # When we do split, we scan each sub-chunk for the first sub-heading
    # (Roman numeral or letter-section pattern) and use it to label that
    # chunk — so "STATEMENT OF THE CASE" splits become
    # "I. Factual Background", "II. School Disciplinary Proceedings", etc.
    if max_section_size > 0:
        final_sections: list[str] = []
        for section in raw_sections:
            if len(section) <= max_section_size:
                final_sections.append(section)
            else:
                sub_chunks = _split_by_characters(section, max_section_size, overlap=0)
                final_sections.extend(sub_chunks)
        return final_sections

    return raw_sections


def _find_first_subheading(text: str) -> Optional[str]:
    """
    Scan the first 25 lines of a chunk for a Roman-numeral or letter sub-heading.

    Used to give force-split chunks a more specific label than their parent
    section heading. Applies the same exclusions as the parser so that TOC
    dot-leader lines are not mistaken for sub-headings.

    Returns the cleaned sub-heading text, or None if none found.
    """
    import re
    from .parser import _is_never_heading, _clean_heading_label

    for line in text.split("\n")[:25]:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip dot-leader lines and other universal non-headings
        if _is_never_heading(stripped):
            continue
        if re.match(r"^[IVXLCDM]{1,6}\.\s+[A-Z]", stripped):
            return _clean_heading_label(stripped)
        if re.match(r"^[A-Z]\.\s+[A-Z]", stripped):
            return _clean_heading_label(stripped)
    return None


# ---------------------------------------------------------------------------
# Strategy: custom delimiter
# ---------------------------------------------------------------------------

def _split_by_delimiter(text: str, delimiter: str) -> list[str]:
    """Split text on a literal delimiter string."""
    # Unescape common escape sequences (\n, \t)
    delimiter = delimiter.replace("\\n", "\n").replace("\\t", "\t")

    parts = text.split(delimiter)
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------

def _merge_small_chunks(
    chunks: list[str],
    min_size: int,
    max_size: Optional[int] = None,
) -> list[str]:
    """
    Merge any chunk shorter than `min_size` into its predecessor.

    Runs until stable (handles runs of consecutive small chunks).
    Respects `max_size` ceiling: will not merge if the result would exceed it.
    """
    if not min_size or len(chunks) <= 1:
        return chunks

    result = list(chunks)
    changed = True

    while changed:
        changed = False
        for i in range(len(result)):
            if len(result[i]) < min_size:
                # Try merging backward (preferred: context flows forward)
                if i > 0:
                    merged = result[i - 1] + "\n\n" + result[i]
                    if max_size is None or len(merged) <= max_size:
                        result[i - 1:i + 1] = [merged]
                        changed = True
                        break
                # Fall back: merge forward
                if i < len(result) - 1:
                    merged = result[i] + "\n\n" + result[i + 1]
                    if max_size is None or len(merged) <= max_size:
                        result[i:i + 2] = [merged]
                        changed = True
                        break
                # Neither merge is possible — leave as-is

    return result


def _build_chunk_objects(
    raw_chunks: list[str],
    original_text: str,
    headings: list[Heading],
) -> list[Chunk]:
    """
    Convert raw string chunks into Chunk objects with metadata.

    Estimates character offsets (for large documents this is approximate
    since chunk boundaries don't always align perfectly with the original
    text after merging/splitting).
    """
    # Estimate token counts without tiktoken (4 chars ≈ 1 token heuristic)
    use_tiktoken = False
    enc = None
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        use_tiktoken = True
    except ImportError:
        pass

    # Build heading ranges for lookup
    heading_ranges = _build_heading_ranges(headings, len(original_text))

    result: list[Chunk] = []
    search_start = 0  # Used to find approximate offset in original text

    for i, text in enumerate(raw_chunks):
        if not text.strip():
            continue

        # Approximate character offset (find the chunk text in the original)
        offset = original_text.find(text[:50], search_start)
        if offset == -1:
            offset = search_start  # Fallback if not found exactly
        search_start = max(search_start, offset + len(text) - 50)

        char_start = offset
        char_end = offset + len(text)

        # Find the heading this chunk falls under.
        # If the parser gave a broad section heading (e.g. "STATEMENT OF THE
        # CASE") but the chunk itself opens with a sub-heading (e.g.
        # "I. Factual Background"), prefer the more specific label.
        #
        # Important guard: only apply the sub-heading finder when this chunk
        # is a CONTINUATION (force-split) chunk, i.e. the chunk text does NOT
        # start with the detected heading label. If the chunk starts with its
        # own heading (e.g. "TABLE OF CONTENTS\n..."), the heading_label is
        # already correct and we must not override it with a sub-heading found
        # inside the chunk body (which could be a TOC entry).
        heading_label = _find_heading_for_offset(char_start, heading_ranges)
        chunk_opens_with_heading = (
            heading_label is not None
            and text.lstrip().startswith(heading_label)
        )
        if not chunk_opens_with_heading:
            subheading = _find_first_subheading(text)
            if subheading:
                heading_label = subheading

        # Token count
        if use_tiktoken and enc:
            token_count = len(enc.encode(text))
        else:
            token_count = max(1, len(text) // 4)  # 4-char heuristic

        result.append(Chunk(
            index=i + 1,
            text=text,
            char_start=char_start,
            char_end=char_end,
            heading=heading_label,
            token_count=token_count,
            word_count=len(text.split()),
        ))

    return result


def _build_heading_ranges(headings: list[Heading], doc_length: int) -> list[tuple]:
    """
    Build (start, end, heading_text) tuples for fast heading lookup.
    """
    if not headings:
        return []

    ranges = []
    for i, h in enumerate(headings):
        start = h.char_offset
        end = headings[i + 1].char_offset if i + 1 < len(headings) else doc_length
        ranges.append((start, end, h.text))
    return ranges


def _find_heading_for_offset(char_offset: int, heading_ranges: list[tuple]) -> Optional[str]:
    """Return the heading text for the given character offset."""
    for start, end, text in heading_ranges:
        if start <= char_offset < end:
            return text
    return None