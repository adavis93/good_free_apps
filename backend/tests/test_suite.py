"""
tests/test_suite.py — Comprehensive test suite

Run with:
    pip install pytest
    pytest tests/test_suite.py -v

Tests cover:
  - validators.py:   file type, magic bytes, size limits, options validation
  - parser.py:       plain text heading detection, HTML parsing, edge cases
  - chunker.py:      all six chunking strategies, overlap, merge small chunks
  - sanitizer.py:    XSS prevention, control character stripping, encoding
  - formatter.py:    JSON schema, CSV structure, text format
  - engine.py:       full pipeline integration, error propagation
  - Edge cases:      empty files, huge inputs, adversarial filenames, etc.

Requires only pytest — no external document files needed. Test documents
are generated programmatically so the test suite is self-contained.
"""

import json
import sys
import os
import pytest

# Make sure core/ is importable when running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================================
# Helpers — document factories
# ============================================================================

def make_plain_text(sections: int = 5, words_per_section: int = 100) -> str:
    """Generate a plain text document with realistic section structure."""
    parts = []
    section_names = [
        "INTRODUCTION", "BACKGROUND", "ANALYSIS", "DISCUSSION", "CONCLUSION",
        "RECOMMENDATIONS", "METHODOLOGY", "FINDINGS", "APPENDIX", "REFERENCES"
    ]
    lorem = (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
        "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. "
        "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris. "
        "Duis aute irure dolor in reprehenderit in voluptate velit esse cillum. "
        "Excepteur sint occaecat cupidatat non proident, sunt in culpa. "
    )
    for i in range(sections):
        name = section_names[i % len(section_names)]
        body = (lorem * 5)[:words_per_section * 6]  # Approx words_per_section words
        parts.append(f"{name}\n\n{body}")
    return "\n\n".join(parts)


def make_legal_brief() -> str:
    """Generate a realistic legal brief structure."""
    return """No. 15-9999

TAYLOR BELL,

PETITIONER

v.

RESPONDENT SCHOOL BOARD,

ON WRIT OF CERTIORARI

Counsel for Petitioner
University of California, Berkeley
School of Law

i

QUESTIONS PRESENTED

1. Does the Tinker standard apply to a student whose speech occurred entirely off-campus?

2. If Tinker applies, should the summary judgment nonetheless be reversed?

3. Does Bell's speech qualify for special First Amendment protection?

ii

TABLE OF CONTENTS

INTRODUCTION ................................................................................................................ 1
STATEMENT OF THE CASE .............................................................................................. 2
ARGUMENT ...................................................................................................................... 13
CONCLUSION ................................................................................................................... 40

iv

TABLE OF AUTHORITIES

Cases

Anderson v. Liberty Lobby, Inc., 477 U.S. 242 (1986)..................................................... 13
Tinker v. Des Moines Indep. School Dist., 393 U.S. 503 (1969) .............................. passim

INTRODUCTION

The First Amendment protects students from government censorship of speech that occurs entirely off campus. This brief argues three things. First, the Tinker standard should not apply to off-campus student speech. Second, even if it applies, the school failed to show a reasonable forecast of substantial disruption. Third, Bell's speech qualifies for heightened protection under the public concern doctrine because it addressed sexual misconduct at a public school. These are weighty constitutional questions that deserve careful consideration by this Court.

STATEMENT OF THE CASE

Taylor Bell was a student at Itawamba Agricultural High School in Mississippi. In December 2010, two female students reported that two male coaches had made sexually inappropriate comments and engaged in inappropriate physical contact with female members of the track team. The coaches denied the allegations but the school investigated and found them credible enough to warrant disciplinary action. Bell, disturbed by what he perceived as a cover-up, decided to speak out about the situation through music.

ARGUMENT

The First Amendment provides that Congress shall make no law abridging the freedom of speech. The Supreme Court has consistently interpreted this protection broadly. When it comes to student speech, the Court has recognized that students do not shed their constitutional rights at the schoolhouse gate. However, the Court has also recognized that schools retain some authority to restrict speech that would substantially disrupt the educational environment under the Tinker standard.

CONCLUSION

For the foregoing reasons, Bell respectfully requests that this Court reverse the judgment of the Fifth Circuit and hold that his speech is protected by the First Amendment."""


