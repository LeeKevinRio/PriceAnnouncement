"""Travelpayouts (Aviasales) flight price API client.

Uses the `/aviasales/v3/get_latest_prices` endpoint which returns the
recent cached cheap deals for a route. We then filter client-side by
date range / stay duration / price threshold.

This trades exact-date matching (prices_for_dates) for better cache
coverage — crucial for low-volume origin airports like TPE where
per-date cache entries are often empty.
"""

from dataclasses import dataclass

import requests


@dataclass
class FlightQuote:
    origin: str
    destination: str
    depart_date: str
    return_date: str
    price: float
    currency: str
    airlines: list[str]


class TravelpayoutsClient:
    _BASE = "https://api.travelpayouts.com"
    _TIMEOUT = 15

    def __init__(self, api_token: str, marker: str = ""):
        self._marker = marker
        self._session = requests.Session()
        self._session.headers["X-Access-Token"] = api_token

    def find_deals(
        self,
        origin: str,
        destination: str,
        adults: int,
        currency: str = "TWD",
        period_type: str = "year",
        limit: int = 1000,
        verbose: bool = False,
    ) -> list[FlightQuote]:
        """Fetch all recent cached roundtrip deals for a route.

        Travelpayouts returns per-person prices; we multiply by `adults`
        so callers see grand totals (matching the existing max_price
        semantics in watchlist.yaml).

        Returns [] on error or when the cache has no data for this route.
        """
        params = {
            "origin": origin,
            "destination": destination,
            "currency": currency.lower(),
            "period_type": period_type,
            "one_way": "false",
            "page": 1,
            "limit": limit,
            "show_to_affiliates": "true",
            "sorting": "price",
        }
        if self._marker:
            params["marker"] = self._marker

        try:
            r = self._session.get(
                f"{self._BASE}/aviasales/v3/get_latest_prices",
                params=params,
                timeout=self._TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as exc:
            if verbose:
                print(f"    API ERROR {origin}->{destination}: {exc}")
            return []

        if not data.get("success", True):
            if verbose:
                print(f"    API NOT-OK {origin}->{destination}: {data}")
            return []

        offers = data.get("data") or []
        if not offers and verbose:
            print(f"    NO DEALS in Travelpayouts cache for {origin}->{destination}")

        quotes: list[FlightQuote] = []
        for offer in offers:
            depart = offer.get("depart_date") or offer.get("departure_at")
            ret = offer.get("return_date") or offer.get("return_at")
            # Different response shapes use different field names
            per_person = offer.get("value") or offer.get("price")
            if not (depart and ret and per_person):
                continue
            # Normalize ISO timestamp to date only
            depart = str(depart)[:10]
            ret = str(ret)[:10]
            airline = offer.get("gate") or offer.get("airline")
            quotes.append(
                FlightQuote(
                    origin=origin,
                    destination=destination,
                    depart_date=depart,
                    return_date=ret,
                    price=float(per_person) * adults,
                    currency=currency,
                    airlines=[airline] if airline else [],
                )
            )

        return quotes
