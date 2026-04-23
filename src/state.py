"""通知狀態持久化：避免每 12 小時重複推播同一筆低價票。

key = "watch_name|depart_date|return_date"
value = {"price": float, "notified_at": "YYYY-MM-DD"}

只在以下情況才通知：
  1. 這筆 key 從未通知過，或
  2. 價格比上次通知再跌 >= DROP_THRESHOLD（預設 5%）
"""

import json
from datetime import date
from pathlib import Path

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "state.json"
DROP_THRESHOLD = 0.05  # 5%


def load_state(path: Path | None = None) -> dict[str, dict]:
    p = path or _DEFAULT_PATH
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict, path: Path | None = None) -> None:
    p = path or _DEFAULT_PATH
    with open(p, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)


def _key(watch_name: str, depart: str, ret: str) -> str:
    return f"{watch_name}|{depart}|{ret}"


def should_notify(
    state: dict,
    watch_name: str,
    depart: str,
    ret: str,
    price: float,
    drop_threshold: float = DROP_THRESHOLD,
) -> bool:
    """True iff this hit should trigger a notification."""
    prev = state.get(_key(watch_name, depart, ret))
    if prev is None:
        return True
    return price <= prev["price"] * (1 - drop_threshold)


def record(
    state: dict,
    watch_name: str,
    depart: str,
    ret: str,
    price: float,
    notified_at: str | None = None,
) -> None:
    state[_key(watch_name, depart, ret)] = {
        "price": price,
        "notified_at": notified_at or date.today().isoformat(),
    }


def prune_past(state: dict, today: date | None = None) -> int:
    """Remove entries whose depart_date is in the past. Returns count pruned."""
    today = today or date.today()
    stale = []
    for key in state:
        parts = key.split("|")
        if len(parts) != 3:
            continue
        try:
            depart = date.fromisoformat(parts[1])
        except ValueError:
            continue
        if depart < today:
            stale.append(key)
    for key in stale:
        del state[key]
    return len(stale)
