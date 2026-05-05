import re
from dataclasses import dataclass
from datetime import date, timedelta

from . import history as history_mod
from . import state as state_mod
from .config import AppConfig, Watch
from .telegram_bot import TelegramNotifier
from .travelpayouts_client import FlightQuote, TravelpayoutsClient


_TIME_RE = re.compile(r"T(\d{2}:\d{2})")


def _extract_time(iso_ts: str) -> str:
    """Pull HH:MM out of an ISO timestamp; '' if it's just a date."""
    if not iso_ts:
        return ""
    m = _TIME_RE.search(iso_ts)
    return m.group(1) if m else ""


def _booking_url(q: FlightQuote, adults: int, marker: str) -> str:
    """Build an Aviasales search deep link for this roundtrip.

    Format: /search/{ORIG}{DDMM_depart}{DEST}{DDMM_return}{adults}.
    Marker is appended for affiliate attribution when configured.
    """
    try:
        d = date.fromisoformat(q.depart_date)
        r = date.fromisoformat(q.return_date)
    except ValueError:
        return ""
    path = (
        f"{q.origin}{d.day:02d}{d.month:02d}"
        f"{q.destination}{r.day:02d}{r.month:02d}{adults}"
    )
    url = f"https://www.aviasales.com/search/{path}"
    if marker:
        url += f"?marker={marker}"
    return url


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
    watch: Watch,
    hits: list[FlightQuote],
    history: dict | None = None,
    marker: str = "",
    prev_prices: dict[tuple[str, str], float] | None = None,
) -> str:
    """Render one watch's hits as an HTML block.

    `prev_prices` (depart→return → previous price) — when supplied, each quote
    that has an entry gets a ⬇️ "降價 from X" annotation. Used for the 🔻 section.
    """
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

        drop_str = ""
        if prev_prices is not None:
            prev = prev_prices.get((q.depart_date, q.return_date))
            if prev is not None and prev > q.price:
                drop_pct = (prev - q.price) / prev * 100
                drop_str = (
                    f"  <i>⬇️ 從 {watch.currency} {prev:,.0f} 降 {drop_pct:.0f}%</i>"
                )

        # 7-day trend (only shown when we have ≥2 samples in the window)
        trend_str = ""
        if history is not None:
            t = history_mod.trend(history, watch.name, q.depart_date, q.return_date)
            if t:
                trend_str = (
                    f"  <i>{t['arrow']}{abs(t['change_pct']):.0f}% 7d {t['spark']}</i>"
                )

        # Departure times are best-effort: API only returns them sometimes,
        # and only for the depart-side of each leg (no arrival/landing).
        dep_t = _extract_time(q.depart_at)
        ret_t = _extract_time(q.return_at)
        dep_str = f"{q.depart_date} {dep_t}" if dep_t else q.depart_date
        ret_str = f"{q.return_date} {ret_t}" if ret_t else q.return_date

        url = _booking_url(q, watch.adults, marker)
        link_html = f"  <a href=\"{url}\">訂票</a>" if url else ""

        seen = f" <i>[cache: {q.found_at}]</i>" if q.found_at else ""
        lines.append(
            f"• {dep_str} → {ret_str}  {price_html}"
            f"{drop_str}{trend_str}  ({meta}){link_html}{seen}"
        )
    return "\n".join(lines)


@dataclass
class _GoneEntry:
    watch_name: str
    depart: str
    ret: str
    prev_price: float
    currency: str


def _classify(
    state: dict,
    all_hits: list[tuple[Watch, list[FlightQuote]]],
) -> tuple[
    list[tuple[Watch, FlightQuote]],
    list[tuple[Watch, FlightQuote, float]],
    list[_GoneEntry],
]:
    """Compare current hits against state. Returns (new, drop, gone).

    - new:  hits whose (watch, depart, return) wasn't in state
    - drop: hits in state where current price ≤ state.price * (1 - DROP_THRESHOLD)
    - gone: state entries (depart still in future) that are absent from current hits.
            Only considers watches still present in the current scan — entries for
            removed watches are ignored so a deleted watch doesn't haunt notifications.
    """
    new_hits: list[tuple[Watch, FlightQuote]] = []
    drop_hits: list[tuple[Watch, FlightQuote, float]] = []
    seen_keys: set[str] = set()
    watch_currency: dict[str, str] = {}

    for watch, hits in all_hits:
        watch_currency[watch.name] = watch.currency
        for q in hits:
            key = state_mod._key(watch.name, q.depart_date, q.return_date)
            seen_keys.add(key)
            prev = state.get(key)
            if prev is None:
                new_hits.append((watch, q))
            elif q.price <= prev["price"] * (1 - state_mod.DROP_THRESHOLD):
                drop_hits.append((watch, q, float(prev["price"])))

    today = date.today()
    gone: list[_GoneEntry] = []
    for key, info in state.items():
        if key in seen_keys:
            continue
        parts = key.split("|")
        if len(parts) != 3:
            continue
        watch_name, depart_str, ret_str = parts
        if watch_name not in watch_currency:
            continue  # watch removed from config — skip, don't ghost-notify
        try:
            depart = date.fromisoformat(depart_str)
        except ValueError:
            continue
        if depart < today:
            continue
        gone.append(
            _GoneEntry(
                watch_name=watch_name,
                depart=depart_str,
                ret=ret_str,
                prev_price=float(info["price"]),
                currency=watch_currency[watch_name],
            )
        )
    return new_hits, drop_hits, gone


