#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from time import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PORT = int(os.environ.get('PORT', '4318'))
PUBLISH_PASSWORD = os.environ.get('PUBLISH_PASSWORD', '')
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
GITHUB_OWNER = os.environ.get('GITHUB_OWNER', 'meteorcyclops')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'japan-trip-2026')
GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', 'master')
GITHUB_CONTENT_PATH = os.environ.get('GITHUB_CONTENT_PATH', 'data/trip.json')
ALLOWED_ORIGIN = os.environ.get('ALLOWED_ORIGIN', 'https://travel.koxuan.com')
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get('RATE_LIMIT_WINDOW_SECONDS', '60'))
RATE_LIMIT_MAX_REQUESTS = int(os.environ.get('RATE_LIMIT_MAX_REQUESTS', '10'))
REQUEST_LOG_PATH = os.environ.get('REQUEST_LOG_PATH', '/opt/travel-publish-api/publish.log')
RATE_STATE: dict[str, list[float]] = {}


def github_headers() -> dict[str, str]:
    return {
        'Authorization': f'Bearer {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'travel-publish-api',
    }


def client_ip(handler: BaseHTTPRequestHandler) -> str:
    forwarded = handler.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return handler.client_address[0]


def rate_limited(ip: str) -> bool:
    now = time()
    values = [t for t in RATE_STATE.get(ip, []) if now - t < RATE_LIMIT_WINDOW_SECONDS]
    if len(values) >= RATE_LIMIT_MAX_REQUESTS:
        RATE_STATE[ip] = values
        return True
    values.append(now)
    RATE_STATE[ip] = values
    return False


def append_log(entry: dict) -> None:
    try:
        with open(REQUEST_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass


class Handler(BaseHTTPRequestHandler):
    def _set_headers(self, status: int, content_type: str = 'application/json') -> None:
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Access-Control-Allow-Origin', ALLOWED_ORIGIN)
        self.send_header('Vary', 'Origin')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(204)

    def do_GET(self):
        if self.path == '/healthz':
            self._set_headers(200)
            self.wfile.write(json.dumps({'ok': True, 'service': 'travel-publish-api'}).encode())
            return
        self._set_headers(404)
        self.wfile.write(json.dumps({'ok': False, 'error': 'not_found'}).encode())

    def do_POST(self):
        if self.path != '/travel-publish':
            self._set_headers(404)
            self.wfile.write(json.dumps({'ok': False, 'error': 'not_found'}).encode())
            return

        try:
            length = int(self.headers.get('Content-Length', '0'))
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode() or '{}')
        except Exception:
            self._set_headers(400)
            self.wfile.write(json.dumps({'ok': False, 'error': 'invalid_json'}).encode())
            return

        ip = client_ip(self)
        if rate_limited(ip):
            self._set_headers(429)
            self.wfile.write(json.dumps({'ok': False, 'error': 'rate_limited'}).encode())
            append_log({'event': 'rate_limited', 'ip': ip})
            return

        password = payload.get('password')
        content = payload.get('content')
        message = payload.get('message') or 'Update trip data from web editor'

        if not all([PUBLISH_PASSWORD, GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO]):
            self._set_headers(500)
            self.wfile.write(json.dumps({'ok': False, 'error': 'server_not_configured'}).encode())
            return

        if password != PUBLISH_PASSWORD:
            self._set_headers(401)
            self.wfile.write(json.dumps({'ok': False, 'error': 'invalid_password'}).encode())
            append_log({'event': 'invalid_password', 'ip': ip})
            return

        if not isinstance(content, dict) or not isinstance(content.get('days'), list) or not isinstance(content.get('stays'), dict) or not isinstance(content.get('transportTips'), dict):
            self._set_headers(400)
            self.wfile.write(json.dumps({'ok': False, 'error': 'invalid_content'}).encode())
            return

        base_url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{GITHUB_CONTENT_PATH}'
        try:
            req = Request(f'{base_url}?ref={GITHUB_BRANCH}', headers=github_headers())
            with urlopen(req, timeout=20) as resp:
                current = json.loads(resp.read().decode())

            encoded = base64.b64encode((json.dumps(content, ensure_ascii=False, indent=2) + '\n').encode()).decode()
            write_payload = json.dumps({
                'message': message,
                'content': encoded,
                'sha': current['sha'],
                'branch': GITHUB_BRANCH,
            }).encode()
            write_req = Request(base_url, data=write_payload, headers={**github_headers(), 'Content-Type': 'application/json'}, method='PUT')
            with urlopen(write_req, timeout=20) as resp:
                result = json.loads(resp.read().decode())

            response = {
                'ok': True,
                'commitSha': result.get('commit', {}).get('sha'),
                'commitUrl': result.get('commit', {}).get('html_url'),
            }
            append_log({'event': 'publish_ok', 'ip': ip, 'commitSha': response['commitSha'], 'message': message})
            self._set_headers(200)
            self.wfile.write(json.dumps(response).encode())
        except HTTPError as error:
            detail = error.read().decode(errors='replace')
            self._set_headers(502)
            self.wfile.write(json.dumps({'ok': False, 'error': 'github_http_error', 'detail': detail}).encode())
            append_log({'event': 'github_http_error', 'ip': ip, 'detail': detail[:500]})
        except URLError as error:
            self._set_headers(502)
            self.wfile.write(json.dumps({'ok': False, 'error': 'github_network_error', 'detail': str(error.reason)}).encode())
            append_log({'event': 'github_network_error', 'ip': ip, 'detail': str(error.reason)})
        except Exception as error:
            self._set_headers(500)
            self.wfile.write(json.dumps({'ok': False, 'error': 'server_error', 'detail': str(error)}).encode())
            append_log({'event': 'server_error', 'ip': ip, 'detail': str(error)})

    def log_message(self, format, *args):
        return


if __name__ == '__main__':
    server = HTTPServer(('127.0.0.1', PORT), Handler)
    print(f'travel-publish-api listening on :{PORT}')
    server.serve_forever()
