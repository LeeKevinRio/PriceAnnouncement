"""Telegram bot — slash commands to manage watchlist.yaml without editing files.

Designed for *polling* (called from a GitHub Actions cron every few minutes).
Each invocation:
  1. Loads bot_state.json to get the last seen update_id
  2. Calls Telegram getUpdates with offset = last_update_id + 1
  3. Processes any new messages from the authorized chat_id
  4. Modifies watchlist.yaml in place (caller commits + pushes the diff)
  5. Saves bot_state.json with the new offset

Authorized chat: only the chat_id in TELEGRAM_CHAT_ID env can issue commands.
Anyone else's messages are ignored silently.

Commands (see /help for full list):
  /list                        list current watches
  /add k=v k=v ...             add a watch (key=value form)
  /remove NAME                 delete a watch by name
  /setprice NAME N             change a watch's max_price
  /setairlines NAME CI,BR      whitelist airlines
  /setdirect NAME on|off       require direct flights
  /scan                        request an immediate scan run
  /help                        show this help
"""

import json
import os
import sys
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
_WATCHLIST = _ROOT / "watchlist.yaml"
_BOT_STATE = _ROOT / "bot_state.json"

_API = "https://api.telegram.org/bot{token}/{method}"


# ─────────────────────────────────────────────────────────────────────────────
# Telegram I/O
# ─────────────────────────────────────────────────────────────────────────────


def get_updates(token: str, offset: int = 0) -> list[dict]:
    r = requests.get(
        _API.format(token=token, method="getUpdates"),
        params={"offset": offset, "timeout": 0},
        timeout=15,
    )
    r.raise_for_status()
    payload = r.json()
    if not payload.get("ok"):
        return []
    return payload.get("result", [])


def send(token: str, chat_id: str, text: str) -> None:
    requests.post(
        _API.format(token=token, method="sendMessage"),
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=15,
    ).raise_for_status()


# ─────────────────────────────────────────────────────────────────────────────
# Bot state (last processed update_id)
# ─────────────────────────────────────────────────────────────────────────────


def load_offset() -> int:
    if not _BOT_STATE.exists():
        return 0
    try:
        return int(json.loads(_BOT_STATE.read_text(encoding="utf-8")).get("update_id", 0))
    except (json.JSONDecodeError, ValueError, OSError):
        return 0


