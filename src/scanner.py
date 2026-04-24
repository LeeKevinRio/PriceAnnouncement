import time
from datetime import date, timedelta

from . import state as state_mod
from .config import AppConfig, Watch
from .telegram_bot import TelegramNotifier
from .travelpayouts_client import FlightQuote, TravelpayoutsClient


def _date_pairs(watch: Watch) -> list[tuple[str, str]]:
    today = date.today()
    pairs: list[tuple[str, str]] = []
    for offset in range(1, watch.depart_window_days + 1, watch.date_step_days):
        depart = today + timedelta(days=offset)
        for stay in watch.stay_days:
            ret = depart + timedelta(days=stay)
            pairs.append((depart.isoformat(), ret.isoformat()))
    return pairs


def scan_watch(client: TravelpayoutsClient, watch: Watch) -> list[FlightQuote]:
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


def _filter_new_hits(
    state: dict, watch: Watch, hits: list[FlightQuote]
) -> list[FlightQuote]:
    """Keep only hits that are new or meaningfully cheaper than last notification."""
    fresh: list[FlightQuote] = []
    for q in hits:
        if state_mod.should_notify(
            state, watch.name, q.depart_date, q.return_date, q.price
        ):
            fresh.append(q)
    return fresh


def run(cfg: AppConfig, dry_run: bool = False) -> None:
    client = TravelpayoutsClient(cfg.travelpayouts_token, cfg.travelpayouts_marker)
    notifier = TelegramNotifier(cfg.tg_bot_token, cfg.tg_chat_id)

    state = state_mod.load_state()
    pruned = state_mod.prune_past(state)
    if pruned:
        print(f"pruned {pruned} past entries from state")

    sections: list[str] = []
    failed: list[str] = []
    all_hits: list[tuple[Watch, list[FlightQuote]]] = []

    for watch in cfg.watches:
        try:
            hits = scan_watch(client, watch)
            all_hits.append((watch, hits))
            fresh = _filter_new_hits(state, watch, hits)
            if fresh:
                sections.append(format_section(watch, fresh))
            suppressed = len(hits) - len(fresh)
            if suppressed:
                print(f"[{watch.name}] {suppressed} hit(s) suppressed (already notified)")
        except Exception as exc:
            print(f"[{watch.name}] scan error: {exc}")
            failed.append(watch.name)

    if not sections and not failed:
        print("no new hits; skipping Telegram notification")
        # Still save pruning updates
        if not dry_run:
            state_mod.save_state(state)
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

    # Record all fresh notifications so we don't re-spam next run
    for watch, hits in all_hits:
        for q in hits:
            if state_mod.should_notify(
                state, watch.name, q.depart_date, q.return_date, q.price
            ):
                state_mod.record(
                    state, watch.name, q.depart_date, q.return_date, q.price
                )
    state_mod.save_state(state)
