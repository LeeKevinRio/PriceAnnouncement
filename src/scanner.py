import time
from datetime import date, timedelta

from .amadeus_client import AmadeusClient, FlightQuote
from .config import AppConfig, Watch
from .telegram_bot import TelegramNotifier


def _date_pairs(watch: Watch) -> list[tuple[str, str]]:
    today = date.today()
    pairs: list[tuple[str, str]] = []
    for offset in range(1, watch.depart_window_days + 1, watch.date_step_days):
        depart = today + timedelta(days=offset)
        for stay in watch.stay_days:
            ret = depart + timedelta(days=stay)
            pairs.append((depart.isoformat(), ret.isoformat()))
    return pairs


def scan_watch(client: AmadeusClient, watch: Watch) -> list[FlightQuote]:
    pairs = _date_pairs(watch)
    print(f"[{watch.name}] scanning {len(pairs)} date combos...")
    hits: list[FlightQuote] = []
    for depart, ret in pairs:
        quote = client.cheapest_roundtrip(
            origin=watch.origin,
            destination=watch.destination,
            depart_date=depart,
            return_date=ret,
            adults=watch.adults,
            cabin=watch.cabin,
            currency=watch.currency,
        )
        if quote and quote.price <= watch.max_price:
            hits.append(quote)
            print(f"  HIT {depart} -> {ret}: {quote.currency} {quote.price:,.0f}")
        time.sleep(0.15)
    print(f"[{watch.name}] {len(hits)} hits under {watch.currency} {watch.max_price:,.0f}")
    return hits


def format_section(watch: Watch, hits: list[FlightQuote]) -> str:
    lines = [
        f"<b>{watch.name} ({watch.origin}→{watch.destination})</b>",
        f"門檻 {watch.currency} {watch.max_price:,.0f} | {watch.adults}人 {watch.cabin}",
        "",
    ]
    for q in sorted(hits, key=lambda x: x.price):
        airlines = "/".join(q.airlines) if q.airlines else "—"
        lines.append(
            f"• {q.depart_date} → {q.return_date}  "
            f"<b>{q.currency} {q.price:,.0f}</b>  ({airlines})"
        )
    return "\n".join(lines)


def run(cfg: AppConfig, dry_run: bool = False) -> None:
    client = AmadeusClient(cfg.amadeus_key, cfg.amadeus_secret)
    notifier = TelegramNotifier(cfg.tg_bot_token, cfg.tg_chat_id)

    sections: list[str] = []
    failed: list[str] = []
    for watch in cfg.watches:
        try:
            hits = scan_watch(client, watch)
            if hits:
                sections.append(format_section(watch, hits))
        except Exception as exc:
            print(f"[{watch.name}] scan error: {exc}")
            failed.append(watch.name)

    if not sections and not failed:
        print("no hits below threshold; skipping Telegram notification")
        return

    header = f"✈️ 機票通知 {date.today().isoformat()}\n\n"
    body_parts = sections[:]
    if failed:
        body_parts.append(f"⚠️ 掃描失敗: {', '.join(failed)}")
    body = "\n\n".join(body_parts)

    if dry_run:
        print("[dry-run] would send:\n" + header + body)
        return

    notifier.send(header + body)
    print("sent Telegram notification")