def save_offset(offset: int) -> None:
    _BOT_STATE.write_text(json.dumps({"update_id": offset}), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Watchlist mutation helpers
# ─────────────────────────────────────────────────────────────────────────────


def _read_watchlist() -> dict:
    return yaml.safe_load(_WATCHLIST.read_text(encoding="utf-8")) or {}


def _write_watchlist(data: dict) -> None:
    _WATCHLIST.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _find_watch(data: dict, name: str) -> tuple[int, dict] | tuple[None, None]:
    for i, w in enumerate(data.get("watches") or []):
        if w.get("name") == name:
            return i, w
    return None, None


def _parse_kv_args(text: str) -> dict[str, str]:
    """Parse 'k1=v1 k2=v2 ...' into a dict. Values may contain commas."""
    out: dict[str, str] = {}
    for token in text.split():
        if "=" not in token:
            continue
        k, _, v = token.partition("=")
        out[k.strip().lower()] = v.strip()
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Command handlers — return a string response to send back
# ─────────────────────────────────────────────────────────────────────────────


def _help() -> str:
    return (
        "<b>可用指令</b>\n"
        "<code>/list</code>  列出所有監控\n"
        "<code>/add name=X dest=YYY price=N [stays=4,5,6] [origin=TPE] [adults=2] "
        "[airlines=CI,BR] [direct=yes] [days=180]</code>\n"
        "  例：<code>/add name=首爾 dest=ICN price=12000 stays=4,5,6</code>\n"
        "<code>/remove NAME</code>  移除\n"
        "<code>/setprice NAME N</code>  改門檻\n"
        "<code>/setairlines NAME CI,BR,JX</code>  設白名單；填 <code>none</code> 清空\n"
        "<code>/setdirect NAME on|off</code>  只看直飛\n"
        "<code>/scan</code>  立即觸發掃描\n"
        "<code>/help</code>  這個說明\n\n"
        "<i>變更要等下次 cron（最多 5 分鐘）才會被 git push 寫回，</i>\n"
        "<i>之後下一次 12h 排程才用新設定。要立即跑可發 /scan。</i>"
    )


_REPO_BLOB_URL = (
    "https://github.com/LeeKevinRio/PriceAnnouncement/blob/main/watchlist.yaml"
)


def _list() -> str:
    data = _read_watchlist()
    watches = data.get("watches") or []
    if not watches:
        return "目前沒有任何監控。發 <code>/add</code> 看怎麼新增。"
    lines = ["<b>📋 監控清單</b>"]
    for w in watches:
        origin = w.get("origin") or (data.get("defaults") or {}).get("origin", "TPE")
        bits = [
            f"• <b>{w['name']}</b> {origin}→{w['destination']}",
            f"  max={w['max_price']:,.0f}",
        ]
        if w.get("stay_days"):
            bits.append(f"stays={w['stay_days']}")
        if w.get("airlines_allow"):
            bits.append(f"only={w['airlines_allow']}")
        if w.get("airlines_block"):
            bits.append(f"block={w['airlines_block']}")
        if w.get("direct_only"):
            bits.append("direct")
        lines.append(" ".join(bits))
    lines.append("")
    lines.append(f'<i>即時版本：<a href="{_REPO_BLOB_URL}">點這裡看 GitHub 上的 watchlist.yaml</a></i>')
    return "\n".join(lines)


def _add(args_text: str) -> str:
    args = _parse_kv_args(args_text)
    if "name" not in args or "dest" not in args or "price" not in args:
        return (
            "❌ 缺少必要欄位。最少要 <code>name=, dest=, price=</code>\n"
            "例：<code>/add name=首爾 dest=ICN price=12000 stays=4,5,6</code>"
        )

    new_watch: dict = {
        "name": args["name"],
        "destination": args["dest"].upper(),
        "depart_window_days": int(args.get("days", 180)),
        "stay_days": [int(s) for s in args.get("stays", "4,5,6,7").split(",") if s.strip()],
        "max_price": float(args["price"]),
    }
    if "origin" in args:
        new_watch["origin"] = args["origin"].upper()
    if "adults" in args:
        new_watch["adults"] = int(args["adults"])
    if "airlines" in args and args["airlines"].lower() != "none":
        new_watch["airlines_allow"] = [
            a.strip().upper() for a in args["airlines"].split(",") if a.strip()
        ]
    if "block" in args and args["block"].lower() != "none":
        new_watch["airlines_block"] = [
            a.strip().upper() for a in args["block"].split(",") if a.strip()
        ]
    if "direct" in args:
        new_watch["direct_only"] = args["direct"].lower() in ("yes", "true", "on", "1")

    data = _read_watchlist()
    idx, _ = _find_watch(data, new_watch["name"])
    if idx is not None:
        data["watches"][idx] = new_watch
        verb = "更新"
    else:
        data.setdefault("watches", []).append(new_watch)
        verb = "新增"
    _write_watchlist(data)
    return f"✅ {verb} <b>{new_watch['name']}</b>（{new_watch.get('origin', 'TPE')}→{new_watch['destination']}, max={new_watch['max_price']:,.0f}）"


def _remove(args_text: str) -> str:
    name = args_text.strip()
    if not name:
        return "❌ 用法：<code>/remove 名稱</code>"
    data = _read_watchlist()
    idx, _ = _find_watch(data, name)
    if idx is None:
        return f"❌ 找不到名稱 <b>{name}</b>"
    del data["watches"][idx]
    _write_watchlist(data)
    return f"✅ 已移除 <b>{name}</b>"


def _setprice(args_text: str) -> str:
    parts = args_text.rsplit(maxsplit=1)
    if len(parts) != 2:
        return "❌ 用法：<code>/setprice 名稱 金額</code>"
    name, price_str = parts
    try:
        price = float(price_str.replace(",", ""))
    except ValueError:
        return "❌ 金額要是數字"
    data = _read_watchlist()
    idx, w = _find_watch(data, name)
    if idx is None:
        return f"❌ 找不到 <b>{name}</b>"
    w["max_price"] = price
    _write_watchlist(data)
    return f"✅ <b>{name}</b> 門檻改為 {price:,.0f}"


def _setairlines(args_text: str) -> str:
    parts = args_text.split(maxsplit=1)
    if len(parts) != 2:
        return "❌ 用法：<code>/setairlines 名稱 CI,BR,JX</code>（填 <code>none</code> 清空）"
    name, codes_str = parts
    data = _read_watchlist()
    idx, w = _find_watch(data, name)
    if idx is None:
        return f"❌ 找不到 <b>{name}</b>"
    if codes_str.lower() in ("none", "off", "clear", "-"):
        w.pop("airlines_allow", None)
        _write_watchlist(data)
        return f"✅ 已清除 <b>{name}</b> 的航空白名單"
    codes = [c.strip().upper() for c in codes_str.split(",") if c.strip()]
    w["airlines_allow"] = codes
    _write_watchlist(data)
    return f"✅ <b>{name}</b> 只接受航空：{codes}"


def _setdirect(args_text: str) -> str:
    parts = args_text.split(maxsplit=1)
    if len(parts) != 2:
        return "❌ 用法：<code>/setdirect 名稱 on|off</code>"
    name, val = parts
    on = val.lower() in ("on", "yes", "true", "1")
    data = _read_watchlist()
    idx, w = _find_watch(data, name)
    if idx is None:
        return f"❌ 找不到 <b>{name}</b>"
    if on:
        w["direct_only"] = True
        suffix = "✅ 只看直飛"
    else:
        w.pop("direct_only", None)
        suffix = "✅ 不限直飛/轉機"
    _write_watchlist(data)
    return f"<b>{name}</b>: {suffix}"


def _scan_request() -> str:
    """Drop a sentinel file the bot workflow checks; the workflow then triggers
    the scan workflow via repository_dispatch (handled by bot-poll.yml)."""
    (_ROOT / ".scan_requested").write_text("1", encoding="utf-8")
    return "🔄 已排程下一次掃描，~5 分鐘內會跑。"


COMMANDS = {
    "/help": lambda _: _help(),
    "/start": lambda _: _help(),
    "/list": lambda _: _list(),
    "/add": _add,
    "/remove": _remove,
    "/setprice": _setprice,
    "/setairlines": _setairlines,
    "/setdirect": _setdirect,
    "/scan": lambda _: _scan_request(),
}


def handle(text: str) -> str:
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    args_text = parts[1] if len(parts) > 1 else ""
    handler = COMMANDS.get(cmd)
    if handler is None:
        return f"未知指令 <code>{cmd}</code>。發 /help 看可用指令。"
    return handler(args_text)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


def poll_once() -> int:
    """One round of getUpdates → process → save offset.
    Returns number of messages handled (for logging)."""
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        print("bot: missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
        return 0

    offset = load_offset()
    updates = get_updates(token, offset + 1 if offset else 0)
    if not updates:
        return 0

    handled = 0
    last_id = offset
    for upd in updates:
        last_id = max(last_id, int(upd["update_id"]))
        msg = upd.get("message") or upd.get("edited_message") or {}
        text = msg.get("text", "") or ""
        sender_chat = str(msg.get("chat", {}).get("id", ""))
        if sender_chat != str(chat_id):
            continue
        if not text.startswith("/"):
            continue
        try:
            response = handle(text)
        except Exception as exc:
            response = f"❌ 處理失敗：{exc}"
        try:
            send(token, chat_id, response)
        except Exception as exc:
            print(f"bot: send failed: {exc}")
        handled += 1

    save_offset(last_id)
    print(f"bot: handled {handled} command(s), offset now {last_id}")
    return handled


if __name__ == "__main__":
    poll_once()
    # Exit code 0 always; let caller workflow inspect git diff to decide
    # whether to commit/push the watchlist.
    sys.exit(0)
