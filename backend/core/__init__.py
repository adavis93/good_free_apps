"""
core/__init__.py

Exposes the public API for the chunker engine.
Platform adapters (Flask, FastAPI, Cloudflare Worker wrapper, etc.) should
import from here rather than calling individual modules directly.

Quick usage:
    from core import process_request, ProcessingError

    try:
        result_str, content_type = process_request(
            content=file_bytes,        # raw bytes of the uploaded file
            filename="brief.pdf",
            declared_mime="application/pdf",
            options={
                "method": "sections",
                "max_section_size": 8000,
                "min_chunk_size": 400,
                "output_format": "json",
            }
        )
    except ProcessingError as e:
        # Return e.message to the user with e.http_status
        ...
"""

from .engine import process_request, process_text, ProcessingError

__all__ = ["process_request", "process_text", "ProcessingError"]
