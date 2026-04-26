"""Rolling price history per route + trend computation.

Records every cheap deal we see, keyed by (watch_name, depart, return).
For each key we keep the (date, price_per_person) samples from the
last `RETENTION_DAYS` days. The scanner uses this to:

  1. Decorate Telegram messages with a 7-day trend (↓-12%, ↑+5%, ──)
  2. Render a tiny ASCII sparkline so the user sees the shape

Storage shape (history.json):
{
  "大阪|2026-06-02|2026-06-08": [
    {"date": "2026-04-22", "price": 6500.0},
    {"date": "2026-04-25", "price": 6200.0},
    {"date": "2026-04-26", "price": 5791.0}
  ],
  ...
}
"""

import json
from datetime import date, timedelta
from pathlib import Path

_DEFAULT_PATH = Path(__file__).resolve().parent.parent / "history.json"
RETENTION_DAYS = 14  # keep ~2 weeks so 7-day windows are always populated

_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def load_history(path: Path | None = None) -> dict[str, list[dict]]:
    p = path or _DEFAULT_PATH
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_history(history: dict, path: Path | None = None) -> None:
    p = path or _DEFAULT_PATH
    with open(p, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2, sort_keys=True)


def _key(watch_name: str, depart: str, ret: str) -> str:
    return f"{watch_name}|{depart}|{ret}"


def record(
    history: dict,
    watch_name: str,
    depart: str,
    ret: str,
    price_per_person: float,
    today: date | None = None,
) -> None:
    """Append today's sample. If we already have a sample for today, overwrite it
    (we only care about the latest snapshot per day to avoid intra-day churn)."""
    today = today or date.today()
    today_iso = today.isoformat()
    series = history.setdefault(_key(watch_name, depart, ret), [])
    # Replace today's entry if it exists, else append
    for entry in series:
        if entry.get("date") == today_iso:
            entry["price"] = price_per_person
            return
    series.append({"date": today_iso, "price": price_per_person})


def prune(history: dict, today: date | None = None) -> int:
    """Drop samples older than RETENTION_DAYS, plus any keys whose depart is
    in the past. Returns total entries removed."""
    today = today or date.today()
    cutoff = today - timedelta(days=RETENTION_DAYS)
    removed = 0

    stale_keys: list[str] = []
    for key, series in history.items():
        # Prune past departures entirely
        parts = key.split("|")
        if len(parts) == 3:
            try:
                if date.fromisoformat(parts[1]) < today:
                    stale_keys.append(key)
                    continue
            except ValueError:
                pass

        # Prune samples older than retention window
        keep = [
            s for s in series
            if _safe_date(s.get("date")) and _safe_date(s["date"]) >= cutoff
        ]
        removed += len(series) - len(keep)
        history[key] = keep

    for key in stale_keys:
        removed += len(history[key])
        del history[key]

    return removed


def _safe_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def trend(
    history: dict,
    watch_name: str,
    depart: str,
    ret: str,
    window_days: int = 7,
    today: date | None = None,
) -> dict | None:
    """Return trend info or None if we don't have enough samples yet.

    Returned dict:
      {
        "samples":     [(date, price), ...],   # within window, oldest first
        "change_pct":  -12.3,                  # vs oldest sample in window
        "arrow":       "↓",                    # ↓ / ↑ / ──
        "spark":       "▆▅▄▃▂"                 # mini sparkline
      }
    """
    today = today or date.today()
    cutoff = today - timedelta(days=window_days)
    series = history.get(_key(watch_name, depart, ret), [])
    samples = sorted(
        [
            (_safe_date(s["date"]), float(s["price"]))
            for s in series
            if _safe_date(s.get("date")) and _safe_date(s["date"]) >= cutoff
        ],
        key=lambda x: x[0],
    )
    if len(samples) < 2:
        return None

    oldest = samples[0][1]
    newest = samples[-1][1]
    change_pct = (newest - oldest) / oldest * 100 if oldest else 0.0
    arrow = "↓" if change_pct < -0.5 else ("↑" if change_pct > 0.5 else "──")

    return {
        "samples": samples,
        "change_pct": change_pct,
        "arrow": arrow,
        "spark": _sparkline([p for _, p in samples]),
    }


def _sparkline(values: list[float]) -> str:
    """Render a list of prices as a sparkline like ▆▅▄▃▂."""
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if hi == lo:
        return _SPARK_CHARS[len(_SPARK_CHARS) // 2] * len(values)
    span = hi - lo
    out = []
    for v in values:
        idx = int((v - lo) / span * (len(_SPARK_CHARS) - 1))
        out.append(_SPARK_CHARS[idx])
    return "".join(out)
