from urllib.parse import urlsplit

from integrations.http import RemoteError, post_json


class CRMClient:
    def __init__(self, base_url: str, token: str, transport=post_json):
        parts = urlsplit(base_url)
        # crm — фиксированное имя сервиса во внутренней сети Docker Compose.
        if (parts.scheme not in ('http', 'https') or parts.hostname not in ('127.0.0.1', 'localhost', '::1', 'crm')
                or parts.username or parts.password or parts.query or parts.fragment or parts.path not in ('', '/')):
            raise ValueError('CRM_BASE_URL должен указывать на локальную CRM или сервис crm в Docker.')
        self._base = base_url.rstrip('/')
        self._token = token
        self._transport = transport

    def create_lead(self, payload: dict):
        result = self._post('/leads', payload)
        if result.get('status') not in ('new', 'in_progress', 'closed', 'rejected'):
            raise RemoteError()
        return result

    def bind(self, payload: dict):
        return self._post('/bind', payload)

    def _post(self, path: str, payload: dict):
        result = self._transport(self._base + '/integrations/telegram' + path, payload,
                                 {'Authorization': 'Bearer ' + self._token}, 10)
        if not isinstance(result, dict) or not isinstance(result.get('id'), int):
            raise RemoteError()
        return result
