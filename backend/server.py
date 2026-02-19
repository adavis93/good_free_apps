"""
server.py — Flask HTTP adapter

This is the HTTP layer that wraps the platform-agnostic core engine.
It handles:
  - Multipart file upload parsing
  - JSON options parsing
  - CORS headers (required for browser-based uploads)
  - Rate limiting (in-memory; use Redis for multi-instance deployments)
  - Request/response lifecycle
  - Error responses

To run locally:
    pip install flask flask-cors
    python server.py

To deploy:
    - Railway / Render: this file is the entry point. Set PORT env var.
    - AWS Lambda: use the Mangum adapter with the FastAPI version instead.
    - Cloudflare Workers: use the JS wrapper in adapters/cloudflare/ instead
      (Workers don't run Python — the JS wrapper calls this as a subprocess
      or you deploy the Python service separately and proxy through Workers).

Environment variables:
    PORT              HTTP port (default: 8080)
    MAX_REQUESTS_PER_MIN  Rate limit per IP (default: 20)
    ALLOWED_ORIGINS   Comma-separated CORS origins (default: *)
    LOG_LEVEL         Logging level (default: INFO)
"""

import json
import logging
import os
import time
from collections import defaultdict
from typing import Optional

from flask import Flask, request, jsonify, Response
from flask_cors import CORS

from core import process_request, process_text, ProcessingError
from core.formatter import format_error

# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("chunker.server")

app = Flask(__name__)

# CORS: allow browser uploads from any origin by default.
# In production, restrict ALLOWED_ORIGINS to your frontend domain.
allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*")
CORS(app, origins=allowed_origins.split(","))

# ---------------------------------------------------------------------------
# In-memory rate limiter
# ---------------------------------------------------------------------------
# This is intentionally simple: a per-IP request counter with a 60-second
# sliding window. For multi-instance deployments, replace with Redis.
# The chunker is CPU-intensive for large PDFs, so rate limiting is important.

_rate_limit_store: dict[str, list[float]] = defaultdict(list)
MAX_REQUESTS_PER_MINUTE = int(os.environ.get("MAX_REQUESTS_PER_MIN", "20"))


def _check_rate_limit(ip: str) -> bool:
    """Return True if the request should be allowed, False if rate-limited."""
    now = time.monotonic()
    window = 60.0
    timestamps = _rate_limit_store[ip]

    # Drop timestamps older than the window
    _rate_limit_store[ip] = [t for t in timestamps if now - t < window]

    if len(_rate_limit_store[ip]) >= MAX_REQUESTS_PER_MINUTE:
        return False

    _rate_limit_store[ip].append(now)
    return True