def _build_header(
    cfg: AppConfig,
    all_hits: list[tuple[Watch, list[FlightQuote]]],
    failed: list[str],
    new_hits: list[tuple[Watch, FlightQuote]],
    drop_hits: list[tuple[Watch, FlightQuote, float]],
    gone: list[_GoneEntry],
) -> str:
    """Top-of-message status block: full watch list + per-region status icons."""
    by_name = {w.name: hs for w, hs in all_hits}
    failed_set = set(failed)

    matched_names = [w.name for w in cfg.watches if by_name.get(w.name)]
    empty_names = [
        w.name
        for w in cfg.watches
        if not by_name.get(w.name) and w.name not in failed_set
    ]

    matched_with_count = [f"{n}({len(by_name[n])})" for n in matched_names]

    lines = [
        f"✈️ 機票通知 {date.today().isoformat()}",
        "",
        (
            f"🎯 監控 {len(cfg.watches)} 地區｜符合 {len(matched_names)}"
            f"｜🆕{len(new_hits)} 🔻{len(drop_hits)} 💤{len(gone)}"
        ),
        "",
    ]
    if matched_with_count:
        lines.append("🟢 <b>有特價</b>: " + " ".join(matched_with_count))
    if empty_names:
        lines.append("🔴 <b>無特價</b>: " + " ".join(empty_names))
    if failed:
        lines.append("⚠️ <b>掃描失敗</b>: " + " ".join(failed))
    return "\n".join(lines)


def _format_gone_section(gone: list[_GoneEntry]) -> str:
    lines = ["💤 <b>已不再特價</b> <i>(上次有, 本次無或漲價)</i>"]
    # Group by watch name for compactness
    grouped: dict[str, list[_GoneEntry]] = {}
    for g in gone:
        grouped.setdefault(g.watch_name, []).append(g)
    for name in sorted(grouped):
        for g in sorted(grouped[name], key=lambda x: (x.depart, x.ret)):
            lines.append(
                f"• {name} {g.depart} → {g.ret}  "
                f"<i>(上次 {g.currency} {g.prev_price:,.0f})</i>"
            )
    return "\n".join(lines)


def _format_changes(
    new_hits: list[tuple[Watch, FlightQuote]],
    drop_hits: list[tuple[Watch, FlightQuote, float]],
    gone: list[_GoneEntry],
    history: dict,
    marker: str,
) -> list[str]:
    """Build the body sections for the message. Empty buckets are skipped."""
    parts: list[str] = []

    if new_hits:
        grouped: dict[str, tuple[Watch, list[FlightQuote]]] = {}
        for w, q in new_hits:
            grouped.setdefault(w.name, (w, []))[1].append(q)
        sub = ["🆕 <b>新增特價</b>"]
        for w, hs in grouped.values():
            sub.append(format_section(w, hs, history=history, marker=marker))
        parts.append("\n\n".join(sub))

    if drop_hits:
        grouped_d: dict[str, tuple[Watch, list[FlightQuote], dict]] = {}
        for w, q, prev in drop_hits:
            entry = grouped_d.setdefault(w.name, (w, [], {}))
            entry[1].append(q)
            entry[2][(q.depart_date, q.return_date)] = prev
        sub = ["🔻 <b>再降價</b>"]
        for w, hs, prev_map in grouped_d.values():
            sub.append(
                format_section(
                    w, hs, history=history, marker=marker, prev_prices=prev_map
                )
            )
        parts.append("\n\n".join(sub))

    if gone:
        parts.append(_format_gone_section(gone))

    return parts


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

    failed: list[str] = []
    all_hits: list[tuple[Watch, list[FlightQuote]]] = []

    for watch in cfg.watches:
        try:
            hits = scan_watch(client, watch, verbose=verbose)
            all_hits.append((watch, hits))
            for q in hits:
                history_mod.record(
                    history, watch.name, q.depart_date, q.return_date, q.price_per_person
                )
        except Exception as exc:
            print(f"[{watch.name}] scan error: {exc}")
            failed.append(watch.name)
            all_hits.append((watch, []))

    new_hits, drop_hits, gone = _classify(state, all_hits)
    print(
        f"summary: {len(new_hits)} new, {len(drop_hits)} drop, "
        f"{len(gone)} gone, {len(failed)} failed"
    )

    has_changes = bool(new_hits or drop_hits or gone)
    if not has_changes and not failed:
        print("no changes vs last scan; skipping Telegram notification")
        if not dry_run:
            # Still record any first-time hits into state for next-scan diffing,
            # and persist history samples we collected this run.
            _persist_state(state, all_hits, gone)
            state_mod.save_state(state)
            history_mod.save_history(history)
        return

    header = _build_header(cfg, all_hits, failed, new_hits, drop_hits, gone)
    body_parts = _format_changes(
        new_hits, drop_hits, gone, history, cfg.travelpayouts_marker
    )

    sep = "\n\n━━━━━━━━━━━━━━━\n\n"
    message = header + (sep + "\n\n".join(body_parts) if body_parts else "")

    if dry_run:
        print("[dry-run] would send:\n" + message)
        return

    notifier.send(message)
    print("sent Telegram notification")

    _persist_state(state, all_hits, gone)
    state_mod.save_state(state)
    history_mod.save_history(history)


def _persist_state(
    state: dict,
    all_hits: list[tuple[Watch, list[FlightQuote]]],
    gone: list[_GoneEntry],
) -> None:
    """Sync state with this scan's reality:

    - Insert/refresh entries for new hits + meaningful drops (so DROP_THRESHOLD
      always compares against the last-notified price, not yesterday's price).
    - Drop GONE entries so they re-appear as 🆕 NEW if they come back.
    """
    for watch, hits in all_hits:
        for q in hits:
            if state_mod.should_notify(
                state, watch.name, q.depart_date, q.return_date, q.price
            ):
                state_mod.record(
                    state, watch.name, q.depart_date, q.return_date, q.price
                )
    for g in gone:
        state.pop(state_mod._key(g.watch_name, g.depart, g.ret), None)
