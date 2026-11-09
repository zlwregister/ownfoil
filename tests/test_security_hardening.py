import io
import socket

import pytest
from flask.testing import FlaskClient
from PIL import Image

import auth
import media
import safe_download
import security
from db import User, db


def test_no_admin_blocks_deployed_app_and_startup(shop_app, monkeypatch):
    monkeypatch.delenv('USER_ADMIN_NAME', raising=False)
    monkeypatch.delenv('USER_GUEST_NAME', raising=False)
    with shop_app.app.app_context():
        User.query.delete()
        db.session.commit()
    assert shop_app.client.get('/admin/settings').status_code == 503
    with pytest.raises(RuntimeError, match='USER_ADMIN_NAME'):
        auth.init_users(shop_app.app)


def test_startup_can_initialize_admin(shop_app, monkeypatch):
    monkeypatch.setenv('USER_ADMIN_NAME', 'new-admin')
    monkeypatch.setenv('USER_ADMIN_PASSWORD', 'a-long-unique-test-password')
    with shop_app.app.app_context():
        User.query.delete()
        db.session.commit()
    auth.init_users(shop_app.app)
    assert shop_app.client.get('/login').status_code == 200


def test_raw_login_requires_csrf(shop_app):
    client = FlaskClient(shop_app.app)
    assert client.post('/login', data={'user': 'admin', 'password': 'wrong'}).status_code == 403
    page = client.get('/login')
    assert b'name="csrf_token"' in page.data
    with client.session_transaction() as session:
        token = session['_csrf_token']
    assert client.post('/login', data={'user': 'admin', 'password': 'wrong',
                                      'csrf_token': token}).status_code == 302


def test_cross_origin_and_cross_site_blocked(shop_app):
    assert shop_app.client.get('/api/ws', headers={'Origin': 'https://evil.example'}).status_code == 403
    assert shop_app.client.post('/login', headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403


def test_basic_api_client_still_works(shop_app):
    import base64
    from capture.fixture import PASSWORDS
    credentials = base64.b64encode(f'admin:{PASSWORDS["admin"]}'.encode()).decode()
    client = FlaskClient(shop_app.app)
    response = client.post('/api/graphql', headers={'Authorization': 'Basic ' + credentials},
                           json={'query': '{ stats { totalApps } }'})
    assert response.status_code == 200


def test_browser_session_cannot_write_without_token(shop_app):
    from capture.fixture import PASSWORDS
    client = FlaskClient(shop_app.app)
    client.get('/login')
    with client.session_transaction() as session:
        token = session['_csrf_token']
    assert client.post('/login', data={'user': 'admin', 'password': PASSWORDS['admin'],
                                      'csrf_token': token}).status_code == 302
    query = {'query': 'mutation { cancelTask(taskId: "9999") { id } }'}
    assert client.post('/api/graphql', json=query).status_code == 403
    assert client.post('/api/graphql', json=query,
                       headers={'Authorization': 'Basic ZmFrZTpmYWtl'}).status_code == 403
    assert client.post('/api/graphql', json=query,
                       headers={'X-CSRF-Token': token}).status_code == 200


def test_cannot_delete_last_admin(shop_app):
    from capture.fixture import PASSWORDS
    shop_app.client.post('/login', data={'user': 'admin', 'password': PASSWORDS['admin']})
    with shop_app.app.app_context():
        admin_id = User.query.filter_by(user='admin').one().id
    response = shop_app.client.delete('/api/user', json={'user_id': admin_id})
    assert response.status_code == 409
    with shop_app.app.app_context():
        assert auth.admin_account_created() == 1


@pytest.mark.parametrize('value', ['https://evil.example', '//evil.example', '/\\evil.example',
                                  '/\nevil.example', 'javascript:alert(1)'])
def test_login_redirects_stay_local(value):
    assert security.safe_next(value) == '/'


def test_local_redirect_allowed():
    assert security.safe_next('/admin/settings?tab=library') == '/admin/settings?tab=library'


def test_login_failures_are_limited(shop_app):
    for _ in range(security.LOGIN_ATTEMPTS):
        assert shop_app.client.post('/login', data={'user': 'admin', 'password': 'wrong'}).status_code == 302
    assert shop_app.client.post('/login', data={'user': 'admin', 'password': 'wrong'}).status_code == 429


@pytest.mark.parametrize('url', ['http://img.nintendo.com/art.jpg', 'https://127.0.0.1/a',
                               'https://nintendo.com.evil.example/a', 'https://nintendo.com:8443/a',
                               'https://user:pass@nintendo.com/a', 'file:///etc/passwd'])
def test_artwork_rejects_untrusted_destinations(url):
    with pytest.raises(ValueError):
        safe_download.destination(url)


@pytest.mark.parametrize('address', ['127.0.0.1', '192.168.1.1', '169.254.169.254', '::1',
                                   '::ffff:8.8.8.8', '10.0.0.1'])
def test_artwork_rejects_private_dns(monkeypatch, address):
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', (address, 443))])
    with pytest.raises(ValueError):
        safe_download.destination('https://img.nintendo.com/art.jpg')


class Response:
    status = 200
    headers = {}
    def stream(self, *args, **kwargs):
        yield b'picture'
    def close(self):
        pass


def mock_download(monkeypatch, response):
    calls = []
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(0, 0, 0, '', ('8.8.8.8', 443))])
    class Pool:
        def __init__(self, address, **kwargs):
            calls.append((address, kwargs))
        def urlopen(self, *args, **kwargs):
            return response
        def close(self):
            pass
    monkeypatch.setattr(safe_download.urllib3, 'HTTPSConnectionPool', Pool)
    return calls


def test_artwork_connects_to_pinned_ip_with_verified_hostname(monkeypatch):
    calls = mock_download(monkeypatch, Response())
    assert safe_download.fetch_artwork('https://img.nintendo.com/art.jpg') == b'picture'
    assert calls[0][0] == '8.8.8.8'
    assert calls[0][1]['server_hostname'] == 'img.nintendo.com'
    assert calls[0][1]['assert_hostname'] == 'img.nintendo.com'
    assert calls[0][1]['cert_reqs'] == 'CERT_REQUIRED'


def test_artwork_redirect_is_revalidated(monkeypatch):
    response = Response()
    response.status = 302
    response.headers = {'Location': 'http://192.168.1.1/admin'}
    calls = mock_download(monkeypatch, response)
    with pytest.raises(ValueError):
        safe_download.fetch_artwork('https://img.nintendo.com/art.jpg')
    assert len(calls) == 1


def test_artwork_stream_size_is_bounded(monkeypatch):
    mock_download(monkeypatch, Response())
    monkeypatch.setattr(safe_download, 'MAX_BYTES', 3)
    with pytest.raises(ValueError, match='size limit'):
        safe_download.fetch_artwork('https://img.nintendo.com/art.jpg')


def test_artwork_rejects_tiff_even_with_jpeg_name():
    buffer = io.BytesIO()
    Image.new('RGB', (4, 4)).save(buffer, format='TIFF')
    with pytest.raises(Exception):
        media.store_bytes(media.ICON, buffer.getvalue(), 'art.jpg')
