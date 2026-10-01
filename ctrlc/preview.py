#!/usr/bin/env python3
"""Serve one generated inspector on localhost, without exposing a directory."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


class InvalidPreviewDocumentError(ValueError):
    """The requested preview target is not a readable document file."""


def create_preview_server(document_path: str | Path, port: int = 8767) -> ThreadingHTTPServer:
    """Create a localhost-only server for one HTML document.

    The caller owns the returned standard-library server and can inspect its
    bound address before serving requests. Port zero asks the OS for a free port.
    """
    source = Path(document_path).resolve(strict=True)
    if not source.is_file():
        raise InvalidPreviewDocumentError("Preview document must be a file")
    with source.open("rb") as document:
        document.read(1)
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("Preview port must be an integer from 0 to 65535")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if urlsplit(self.path).path not in ("/", "/sample/inspector.html"):
                self.send_error(404)
                return
            try:
                content = source.read_bytes()
            except OSError:
                self.send_error(503)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
