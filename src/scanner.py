from datetime import date, timedelta

from . import state as state_mod
from .config import AppConfig, Watch
from .telegram_bot import TelegramNotifier
from .travelpayouts_client import FlightQuote, TravelpayoutsClient


def scan_watch(
    client: TravelpayoutsClient, watch: Watch, verbose: bool = False
) -> list[FlightQuote]:
    """Fetch recent deals for a watch and filter to hits matching all constraints."""
    quotes = client.find_deals(
        origin=watch.origin,
        destination=watch.destination,
        adults=watch.adults,
        currency=watch.currency,
        verbose=verbose,
    )
    print(f"[{watch.name}] got {len(quotes)} cached deals, filtering...")

    today = date.today()
    max_depart = today + timedelta(days=watch.depart_window_days)

    hits: list[FlightQuote] = []
    for q in quotes:
        try:
            depart = date.fromisoformat(q.depart_date)
            ret = date.fromisoformat(q.return_date)
        except ValueError:
            continue

        duration = (ret - depart).days
        reasons: list[str] = []
        if depart < today:
            reasons.append("depart in past")
        elif depart > max_depart:
            reasons.append(f"depart > +{watch.depart_window_days}d")
        if watch.stay_days and duration not in watch.stay_days:
            reasons.append(f"stay={duration}d not in {watch.stay_days}")
        if q.price > watch.max_price:
            reasons.append(f"price {q.price:,.0f} > {watch.max_price:,.0f}")
        if watch.airlines_allow and not any(
            a in watch.airlines_allow for a in q.airlines
        ):
            reasons.append(
                f"airline {q.airlines or '?'} not in allow {watch.airlines_allow}"
            )
        if watch.airlines_block and any(
            a in watch.airlines_block for a in q.airlines
        ):
            reasons.append(f"airline {q.airlines} in block list")

        if reasons:
            if verbose:
                print(
                    f"      SKIP {q.depart_date}→{q.return_date} ({duration}d) "
                    f"{q.currency} {q.price:,.0f}: {'; '.join(reasons)}"
                )
            continue

        print(
            f"  HIT {q.depart_date} → {q.return_date} ({duration}d): "
            f"{q.currency} {q.price:,.0f}"
        )
        hits.append(q)

    print(f"[{watch.name}] {len(hits)} hits under {watch.currency} {watch.max_price:,.0f}")
    return hits


def format_section(watch: Watch, hits: list[FlightQuote]) -> str:
    lines = [
        f"<b>{watch.name} ({watch.origin}→{watch.destination})</b>",
        f"門檻 {watch.currency} {watch.max_price:,.0f} | {watch.adults}人 {watch.cabin}",
        "",
    ]
    for q in sorted(hits, key=lambda x: x.price):
        meta_parts: list[str] = []
        if q.airlines:
            meta_parts.append("/".join(q.airlines))
        if q.gate:
            meta_parts.append(f"via {q.gate}")
        meta = " ".join(meta_parts) if meta_parts else "—"
        lines.append(
            f"• {q.depart_date} → {q.return_date}  "
            f"<b>{q.currency} {q.price:,.0f}</b>  ({meta})"
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


def run(cfg: AppConfig, dry_run: bool = False, verbose: bool = False) -> None:
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
            hits = scan_watch(client, watch, verbose=verbose)
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

    for watch, hits in all_hits:
        for q in hits:
            if state_mod.should_notify(
                state, watch.name, q.depart_date, q.return_date, q.price
            ):
                state_mod.record(
                    state, watch.name, q.depart_date, q.return_date, q.price
                )
    state_mod.save_state(state)
