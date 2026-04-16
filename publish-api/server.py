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
GITHUB_VERSIONS_DIR = os.environ.get('GITHUB_VERSIONS_DIR', 'data/versions')
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


def normalize_value(value):
    if isinstance(value, list):
        return [normalize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: normalize_value(v) for k, v in value.items()}
    return value


def collect_changed_sections(before, after, path=''):
    if before == after:
        return []
    if not isinstance(before, dict) or not isinstance(after, dict):
        return [path or 'root']
    changed = []
    keys = set(before.keys()) | set(after.keys())
    for key in keys:
        next_path = f'{path}.{key}' if path else key
        changed.extend(collect_changed_sections(before.get(key), after.get(key), next_path))
    return sorted(set(changed))


def build_diff(before, after, path=''):
    if before == after:
        return []
    if not isinstance(before, dict) or not isinstance(after, dict):
        return [{'path': path or 'root', 'before': before, 'after': after}]
    entries = []
    keys = set(before.keys()) | set(after.keys())
    for key in keys:
        next_path = f'{path}.{key}' if path else key
        entries.extend(build_diff(before.get(key), after.get(key), next_path))
    return entries


def github_get_json(url: str):
    req = Request(url, headers=github_headers())
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def github_put_json(url: str, payload: dict):
    body = json.dumps(payload, ensure_ascii=False).encode()
    req = Request(url, data=body, headers={**github_headers(), 'Content-Type': 'application/json'}, method='PUT')
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


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
        editor = payload.get('editor') or 'web-editor'
        source = payload.get('source') or 'editor.html'

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
            current = github_get_json(f'{base_url}?ref={GITHUB_BRANCH}')
            before_content = json.loads(base64.b64decode(current['content']).decode())
            normalized_content = normalize_value(content)
            timestamp = __import__('datetime').datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
            revision_id = timestamp.replace(':', '-')
            changed_sections = collect_changed_sections(before_content, normalized_content)
            diff = build_diff(before_content, normalized_content)
            revision_path = f'{GITHUB_VERSIONS_DIR}/{revision_id}.json'
            revision_url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{revision_path}'
            revision_payload = {
                'revisionId': revision_id,
                'createdAt': timestamp,
                'editor': editor,
                'source': source,
                'message': message,
                'changedSections': changed_sections,
                'diff': diff,
                'beforeSha': current['sha'],
                'beforeSnapshot': before_content,
                'afterSnapshot': normalized_content,
            }

            github_put_json(revision_url, {
                'message': f'{message} [revision]',
                'content': base64.b64encode((json.dumps(revision_payload, ensure_ascii=False, indent=2) + '\n').encode()).decode(),
                'branch': GITHUB_BRANCH,
            })

            encoded = base64.b64encode((json.dumps(normalized_content, ensure_ascii=False, indent=2) + '\n').encode()).decode()
            result = github_put_json(base_url, {
                'message': message,
                'content': encoded,
                'sha': current['sha'],
                'branch': GITHUB_BRANCH,
            })

            response = {
                'ok': True,
                'commitSha': result.get('commit', {}).get('sha'),
                'commitUrl': result.get('commit', {}).get('html_url'),
                'revisionId': revision_id,
                'revisionPath': revision_path,
                'revisionUrl': f'https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/blob/{GITHUB_BRANCH}/{revision_path}',
                'changedSections': changed_sections,
            }
            append_log({'event': 'publish_ok', 'ip': ip, 'commitSha': response['commitSha'], 'message': message, 'revisionId': revision_id})
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
