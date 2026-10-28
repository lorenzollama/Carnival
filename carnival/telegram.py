"""Step 10: send. Two Bot API methods over the standard library."""

import json
import os
import urllib.error
import urllib.request
import uuid


class TelegramError(RuntimeError):
    pass


def send_message(html):
    """Send an HTML message without link previews; returns its message id."""
    fields = {"text": html, "parse_mode": "HTML", "link_preview_options": {"is_disabled": True}}
    return _call("sendMessage", fields)["message_id"]


def send_photo(path, caption, reply_to):
    """A silent photo reply to `reply_to`; returns its message id."""
    fields = {"caption": caption[:1024], "disable_notification": True, "reply_parameters": {"message_id": reply_to}}
    return _call("sendPhoto", fields, photo=path)["message_id"]


def _call(method, fields, photo=None):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        raise TelegramError("set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (or use --dry-run)")
    fields = {"chat_id": chat, **fields}
    if photo:
        boundary = uuid.uuid4().hex
        parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'.encode()
                 + (json.dumps(v) if isinstance(v, (dict, bool)) else str(v)).encode() + b"\r\n"
                 for k, v in fields.items()]  # fmt: skip
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="{photo.name}"\r\n'
            f"Content-Type: image/jpeg\r\n\r\n".encode() + photo.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
        )
        body, kind = b"".join(parts), f"multipart/form-data; boundary={boundary}"
    else:
        body, kind = json.dumps(fields).encode(), "application/json"
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", body, {"Content-Type": kind})
    try:
        with urllib.request.urlopen(request, timeout=60) as r:
            reply = json.load(r)
    except urllib.error.HTTPError as e:  # Telegram explains its errors in the body
        reply = json.load(e)
    if not reply.get("ok"):
        raise TelegramError(f"{method}: {reply.get('description')}")
    return reply["result"]
