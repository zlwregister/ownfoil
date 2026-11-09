"""Browser request protections and bounded authentication throttling."""
import hmac
import secrets
import threading
import time
from collections import OrderedDict
from urllib.parse import urlsplit

from flask import abort, request, session

_attempts = OrderedDict()
_lock = threading.Lock()
LOGIN_WINDOW = 300
LOGIN_ATTEMPTS = 10


def login_allowed(address):
    now = time.monotonic()
    with _lock:
        count, started = _attempts.get(address, (0, now))
        if now - started >= LOGIN_WINDOW:
            _attempts.pop(address, None)
            return True
        return count < LOGIN_ATTEMPTS


def login_result(address, success):
    now = time.monotonic()
    with _lock:
        if success:
            _attempts.pop(address, None)
            return
        count, started = _attempts.pop(address, (0, now))
        if now - started >= LOGIN_WINDOW:
            count, started = 0, now
        _attempts[address] = (count + 1, started)
        while len(_attempts) > 1024:
            _attempts.popitem(last=False)


def safe_next(value):
    # Only local absolute paths. Backslashes/control characters are normalized
    # differently by browsers and must not be accepted as redirect destinations.
    if (not value or not value.startswith('/') or value.startswith('//')
            or '\\' in value or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        return '/'
    parsed = urlsplit(value)
    return value if not parsed.scheme and not parsed.netloc else '/'


def csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_urlsafe(32)
    return session['_csrf_token']


def install_browser_protection(app):
    app.config.update(MAX_CONTENT_LENGTH=1024 * 1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict',
                      REMEMBER_COOKIE_HTTPONLY=True, REMEMBER_COOKIE_SAMESITE='Strict')
    app.jinja_env.globals['csrf_token'] = csrf_token

    @app.before_request
    def protect_browser_request():
        origin = request.headers.get('Origin')
        if origin and origin != request.host_url.rstrip('/'):
            abort(403, 'Cross-origin requests are not allowed')
        if request.headers.get('Sec-Fetch-Site') == 'cross-site':
            abort(403, 'Cross-site requests are not allowed')
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return
        # Non-browser clients use explicit Basic credentials, not ambient cookies.
        # An existing browser session must never bypass CSRF by adding Authorization.
        if request.authorization and not session.get('_user_id'):
            return
        expected = session.get('_csrf_token', '')
        supplied = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token', '')
        if not expected or not hmac.compare_digest(expected, supplied):
            abort(403, 'Missing or invalid CSRF token; reload the page')

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        return response
