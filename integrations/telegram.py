from integrations.http import RemoteError, post_json


class TelegramClient:
    def __init__(self, token: str, transport=post_json):
        self._token = token
        self._transport = transport

    def call(self, method: str, payload: dict, timeout: int = 15):
        result = self._transport(f'https://api.telegram.org/bot{self._token}/{method}', payload, {}, timeout)
        if not isinstance(result, dict) or not result.get('ok'):
            code = result.get('error_code', 0) if isinstance(result, dict) else 0
            parameters = result.get('parameters') if isinstance(result, dict) else None
            retry = parameters.get('retry_after', 0) if isinstance(parameters, dict) else 0
            raise RemoteError(code, retry)
        if 'result' not in result:
            raise RemoteError()
        return result['result']

    def get_updates(self, offset: int):
        result = self.call('getUpdates', {'offset': offset, 'timeout': 25, 'allowed_updates': ['message']}, timeout=35)
        if not isinstance(result, list) or any(not isinstance(item, dict) or not isinstance(item.get('update_id'), int) for item in result):
            raise RemoteError()
        return result

    def send_message(self, chat_id: int, text: str, reply_markup: dict | None = None):
        payload = {'chat_id': chat_id, 'text': text}
        if reply_markup is not None:
            payload['reply_markup'] = reply_markup
        # parse_mode не используется: пользовательский текст остаётся обычным текстом.
        result = self.call('sendMessage', payload)
        if not isinstance(result, dict) or not isinstance(result.get('message_id'), int):
            raise RemoteError()
        return result