def _get_client_ip() -> str:
    """Get the real client IP, respecting X-Forwarded-For from proxies."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    """Simple health check endpoint for load balancers and uptime monitors."""
    return jsonify({"ok": True, "service": "chunker"})


@app.route("/api/chunk", methods=["POST"])
def chunk_endpoint():
    """
    Main chunking endpoint.

    Accepts multipart/form-data with:
      file          (optional) The document file to process
      text          (optional) Plain text string — used if no file provided
      options       JSON string of chunking options

    One of `file` or `text` must be provided.

    Options JSON schema:
      {
        "method":           "characters" | "words" | "tokens" | "sentences" | "sections" | "delimiter"
        "size":             number   (chars/words/tokens/sentences per chunk)
        "overlap":          number   (overlap amount, same unit as size)
        "max_section_size": number   (sections mode only — hard cap per section)
        "min_chunk_size":   number   (merge chunks smaller than this)
        "delimiter":        string   (delimiter mode only)
        "output_format":    "json" | "text" | "csv"
        "preserve_headings": boolean
        "strip_page_numbers": boolean
      }

    Returns:
      On success: formatted output with Content-Type matching output_format
      On error:   JSON body with { ok: false, code: "...", message: "..." }
    """
    # ── Rate limit ────────────────────────────────────────────────────────
    client_ip = _get_client_ip()
    if not _check_rate_limit(client_ip):
        body = format_error(
            "Too many requests. Please wait a moment and try again.",
            code="RATE_LIMITED",
        )
        return Response(body, status=429, mimetype="application/json")

    # ── Parse options ─────────────────────────────────────────────────────
    options_raw = request.form.get("options", "{}")
    try:
        options = json.loads(options_raw)
        if not isinstance(options, dict):
            raise ValueError("options must be a JSON object")
    except (json.JSONDecodeError, ValueError) as e:
        body = format_error(f"Invalid options JSON: {e}", code="INVALID_OPTIONS")
        return Response(body, status=400, mimetype="application/json")

    # ── Determine input: file upload or text paste ─────────────────────────
    uploaded_file = request.files.get("file")
    pasted_text = request.form.get("text", "").strip()

    if uploaded_file and uploaded_file.filename:
        return _handle_file_upload(uploaded_file, options)
    elif pasted_text:
        return _handle_text_input(pasted_text, options)
    else:
        body = format_error(
            "No input provided. Send a file in the 'file' field or text in the 'text' field.",
            code="NO_INPUT",
        )
        return Response(body, status=400, mimetype="application/json")


def _handle_file_upload(uploaded_file, options: dict) -> Response:
    """Handle a multipart file upload."""
    filename = uploaded_file.filename or "upload"
    declared_mime = uploaded_file.content_type or None

    # Read file into memory — never write to disk
    try:
        content = uploaded_file.read()
    except Exception as e:
        logger.error("Failed to read upload stream", exc_info=False)
        body = format_error(
            "Failed to read the uploaded file.",
            code="READ_ERROR",
        )
        return Response(body, status=400, mimetype="application/json")

    try:
        output_str, content_type = process_request(
            content=content,
            filename=filename,
            declared_mime=declared_mime,
            options=options,
        )
        return Response(output_str, status=200, mimetype=content_type)

    except ProcessingError as e:
        body = format_error(e.message, code=e.code)
        return Response(body, status=e.http_status, mimetype="application/json")

    except Exception as e:
        # Catch-all for unexpected errors — never expose internal details
        logger.error("Unexpected error during file processing", exc_info=True)
        body = format_error(
            "An unexpected error occurred. Please try again.",
            code="SERVER_ERROR",
        )
        return Response(body, status=500, mimetype="application/json")


def _handle_text_input(text: str, options: dict) -> Response:
    """Handle a plain text paste."""
    try:
        output_str, content_type = process_text(text=text, options=options)
        return Response(output_str, status=200, mimetype=content_type)

    except ProcessingError as e:
        body = format_error(e.message, code=e.code)
        return Response(body, status=e.http_status, mimetype="application/json")

    except Exception as e:
        logger.error("Unexpected error during text processing", exc_info=True)
        body = format_error(
            "An unexpected error occurred. Please try again.",
            code="SERVER_ERROR",
        )
        return Response(body, status=500, mimetype="application/json")


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(413)
def too_large(e):
    """Flask raises 413 when Content-Length exceeds MAX_CONTENT_LENGTH."""
    body = format_error(
        "The uploaded file is too large. Maximum size is 50 MB.",
        code="SIZE_LIMIT_EXCEEDED",
    )
    return Response(body, status=413, mimetype="application/json")


@app.errorhandler(405)
def method_not_allowed(e):
    body = format_error("Method not allowed.", code="METHOD_NOT_ALLOWED")
    return Response(body, status=405, mimetype="application/json")


@app.errorhandler(404)
def not_found(e):
    body = format_error("Endpoint not found.", code="NOT_FOUND")
    return Response(body, status=404, mimetype="application/json")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    debug = os.environ.get("FLASK_ENV") == "development"

    # Set Flask's max content length to match our validator's limit (50 MB)
    # Flask will return 413 before we even read the body if exceeded
    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

    logger.info(f"Starting chunker server on port {port} (debug={debug})")
    app.run(host="0.0.0.0", port=port, debug=debug)
