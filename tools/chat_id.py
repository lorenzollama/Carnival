"""Find the chat ID to put in the TELEGRAM_CHAT_ID secret.

Send your bot any message in Telegram first, then run:

    python3 tools/chat_id.py

It asks for the bot token (input is hidden) and prints every chat that has written to the bot.
"""

import getpass
import json
import os
import sys
import urllib.request

token = os.environ.get("TELEGRAM_BOT_TOKEN") or getpass.getpass("Bot token from @BotFather: ").strip()
with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30) as reply:
    updates = json.load(reply)["result"]

chats = {}
for update in updates:
    for kind in ("message", "edited_message", "channel_post", "my_chat_member"):
        chat = update.get(kind, {}).get("chat")
        if chat:
            chats[chat["id"]] = chat.get("title") or chat.get("username") or chat.get("first_name") or ""
if not chats:
    sys.exit("No messages yet. Send your bot a message in Telegram, then run this again.")
for chat_id, name in chats.items():
    print(f"{chat_id}\t{name}")
