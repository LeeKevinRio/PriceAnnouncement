import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class Watch:
    name: str
    origin: str
    destination: str
    depart_window_days: int
    stay_days: list[int]
    adults: int
    cabin: str
    currency: str
    max_price: float
    date_step_days: int


@dataclass
class AppConfig:
    travelpayouts_token: str
    travelpayouts_marker: str
    tg_bot_token: str
    tg_chat_id: str
    watches: list[Watch]


def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


def load(
    watchlist_path: Path | None = None, require_flights_api: bool = True
) -> AppConfig:
    """Load config from watchlist.yaml + env vars.

    Set require_flights_api=False for commands that only talk to Telegram
    (e.g. --test-notify), so the user can verify Telegram connectivity
    before they've finished setting up their Travelpayouts credentials.
    """
    load_dotenv()

    path = watchlist_path or Path(__file__).resolve().parent.parent / "watchlist.yaml"
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    defaults = raw.get("defaults") or {}
    watches: list[Watch] = []
    for w in raw["watches"]:
        watches.append(
            Watch(
                name=w["name"],
                origin=w.get("origin", defaults.get("origin", "TPE")),
                destination=w["destination"],
                depart_window_days=int(w["depart_window_days"]),
                stay_days=[int(d) for d in w["stay_days"]],
                adults=int(w.get("adults", defaults.get("adults", 2))),
                cabin=w.get("cabin", defaults.get("cabin", "ECONOMY")),
                currency=w.get("currency", defaults.get("currency", "TWD")),
                max_price=float(w["max_price"]),
                date_step_days=int(
                    w.get("date_step_days", defaults.get("date_step_days", 3))
                ),
            )
        )

    if require_flights_api:
        tp_token = _require_env("TRAVELPAYOUTS_TOKEN")
    else:
        tp_token = os.environ.get("TRAVELPAYOUTS_TOKEN", "")
    # Marker is optional; Travelpayouts only needs it for attribution
    tp_marker = os.environ.get("TRAVELPAYOUTS_MARKER", "")

    return AppConfig(
        travelpayouts_token=tp_token,
        travelpayouts_marker=tp_marker,
        tg_bot_token=_require_env("TELEGRAM_BOT_TOKEN"),
        tg_chat_id=_require_env("TELEGRAM_CHAT_ID"),
        watches=watches,
    )
