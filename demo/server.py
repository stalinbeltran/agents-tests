"""Servidor web mínimo (sólo biblioteca estándar) para la demo de subagentes.

Rutas:
  GET  /              -> la interfaz (static/index.html)
  GET  /api/config    -> modo activo (real | demo) y modelo
  POST /api/run       -> NDJSON en streaming con los eventos de la comparación

Uso:  python -m demo.server [--port 8000]
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import agents, runner

STATIC = Path(__file__).parent / "static"
MAX_CODE_BYTES = 40_000


class Handler(BaseHTTPRequestHandler):
    # HTTP/1.0: sin keep-alive, el navegador lee el stream hasta que cerramos.
    protocol_version = "HTTP/1.0"
    server_version = "SubagentesDemo/1.0"

    def log_message(self, fmt: str, *args) -> None:  # log de una línea, sin ruido
        sys.stderr.write("  %s\n" % (fmt % args))

    # -- helpers ----------------------------------------------------------
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    # -- rutas ------------------------------------------------------------
    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            html = (STATIC / "index.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
        elif self.path == "/api/config":
            self._json(
                200,
                {
                    "backend": runner.backend_mode(),
                    "model": agents.MODEL,
                    "effort": agents.EFFORT,
                    "sample_code": agents.SAMPLE_CODE,
                },
            )
        else:
            self._json(404, {"error": "no encontrado"})

    def do_POST(self) -> None:
        if self.path != "/api/run":
            self._json(404, {"error": "no encontrado"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_CODE_BYTES:
            self._json(413, {"error": "el fragmento de código es demasiado grande"})
            return

        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "JSON inválido"})
            return

        code = (payload.get("code") or "").strip() or agents.SAMPLE_CODE

        # Streaming NDJSON: una línea JSON por evento.
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        try:
            for event in runner.stream_comparison(code):
                self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # el navegador cerró la pestaña a mitad de la ejecución


def main() -> int:
    parser = argparse.ArgumentParser(description="Demo de subagentes de Claude")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    mode = runner.backend_mode()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    # flush explícito: si se redirige la salida a un fichero, el banner se
    # bufferaría y no se vería hasta que el proceso termine.
    print(f"Demo de subagentes escuchando en http://{args.host}:{args.port}", flush=True)
    print(
        f"  modo: {mode.upper()}  |  modelo: {agents.MODEL}  |  effort: {agents.EFFORT}",
        flush=True,
    )
    if mode == "demo":
        print("  (modo DEMO: respuestas simuladas, no se llama a la API)", flush=True)
    print("  Ctrl+C para parar.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nParando.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
