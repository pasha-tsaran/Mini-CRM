import io
import traceback
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError

import pytest

from bot.config import require_settings
from integrations import http
from integrations.crm import CRMClient
from integrations.telegram import TelegramClient


@pytest.mark.parametrize('error', [URLError('secret-token'), IncompleteRead(b'secret-token'), ValueError('secret-token')])
def test_transport_errors_do_not_expose_secret(monkeypatch, error):
    class Opener:
        def open(self, request, timeout):
            raise error
    monkeypatch.setattr(http, 'build_opener', lambda *args: Opener())
    endpoint = 'https://example.test/botsecret-token/sendMessage'
    with pytest.raises(http.RemoteError) as caught:
        http.post_json(endpoint, {}, {}, 15)
    assert 'secret-token' not in ''.join(traceback.format_exception(caught.value))


def test_http_retry_after_and_response_closing(monkeypatch):
    body = io.BytesIO(b'{"parameters":{"retry_after":37},"description":"secret-token"}')
    class Opener:
        def open(self, request, timeout):
            raise HTTPError('secret-token', 429, 'secret-token', {}, body)
    monkeypatch.setattr(http, 'build_opener', lambda *args: Opener())
    with pytest.raises(http.RemoteError) as caught:
        http.post_json('https://example.test/', {}, {}, 15)
    assert caught.value.code == 429 and caught.value.retry_after == 37
    assert body.closed and 'secret-token' not in str(caught.value)


def test_clients_auth_timeout_and_plain_text():
    calls = []
    def crm_transport(*args):
        calls.append(args)
        return {'id': 1, 'status': 'new'}
    CRMClient('http://127.0.0.1:5000', 'test-secret', crm_transport).create_lead({'name': 'Иван'})
    assert calls[-1][2] == {'Authorization': 'Bearer test-secret'}
    assert calls[-1][3] == 10
    def tg_transport(*args):
        calls.append(args)
        return {'ok': True, 'result': [] if args[0].endswith('getUpdates') else {'message_id': 1}}
    client = TelegramClient('dummy', tg_transport)
    client.get_updates(42)
    assert calls[-1][1]['offset'] == 42 and calls[-1][3] == 35
    client.send_message(123, '<b>Обычный текст</b>')
    assert 'parse_mode' not in calls[-1][1] and calls[-1][3] == 15


@pytest.mark.parametrize('url', ['https://example.com', 'http://127.0.0.1@evil.test', 'http://localhost/path', 'file:///tmp/crm'])
def test_crm_rejects_nonlocal_urls(url):
    with pytest.raises(ValueError):
        CRMClient(url, 'dummy')


def test_crm_accepts_compose_service_without_relaxing_host_validation():
    calls = []
    def transport(*args):
        calls.append(args)
        return {'id': 1, 'status': 'new'}
    CRMClient('http://crm:5000', 'test-secret', transport).create_lead({})
    assert calls[0][0] == 'http://crm:5000/integrations/telegram/leads'
    for invalid in ('http://crm.evil.test:5000', 'http://crm@evil.test', 'http://crm/path'):
        with pytest.raises(ValueError):
            CRMClient(invalid, 'dummy')


def test_missing_settings_fail_without_secrets(monkeypatch):
    for name in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_BOT_USERNAME', 'CRM_BASE_URL', 'CRM_BOT_API_TOKEN'):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit, match='TELEGRAM_BOT_TOKEN'):
        require_settings()


@pytest.mark.parametrize('result', [{}, {'ok': True}, {'ok': True, 'result': {}}, {'ok': False, 'error_code': 'secret-token', 'parameters': None}])
def test_malformed_telegram_response_is_safe(result):
    with pytest.raises(http.RemoteError) as caught:
        TelegramClient('dummy', lambda *args: result).send_message(123, 'Текст')
    assert 'secret-token' not in str(caught.value)
