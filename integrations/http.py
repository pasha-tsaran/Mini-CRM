import json
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class RemoteError(Exception):
    """Безопасное исключение: без адреса, токенов и текста удалённого ответа."""

    def __init__(self, code: int = 0, retry_after: int = 0):
        self.code = code if isinstance(code, int) else 0
        self.retry_after = max(0, retry_after) if isinstance(retry_after, int) else 0
        super().__init__(f'Ошибка удалённого сервиса (код {self.code}).')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post_json(url: str, payload: dict, headers: dict, timeout: int) -> dict:
    request = Request(url, data=json.dumps(payload).encode(), headers={
        'Content-Type': 'application/json', 'Accept': 'application/json', **headers,
    }, method='POST')
    try:
        with build_opener(NoRedirect).open(request, timeout=timeout) as response:
            data = json.loads(response.read(2_000_000))
            if not isinstance(data, dict):
                raise RemoteError()
            return data
    except HTTPError as error:
        try:
            data = json.loads(error.read(100_000))
            retry_after = int(data.get('parameters', {}).get('retry_after', 0))
        except (ValueError, TypeError, AttributeError, HTTPException, OSError):
            retry_after = 0
        finally:
            error.close()
        raise RemoteError(error.code, retry_after) from None
    except (URLError, OSError, ValueError, HTTPException):
        raise RemoteError() from None
