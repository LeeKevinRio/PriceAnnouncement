import requests

_MAX_LEN = 4096


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._chat_id = chat_id

    def send(self, text: str) -> None:
        for chunk in _split_message(text):
            self._post(chunk)

    def _post(self, text: str) -> None:
        response = requests.post(
            self._url,
            json={
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        response.raise_for_status()


def _split_message(text: str) -> list[str]:
    """Split text into chunks ≤ _MAX_LEN, breaking at double-newlines when possible."""
    if len(text) <= _MAX_LEN:
        return [text]
    chunks: list[str] = []
    while len(text) > _MAX_LEN:
        split_at = text.rfind("\n\n", 0, _MAX_LEN)
        if split_at == -1:
            split_at = text.rfind("\n", 0, _MAX_LEN)
        if split_at == -1:
            split_at = _MAX_LEN
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    if text:
        chunks.append(text)
    return chunks
