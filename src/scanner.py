from datetime import date, timedelta

from . import history as history_mod
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
        direct_only=watch.direct_only,
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

        if watch.adults > 1:
            price_str = (
                f"{q.currency} {q.price_per_person:,.0f}/人 "
                f"(×{watch.adults}={q.price:,.0f})"
            )
        else:
            price_str = f"{q.currency} {q.price:,.0f}"
        seen = f" [seen {q.found_at}]" if q.found_at else ""
        print(f"  HIT {q.depart_date} → {q.return_date} ({duration}d): {price_str}{seen}")
        hits.append(q)

    print(f"[{watch.name}] {len(hits)} hits under {watch.currency} {watch.max_price:,.0f}")
    return hits


def format_section(
    watch: Watch, hits: list[FlightQuote], history: dict | None = None
) -> str:
    lines = [
        f"<b>{watch.name} ({watch.origin}→{watch.destination})</b>",
        f"門檻 {watch.currency} {watch.max_price:,.0f} | {watch.adults}人 {watch.cabin}",
        "",
    ]
    for q in sorted(hits, key=lambda x: x.price):
        meta_parts: list[str] = []
        if q.airlines:
            meta_parts.append("/".join(q.airlines))
        if q.transfers == 0:
            meta_parts.append("直飛")
        else:
            meta_parts.append(f"{q.transfers}轉")
        if q.gate:
            meta_parts.append(f"via {q.gate}")
        meta = " ".join(meta_parts) if meta_parts else "—"

        if watch.adults > 1:
            price_html = (
                f"<b>{q.currency} {q.price_per_person:,.0f}/人</b> "
                f"({watch.adults}人 {q.price:,.0f})"
            )
        else:
            price_html = f"<b>{q.currency} {q.price:,.0f}</b>"

        # 7-day trend (only shown when we have ≥2 samples in the window)
        trend_str = ""
        if history is not None:
            t = history_mod.trend(history, watch.name, q.depart_date, q.return_date)
            if t:
                trend_str = (
                    f"  <i>{t['arrow']}{abs(t['change_pct']):.0f}% 7d {t['spark']}</i>"
                )

        seen = f" <i>[cache: {q.found_at}]</i>" if q.found_at else ""
        lines.append(
            f"• {q.depart_date} → {q.return_date}  {price_html}{trend_str}  ({meta}){seen}"
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


def format_summary(
    cfg: AppConfig,
    all_hits: list[tuple[Watch, list[FlightQuote]]],
    failed: list[str],
) -> str:
    """One-line-per-watch summary of cheapest current hit, listed for *every*
    watch in the config — independent of dedup state. Sent every scan so the
    user sees full coverage of all routes even when individual prices haven't
    crossed the 5% re-notify threshold; the detailed change-only sections
    (sent below) still rely on dedup."""
    by_name = {w.name: hits for w, hits in all_hits}
    failed_set = set(failed)
    lines = ["📊 <b>當前最低價（全部 watches）</b>"]

    for watch in cfg.watches:
        prefix = f"• <b>{watch.name}</b> ({watch.origin}→{watch.destination})"
        if watch.name in failed_set:
            lines.append(f"{prefix}  ⚠️ <i>掃描失敗</i>")
            continue
        hits = by_name.get(watch.name, [])
        if not hits:
            lines.append(
                f"{prefix}  — <i>無低於 {watch.currency} {watch.max_price:,.0f} 的 hit</i>"
            )
            continue
        cheapest = min(hits, key=lambda q: q.price)
        try:
            duration = (
                date.fromisoformat(cheapest.return_date)
                - date.fromisoformat(cheapest.depart_date)
            ).days
            duration_str = f" ({duration}天)"
        except ValueError:
            duration_str = ""
        if watch.adults > 1:
            price_str = (
                f"{watch.currency} {cheapest.price_per_person:,.0f}/人"
                f" (×{watch.adults}={cheapest.price:,.0f})"
            )
        else:
            price_str = f"{watch.currency} {cheapest.price:,.0f}"
        lines.append(
            f"{prefix}  <b>{price_str}</b>  "
            f"{cheapest.depart_date}→{cheapest.return_date}{duration_str}"
        )

    return "\n".join(lines)


def run(cfg: AppConfig, dry_run: bool = False, verbose: bool = False) -> None:
    client = TravelpayoutsClient(cfg.travelpayouts_token, cfg.travelpayouts_marker)
    notifier = TelegramNotifier(cfg.tg_bot_token, cfg.tg_chat_id)

    state = state_mod.load_state()
    pruned = state_mod.prune_past(state)
    if pruned:
        print(f"pruned {pruned} past entries from state")

    history = history_mod.load_history()
    h_pruned = history_mod.prune(history)
    if h_pruned:
        print(f"pruned {h_pruned} stale samples from history")

    sections: list[str] = []
    failed: list[str] = []
    all_hits: list[tuple[Watch, list[FlightQuote]]] = []

    for watch in cfg.watches:
        try:
            hits = scan_watch(client, watch, verbose=verbose)
            all_hits.append((watch, hits))

            # Record every hit's per-person price into history (regardless of
            # dedup), so the trend chart reflects all observations not just
            # what we ended up notifying about.
            for q in hits:
                history_mod.record(
                    history, watch.name, q.depart_date, q.return_date, q.price_per_person
                )

            fresh = _filter_new_hits(state, watch, hits)
            if fresh:
                sections.append(format_section(watch, fresh, history=history))
            suppressed = len(hits) - len(fresh)
            if suppressed:
                print(f"[{watch.name}] {suppressed} hit(s) suppressed (already notified)")
        except Exception as exc:
            print(f"[{watch.name}] scan error: {exc}")
            failed.append(watch.name)

    has_any_hits = any(hits for _, hits in all_hits)

    # Skip only when truly nothing to report (no hits AND no failures across
    # all watches). Anything else gets a notification with the always-present
    # summary at the top.
    if not has_any_hits and not failed:
        print("no hits anywhere; skipping Telegram notification")
        if not dry_run:
            state_mod.save_state(state)
            history_mod.save_history(history)
        return

    header = f"✈️ 機票通知 {date.today().isoformat()}\n\n"
    summary = format_summary(cfg, all_hits, failed)

    body_parts: list[str] = [summary]
    if sections:
        body_parts.append(
            "🔻 <b>新降價 / 首次出現（已過 5% dedup）</b>\n\n"
            + "\n\n".join(sections)
        )
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
    history_mod.save_history(history)