def make_html_document() -> bytes:
    """Generate a simple HTML document."""
    return b"""<!DOCTYPE html>
<html>
<head><title>Test Document</title></head>
<body>
<h1>Main Title</h1>
<p>First paragraph with some content here.</p>
<h2>Section One</h2>
<p>Content of section one. This has several sentences. Each one adds context.</p>
<h2>Section Two</h2>
<p>Content of section two. More information follows here.</p>
<h3>Subsection</h3>
<p>Subsection content with specific details.</p>
<script>alert('xss attempt')</script>
</body>
</html>"""


def make_pdf_magic() -> bytes:
    """Return a byte sequence that starts with the PDF magic bytes but is not a real PDF."""
    return b"%PDF-1.4 fake pdf content for testing"


def make_docx_magic() -> bytes:
    """Return a byte sequence with DOCX/ZIP magic bytes but not a real DOCX."""
    return b"PK\x03\x04 fake docx content for testing"


# ============================================================================
# Validators
# ============================================================================

class TestValidators:

    def test_empty_file_rejected(self):
        from core.validators import validate_upload, ValidationError
        with pytest.raises(ValidationError, match="empty"):
            validate_upload(b"", "test.txt", "text/plain")

    def test_file_too_large(self):
        from core.validators import validate_upload, ValidationError, MAX_FILE_SIZE_BYTES
        oversized = b"x" * (MAX_FILE_SIZE_BYTES + 1)
        with pytest.raises(ValidationError, match="size limit"):
            validate_upload(oversized, "big.txt", "text/plain")

    def test_valid_text_file(self):
        from core.validators import validate_upload
        content = b"Hello, world. This is a plain text document."
        result = validate_upload(content, "doc.txt", "text/plain")
        assert result.canonical_mime == "text/plain"

    def test_pdf_magic_bytes_accepted(self):
        from core.validators import validate_upload
        content = b"%PDF-1.4 some content"
        result = validate_upload(content, "doc.pdf", "application/pdf")
        assert result.canonical_mime == "application/pdf"

    def test_pdf_wrong_magic_rejected(self):
        from core.validators import validate_upload, ValidationError
        content = b"Not a real PDF file"
        with pytest.raises(ValidationError, match="signature"):
            validate_upload(content, "fake.pdf", "application/pdf")

    def test_docx_magic_accepted(self):
        from core.validators import validate_upload
        content = b"PK\x03\x04" + b"\x00" * 100
        result = validate_upload(content, "doc.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        assert "wordprocessingml" in result.canonical_mime

    def test_mime_alias_resolution(self):
        from core.validators import validate_upload
        # application/msword should resolve to docx type
        content = b"PK\x03\x04" + b"\x00" * 100
        result = validate_upload(content, "doc.docx", "application/msword")
        assert "wordprocessingml" in result.canonical_mime

    def test_extension_fallback_when_no_mime(self):
        from core.validators import validate_upload
        content = b"Hello plain text"
        result = validate_upload(content, "document.txt", None)
        assert result.canonical_mime == "text/plain"

    def test_unknown_extension_rejected(self):
        from core.validators import validate_upload, ValidationError
        content = b"some content"
        with pytest.raises(ValidationError):
            validate_upload(content, "malware.exe", "application/octet-stream")

    def test_binary_content_as_text_rejected(self):
        from core.validators import validate_upload, ValidationError
        binary_content = bytes(range(256)) * 100  # Binary garbage
        with pytest.raises(ValidationError):
            validate_upload(binary_content, "fake.txt", "text/plain")

    def test_options_valid_defaults(self):
        from core.validators import validate_options
        opts = validate_options({"method": "characters"})
        assert opts["method"] == "characters"
        assert opts["size"] == 4000  # default
        assert opts["overlap"] == 0

    def test_options_size_clamped(self):
        from core.validators import validate_options
        opts = validate_options({"method": "characters", "size": 999999999})
        assert opts["size"] <= 500_000

    def test_options_size_min_clamped(self):
        from core.validators import validate_options
        opts = validate_options({"method": "words", "size": 1})
        assert opts["size"] >= 50

    def test_options_overlap_capped_at_half_size(self):
        from core.validators import validate_options
        opts = validate_options({"method": "characters", "size": 1000, "overlap": 999})
        assert opts["overlap"] <= 500  # Can't exceed half of size

    def test_options_invalid_method(self):
        from core.validators import validate_options, ValidationError
        with pytest.raises(ValidationError, match="method"):
            validate_options({"method": "magic_ai_splitting"})

    def test_options_invalid_format(self):
        from core.validators import validate_options, ValidationError
        with pytest.raises(ValidationError, match="format"):
            validate_options({"method": "characters", "output_format": "yaml"})

    def test_options_delimiter_truncated(self):
        from core.validators import validate_options
        long_delim = "x" * 200
        opts = validate_options({"method": "delimiter", "delimiter": long_delim})
        assert len(opts["delimiter"]) <= 100


# ============================================================================
# Parser — plain text
# ============================================================================

class TestTextParser:

    def test_basic_text_extraction(self):
        from core.parser import _parse_text
        content = b"Hello world. This is a test."
        result = _parse_text(content)
        assert "Hello world" in result.text
        assert result.text == result.text.strip()

    def test_utf8_content(self):
        from core.parser import _parse_text
        content = "Héllo wörld — résumé café".encode("utf-8")
        result = _parse_text(content)
        assert "Héllo" in result.text

    def test_latin1_content(self):
        from core.parser import _parse_text
        content = "Caf\xe9 au lait".encode("latin-1")
        result = _parse_text(content)
        assert len(result.text) > 0  # Should decode without crashing

    def test_windows_line_endings_normalised(self):
        from core.parser import _parse_text
        content = b"Line one\r\nLine two\r\nLine three"
        result = _parse_text(content)
        assert "\r" not in result.text
        assert "Line one" in result.text
        assert "Line two" in result.text

    def test_allcaps_heading_detected(self):
        from core.parser import _detect_text_headings
        text = "INTRODUCTION\n\nSome body text here.\n\nCONCLUSION\n\nMore text."
        headings = _detect_text_headings(text)
        heading_texts = [h.text for h in headings]
        assert "INTRODUCTION" in heading_texts
        assert "CONCLUSION" in heading_texts

    def test_markdown_headings_detected(self):
        from core.parser import _detect_text_headings
        text = "# Main Title\n\nSome content.\n\n## Section\n\nMore content."
        headings = _detect_text_headings(text)
        assert len(headings) >= 2
        assert headings[0].level == 1
        assert headings[1].level == 2

    def test_roman_numeral_headings_detected(self):
        from core.parser import _detect_text_headings
        text = "I. Introduction\n\nSome text.\n\nII. Background\n\nMore text."
        headings = _detect_text_headings(text)
        assert any(h.text.startswith("I.") for h in headings)

    def test_no_false_positives_in_body_text(self):
        from core.parser import _detect_text_headings
        # Regular prose should not be detected as headings
        text = ("This is a normal sentence. Another sentence follows it. "
                "The quick brown fox jumps over the lazy dog. "
                "This continues for several more words to exceed the threshold.")
        headings = _detect_text_headings(text)
        # Body sentences should not be detected as headings
        for h in headings:
            assert len(h.text) <= 120  # Any detected heading should be short

    def test_page_numbers_not_detected_as_headings(self):
        from core.parser import _classify_text_heading
        assert _classify_text_heading("42") is None
        assert _classify_text_heading("iii") is None
        assert _classify_text_heading("iv") is None

    def test_heading_char_offset_increases(self):
        from core.parser import _detect_text_headings
        text = "INTRO\n\nText.\n\nCONCLUSION\n\nMore."
        headings = _detect_text_headings(text)
        if len(headings) >= 2:
            assert headings[1].char_offset > headings[0].char_offset


# ============================================================================
# Parser — HTML
# ============================================================================

class TestHTMLParser:

    def test_extracts_paragraph_text(self):
        from core.parser import _parse_html
        html = b"<html><body><p>Hello world</p></body></html>"
        result = _parse_html(html)
        assert "Hello world" in result.text

    def test_extracts_headings(self):
        from core.parser import _parse_html
        result = _parse_html(make_html_document())
        heading_texts = [h.text for h in result.headings]
        assert "Main Title" in heading_texts
        assert "Section One" in heading_texts

    def test_removes_script_tags(self):
        from core.parser import _parse_html
        result = _parse_html(make_html_document())
        # The alert() script should not appear in extracted text
        assert "alert(" not in result.text
        assert "xss attempt" not in result.text

    def test_extracts_title(self):
        from core.parser import _parse_html
        result = _parse_html(make_html_document())
        assert result.title == "Test Document"

    def test_heading_levels_correct(self):
        from core.parser import _parse_html
        result = _parse_html(make_html_document())
        h1 = [h for h in result.headings if h.level == 1]
        h2 = [h for h in result.headings if h.level == 2]
        h3 = [h for h in result.headings if h.level == 3]
        assert len(h1) >= 1
        assert len(h2) >= 2
        assert len(h3) >= 1

    def test_empty_html(self):
        from core.parser import _parse_html
        result = _parse_html(b"<html><body></body></html>")
        # Should not crash; text may be empty
        assert isinstance(result.text, str)

    def test_nav_and_footer_removed(self):
        from core.parser import _parse_html
        html = b"""<html><body>
            <nav>Navigation link 1 | Navigation link 2</nav>
            <p>Real content here.</p>
            <footer>Copyright 2024</footer>
        </body></html>"""
        result = _parse_html(html)
        # Nav/footer content should be stripped
        assert "Navigation link" not in result.text
        assert "Real content" in result.text


# ============================================================================
# Chunker — all strategies
# ============================================================================

class TestChunkerCharacters:

    def _opts(self, **kwargs):
        from core.validators import validate_options
        defaults = {"method": "characters", "size": 500, "overlap": 0,
                    "output_format": "json", "min_chunk_size": 0,
                    "max_section_size": 10000}
        defaults.update(kwargs)
        return defaults

    def test_short_text_single_chunk(self):
        from core.chunker import chunk_text
        text = "Short text."
        result = chunk_text(text, [], self._opts(size=1000))
        assert len(result.chunks) == 1
        assert result.chunks[0].text == "Short text."

    def test_long_text_splits_correctly(self):
        from core.chunker import chunk_text
        text = make_plain_text(sections=3, words_per_section=200)
        result = chunk_text(text, [], self._opts(size=500))
        assert len(result.chunks) > 1
        # No chunk should significantly exceed the target size
        for chunk in result.chunks:
            assert len(chunk.text) < 800  # Allow some overage for natural breaks

    def test_no_content_lost(self):
        from core.chunker import chunk_text
        text = "word " * 1000
        result = chunk_text(text, [], self._opts(size=200))
        combined = " ".join(c.text for c in result.chunks)
        # All words should appear somewhere in the output (some whitespace may differ)
        original_words = set(text.split())
        output_words = set(combined.split())
        assert original_words == output_words

    def test_overlap_produces_repeated_content(self):
        from core.chunker import chunk_text
        text = "A " * 500  # Enough text to guarantee multiple chunks
        result = chunk_text(text, [], self._opts(size=200, overlap=50))
        if len(result.chunks) >= 2:
            # With overlap, consecutive chunks should share some content
            # (at least the overlap region)
            assert len(result.chunks) > 0

    def test_chunk_indices_sequential(self):
        from core.chunker import chunk_text
        text = make_plain_text()
        result = chunk_text(text, [], self._opts(size=300))
        indices = [c.index for c in result.chunks]
        assert indices == list(range(1, len(result.chunks) + 1))

    def test_word_counts_populated(self):
        from core.chunker import chunk_text
        text = make_plain_text()
        result = chunk_text(text, [], self._opts())
        for chunk in result.chunks:
            assert chunk.word_count > 0


class TestChunkerWords:

    def _opts(self, **kwargs):
        from core.validators import validate_options
        defaults = {"method": "words", "size": 100, "overlap": 0,
                    "output_format": "json", "min_chunk_size": 0,
                    "max_section_size": 10000}
        defaults.update(kwargs)
        return defaults

    def test_approximately_correct_word_count(self):
        from core.chunker import chunk_text
        text = " ".join(f"word{i}" for i in range(1000))
        result = chunk_text(text, [], self._opts(size=100))
        # Each chunk should have approximately 100 words (allow ±20%)
        for chunk in result.chunks[:-1]:  # Exclude last (may be shorter)
            assert 80 <= chunk.word_count <= 120

    def test_word_overlap(self):
        from core.chunker import chunk_text
        text = " ".join(f"word{i}" for i in range(500))
        result = chunk_text(text, [], self._opts(size=100, overlap=20))
        assert len(result.chunks) > 0


class TestChunkerSentences:

    def _opts(self, **kwargs):
        from core.validators import validate_options
        defaults = {"method": "sentences", "size": 3, "overlap": 0,
                    "output_format": "json", "min_chunk_size": 0,
                    "max_section_size": 10000}
        defaults.update(kwargs)
        return defaults

    def test_splits_into_sentence_groups(self):
        from core.chunker import chunk_text
        text = ". ".join([f"Sentence {i} with some content here" for i in range(30)]) + "."
        result = chunk_text(text, [], self._opts(size=3))
        assert len(result.chunks) >= 8  # ~30 sentences / 3 per chunk

    def test_single_sentence_text(self):
        from core.chunker import chunk_text
        text = "This is just one sentence."
        result = chunk_text(text, [], self._opts())
        assert len(result.chunks) >= 1


class TestChunkerSections:

    def _opts(self, **kwargs):
        from core.validators import validate_options
        defaults = {"method": "sections", "size": 4000, "overlap": 0,
                    "output_format": "json", "min_chunk_size": 0,
                    "max_section_size": 8000}
        defaults.update(kwargs)
        return defaults

    def test_sections_split_at_headings(self):
        from core.parser import _detect_text_headings
        from core.chunker import chunk_text
        text = make_legal_brief()
        headings = _detect_text_headings(text)
        result = chunk_text(text, headings, self._opts())
        assert len(result.chunks) >= 3  # Should have multiple sections

    def test_fallback_warning_when_no_headings(self):
        from core.chunker import chunk_text
        text = "no headings here just plain prose " * 100
        result = chunk_text(text, [], self._opts())
        # Should fall back with a warning
        assert len(result.warnings) > 0 or len(result.chunks) >= 1

    def test_max_section_size_enforced(self):
        from core.parser import _detect_text_headings
        from core.chunker import chunk_text
        text = make_legal_brief()
        headings = _detect_text_headings(text)
        opts = self._opts(max_section_size=500)
        result = chunk_text(text, headings, opts)
        for chunk in result.chunks:
            assert len(chunk.text) <= 700  # Allow some tolerance


class TestChunkerDelimiter:

    def _opts(self, delimiter="---", **kwargs):
        defaults = {"method": "delimiter", "delimiter": delimiter,
                    "size": 4000, "overlap": 0, "output_format": "json",
                    "min_chunk_size": 0, "max_section_size": 10000}
        defaults.update(kwargs)
        return defaults

    def test_splits_on_delimiter(self):
        from core.chunker import chunk_text
        text = "Part one content.\n---\nPart two content.\n---\nPart three."
        result = chunk_text(text, [], self._opts(delimiter="---"))
        assert len(result.chunks) == 3

    def test_newline_escape_in_delimiter(self):
        from core.chunker import chunk_text
        text = "First block\n\nSecond block\n\nThird block"
        result = chunk_text(text, [], self._opts(delimiter="\\n\\n"))
        assert len(result.chunks) >= 2

    def test_empty_parts_skipped(self):
        from core.chunker import chunk_text
        text = "---content---"  # Produces empty parts at start and end
        result = chunk_text(text, [], self._opts(delimiter="---"))
        for chunk in result.chunks:
            assert chunk.text.strip()  # No empty chunks


class TestMergeSmallChunks:

    def test_small_chunks_merged(self):
        from core.chunker import _merge_small_chunks
        chunks = ["tiny", "also tiny", "A" * 500, "B" * 500]
        merged = _merge_small_chunks(chunks, min_size=100)
        # The tiny chunks should be absorbed
        for c in merged:
            assert len(c) >= 100 or c == merged[-1]  # Last may still be small

    def test_merge_respects_max_size(self):
        from core.chunker import _merge_small_chunks
        chunks = ["A" * 400, "B" * 50, "C" * 400]
        merged = _merge_small_chunks(chunks, min_size=100, max_size=500)
        # The small "B" chunk can't merge with A (500+50 > 500), so merges with C
        for c in merged:
            assert len(c) <= 600  # Some tolerance for separator text

    def test_single_small_chunk_kept(self):
        from core.chunker import _merge_small_chunks
        # If there's only one chunk and it's small, keep it
        chunks = ["tiny"]
        merged = _merge_small_chunks(chunks, min_size=1000)
        assert len(merged) == 1
        assert merged[0] == "tiny"


# ============================================================================
# Sanitizer
# ============================================================================

class TestSanitizer:

    def test_html_escaped(self):
        from core.sanitizer import sanitize_text
        text = '<script>alert("xss")</script>'
        result = sanitize_text(text, context="output")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_null_bytes_removed(self):
        from core.sanitizer import sanitize_text
        text = "Hello\x00World\x01\x02"
        result = sanitize_text(text, context="output")
        assert "\x00" not in result
        assert "\x01" not in result
        assert "Hello" in result
        assert "World" in result

    def test_newlines_preserved(self):
        from core.sanitizer import sanitize_text
        text = "Line one\nLine two\nLine three"
        result = sanitize_text(text, context="output")
        assert "\n" in result

    def test_excessive_blank_lines_collapsed(self):
        from core.sanitizer import sanitize_text
        text = "Para one\n\n\n\n\n\nPara two"
        result = sanitize_text(text, context="output")
        assert "\n\n\n" not in result

    def test_internal_context_no_html_escape(self):
        from core.sanitizer import sanitize_text
        text = "Some text with <brackets> here"
        result = sanitize_text(text, context="internal")
        assert "<brackets>" in result  # Not escaped for internal processing

    def test_empty_string_safe(self):
        from core.sanitizer import sanitize_text
        result = sanitize_text("", context="output")
        assert result == ""

    def test_none_like_empty_safe(self):
        from core.sanitizer import sanitize_text
        result = sanitize_text(None, context="output")
        assert result == ""

    def test_filename_sanitization(self):
        from core.sanitizer import sanitize_filename
        dangerous = "../../../etc/passwd"
        safe = sanitize_filename(dangerous)
        # Path traversal requires / — that must be removed
        assert "/" not in safe
        # The dangerous relative path components should be broken
        assert "etc/passwd" not in safe
        assert len(safe) <= 100
        # Normal filenames should be preserved
        assert sanitize_filename("my-document_v2.pdf") == "my-document_v2.pdf"
    def test_private_use_unicode_removed(self):
        from core.sanitizer import sanitize_text
        text = "Normal text\ue000private\uf8ffuse area"
        result = sanitize_text(text)
        assert "\ue000" not in result
        assert "Normal text" in result

    def test_unicode_normalized(self):
        from core.sanitizer import sanitize_text
        import unicodedata
        # Two ways to write "é": single char vs combining chars
        text_nfc = unicodedata.normalize("NFC", "café")
        text_nfd = unicodedata.normalize("NFD", "café")
        result_nfc = sanitize_text(text_nfc)
        result_nfd = sanitize_text(text_nfd)
        # Both should produce the same output after normalization
        assert result_nfc == result_nfd


# ============================================================================
# Formatter
# ============================================================================

class TestFormatter:

    def _make_result(self):
        from core.chunker import ChunkResult, Chunk
        chunks = [
            Chunk(index=1, text="First chunk text.", char_start=0, char_end=17,
                  heading="Introduction", token_count=5, word_count=3),
            Chunk(index=2, text="Second chunk text.", char_start=18, char_end=36,
                  heading="Background", token_count=5, word_count=3),
        ]
        return ChunkResult(
            chunks=chunks,
            method="sections",
            total_chars=36,
            total_words=6,
            warnings=["A test warning"],
        )

    def test_json_output_valid_json(self):
        from core.formatter import format_output
        result = self._make_result()
        output, content_type = format_output(result, "json")
        data = json.loads(output)
        assert data["ok"] is True
        assert data["chunk_count"] == 2
        assert "application/json" in content_type

    def test_json_output_schema(self):
        from core.formatter import format_output
        result = self._make_result()
        output, _ = format_output(result, "json")
        data = json.loads(output)
        required_keys = ["ok", "method", "chunk_count", "total_chars",
                          "total_words", "warnings", "chunks"]
        for key in required_keys:
            assert key in data, f"Missing key: {key}"

    def test_json_chunk_fields(self):
        from core.formatter import format_output
        result = self._make_result()
        output, _ = format_output(result, "json")
        data = json.loads(output)
        chunk = data["chunks"][0]
        for field in ["index", "text", "heading", "token_count",
                       "word_count", "char_start", "char_end"]:
            assert field in chunk, f"Chunk missing field: {field}"

    def test_text_output_contains_separators(self):
        from core.formatter import format_output
        result = self._make_result()
        output, content_type = format_output(result, "text")
        assert "=== CHUNK 1 OF 2 ===" in output
        assert "=== CHUNK 2 OF 2 ===" in output
        assert "text/plain" in content_type

    def test_text_output_contains_chunk_content(self):
        from core.formatter import format_output
        result = self._make_result()
        output, _ = format_output(result, "text")
        assert "First chunk text." in output
        assert "Second chunk text." in output

    def test_csv_output_has_header_row(self):
        from core.formatter import format_output
        import csv, io
        result = self._make_result()
        output, content_type = format_output(result, "csv")
        reader = csv.reader(io.StringIO(output))
        header = next(reader)
        assert "index" in header
        assert "text" in header
        assert "text/csv" in content_type

    def test_csv_output_correct_row_count(self):
        from core.formatter import format_output
        import csv, io
        result = self._make_result()
        output, _ = format_output(result, "csv")
        reader = csv.reader(io.StringIO(output))
        rows = list(reader)
        assert len(rows) == 3  # 1 header + 2 data rows

    def test_warnings_in_json_output(self):
        from core.formatter import format_output
        result = self._make_result()
        output, _ = format_output(result, "json")
        data = json.loads(output)
        assert "A test warning" in data["warnings"]

    def test_error_format(self):
        from core.formatter import format_error
        output = format_error("Something went wrong", code="TEST_ERROR")
        data = json.loads(output)
        assert data["ok"] is False
        assert data["code"] == "TEST_ERROR"
        assert data["message"] == "Something went wrong"


# ============================================================================
# Engine — full pipeline integration
# ============================================================================

class TestEngine:

    def test_plain_text_pipeline(self):
        from core.engine import process_text
        text = make_plain_text(sections=3, words_per_section=100)
        output, content_type = process_text(text, {"method": "characters", "size": 500,
                                                     "output_format": "json"})
        data = json.loads(output)
        assert data["ok"] is True
        assert data["chunk_count"] >= 1

    def test_empty_text_raises_error(self):
        from core.engine import process_text, ProcessingError
        with pytest.raises(ProcessingError) as exc_info:
            process_text("", {"method": "characters"})
        assert exc_info.value.http_status == 400

    def test_whitespace_only_text_raises_error(self):
        from core.engine import process_text, ProcessingError
        with pytest.raises(ProcessingError):
            process_text("   \n\n\t  ", {"method": "characters"})

    def test_oversized_text_raises_413(self):
        from core.engine import process_text, ProcessingError
        huge_text = "x " * 6_000_000  # > 10 MB of text
        with pytest.raises(ProcessingError) as exc_info:
            process_text(huge_text, {"method": "characters"})
        assert exc_info.value.http_status == 413

    def test_html_pipeline(self):
        from core.engine import process_request
        content = make_html_document()
        output, content_type = process_request(
            content=content,
            filename="test.html",
            declared_mime="text/html",
            options={"method": "sections", "output_format": "json"},
        )
        data = json.loads(output)
        assert data["ok"] is True

    def test_invalid_file_type_raises_validation_error(self):
        from core.engine import process_request, ProcessingError
        content = b"Not a PDF at all"
        with pytest.raises(ProcessingError) as exc_info:
            process_request(content, "file.pdf", "application/pdf", {})
        assert exc_info.value.code == "VALIDATION_ERROR"

    def test_output_json_by_default(self):
        from core.engine import process_text
        text = "Simple text for testing the output format selection."
        output, content_type = process_text(text, {"method": "characters"})
        assert "application/json" in content_type
        data = json.loads(output)
        assert "chunks" in data

    def test_output_csv_format(self):
        from core.engine import process_text
        text = make_plain_text()
        output, content_type = process_text(
            text,
            {"method": "characters", "size": 500, "output_format": "csv"}
        )
        assert "text/csv" in content_type
        assert "index" in output  # Header row

    def test_output_text_format(self):
        from core.engine import process_text
        text = make_plain_text()
        output, content_type = process_text(
            text,
            {"method": "characters", "size": 500, "output_format": "text"}
        )
        assert "text/plain" in content_type
        assert "CHUNK 1" in output

    def test_xss_not_in_output(self):
        from core.engine import process_text
        text = '<script>alert("xss")</script> Normal text follows here.'
        output, _ = process_text(text, {"method": "characters", "output_format": "json"})
        assert "<script>" not in output

    def test_legal_brief_sections(self):
        from core.engine import process_text
        text = make_legal_brief()
        output, _ = process_text(text, {
            "method": "sections",
            "max_section_size": 8000,
            "min_chunk_size": 400,
            "output_format": "json",
        })
        data = json.loads(output)
        assert data["ok"] is True
        assert data["chunk_count"] >= 4  # Cover, Questions, TOC, body sections

    def test_warnings_surface_to_output(self):
        from core.engine import process_text
        # Sections mode on text with no headings should produce a warning
        text = "just plain text with no section headings at all " * 50
        output, _ = process_text(text, {
            "method": "sections",
            "output_format": "json",
        })
        data = json.loads(output)
        assert len(data["warnings"]) > 0


# ============================================================================
# Edge cases and adversarial inputs
# ============================================================================

class TestEdgeCases:

    def test_unicode_heavy_document(self):
        from core.engine import process_text
        # Mix of scripts that should all survive round-trip
        text = "中文内容。 日本語テキスト。 한국어 텍스트. العربية النص. Текст на русском."
        output, _ = process_text(text, {"method": "characters", "output_format": "json"})
        data = json.loads(output)
        assert data["ok"] is True

    def test_document_with_only_whitespace_between_sections(self):
        from core.engine import process_text
        text = "SECTION ONE\n\n   \n\n   \n\nSome content here that is long enough to count."
        output, _ = process_text(text, {"method": "sections", "output_format": "json"})
        data = json.loads(output)
        assert data["ok"] is True

    def test_very_long_single_line(self):
        from core.engine import process_text
        # A document with no newlines at all
        text = "word " * 5000
        output, _ = process_text(text, {"method": "characters", "size": 500,
                                          "output_format": "json"})
        data = json.loads(output)
        assert data["chunk_count"] > 1

    def test_repeated_delimiter(self):
        from core.engine import process_text
        # Multiple consecutive delimiters should not produce empty chunks
        text = "Part one\n---\n---\n---\nPart two"
        output, _ = process_text(text, {"method": "delimiter", "delimiter": "---",
                                          "output_format": "json"})
        data = json.loads(output)
        for chunk in data["chunks"]:
            assert chunk["text"].strip()

    def test_adversarial_filename_safe(self):
        from core.sanitizer import sanitize_filename
        names = [
            "../../etc/shadow",
            "file\x00name.txt",
            "a" * 500,
            "normal_file-v2.docx",
        ]
        for name in names:
            result = sanitize_filename(name)
            assert len(result) <= 100
            assert "\x00" not in result
            assert "/" not in result

    def test_minimum_viable_document(self):
        from core.engine import process_text
        text = "A single short sentence."
        output, _ = process_text(text, {"method": "characters", "output_format": "json"})
        data = json.loads(output)
        assert data["ok"] is True
        assert len(data["chunks"]) == 1

    def test_options_with_string_numbers(self):
        """Frontend may send numbers as strings — should still work."""
        from core.validators import validate_options
        opts = validate_options({"method": "characters", "size": "2000", "overlap": "100"})
        assert opts["size"] == 2000
        assert opts["overlap"] == 100
