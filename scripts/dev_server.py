"""
dev_server.py – Servidor de desarrollo local para gemamx-webapp
Replica la estructura de volúmenes del contenedor Docker:

  /             → webapp/
  /data/        → results/data/        (contrato vigente)
  /runs/        → results/runs/        (historial de corridas)
  /external/    → results/external/    (datasets externos, si existe)

Uso:
  python3 scripts/dev_server.py [--port 8099] [--root d:/ProyectosIA/gemamx_nf]

Acceder en: http://localhost:8099
"""

import argparse
import http.server
import os
import pathlib
import sys
import urllib.parse
from http import HTTPStatus


def resolve_path(root: pathlib.Path, url_path: str) -> pathlib.Path | None:
    """
    Mapea una URL path al sistema de archivos según las reglas de volumen:
      /data/...     → results/data/...
      /runs/...     → results/runs/...
      /external/... → results/external/...
      /...          → webapp/...
    Devuelve None si la ruta no existe.
    """
    # Decodificar URL
    decoded = urllib.parse.unquote(url_path)
    # Quitar query string
    decoded = decoded.split('?')[0]

    if decoded.startswith('/data/'):
        candidate = root / 'results' / 'data' / decoded[6:]
    elif decoded.startswith('/runs/'):
        candidate = root / 'results' / 'runs' / decoded[6:]
    elif decoded.startswith('/external/'):
        candidate = root / 'results' / 'external' / decoded[10:]
    else:
        rel = decoded.lstrip('/')
        candidate = root / 'webapp' / (rel or 'index.html')
        # SPA fallback: si no existe, servir index.html
        if not candidate.exists() and not decoded.startswith('/favicon'):
            fallback = root / 'webapp' / 'index.html'
            if fallback.exists():
                return fallback

    # Directorio → index.html
    if candidate.is_dir():
        candidate = candidate / 'index.html'

    return candidate if candidate.exists() else None


MIME = {
    '.html': 'text/html; charset=utf-8',
    '.js':   'application/javascript; charset=utf-8',
    '.css':  'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.svg':  'image/svg+xml',
    '.png':  'image/png',
    '.ico':  'image/x-icon',
    '.pdb':  'text/plain',
    '.cif':  'text/plain',
    '.pdbqt':'text/plain',
    '.woff2':'font/woff2',
    '.woff': 'font/woff',
}


class GemaMXHandler(http.server.BaseHTTPRequestHandler):
    root: pathlib.Path  # inyectado por la subclase

    def do_GET(self):
        path = resolve_path(self.root, self.path)
        if path is None:
            self.send_error(HTTPStatus.NOT_FOUND, f'Archivo no encontrado: {self.path}')
            return

        suffix = path.suffix.lower()
        mime = MIME.get(suffix, 'application/octet-stream')

        try:
            data = path.read_bytes()
        except OSError as e:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(e))
            return

        self.send_response(HTTPStatus.OK)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        # Sin caché para JSON y JS/CSS (igual que nginx.conf)
        if suffix in ('.json', '.js', '.css'):
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):  # noqa: N802
        # Mostrar solo errores 4xx/5xx para no saturar la consola
        msg = fmt % args
        if args and str(args[1]) not in ('200', '304'):
            print(f'[dev] {self.path}  →  {msg}', file=sys.stderr)


def make_handler(root: pathlib.Path):
    class Handler(GemaMXHandler):
        pass
    Handler.root = root
    return Handler


def main():
    parser = argparse.ArgumentParser(description='Servidor de desarrollo gemamx-webapp')
    parser.add_argument('--port', type=int, default=8099)
    parser.add_argument('--root', type=pathlib.Path,
                        default=pathlib.Path(__file__).parent.parent)
    args = parser.parse_args()

    root = args.root.resolve()
    print(f'gemamx-webapp dev server')
    print(f'  Raíz del proyecto : {root}')
    print(f'  webapp/           : {root / "webapp"}')
    print(f'  results/data/     → /data/')
    print(f'  results/runs/     → /runs/')
    print(f'  results/external/ → /external/  (si existe)')
    print(f'  Escuchando en     : http://localhost:{args.port}')
    print('  Ctrl+C para detener\n')

    handler = make_handler(root)
    with http.server.HTTPServer(('', args.port), handler) as srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print('\nServidor detenido.')


if __name__ == '__main__':
    main()

