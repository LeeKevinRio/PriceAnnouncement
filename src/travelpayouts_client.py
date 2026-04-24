"""Travelpayouts (Aviasales) flight price API client.

Replaces the Amadeus client. Uses Travelpayouts' cached-prices endpoint
which is free after signup, no per-call quota for reasonable traffic.

Endpoint: https://api.travelpayouts.com/aviasales/v3/prices_for_dates

Note: Travelpayouts serves cached prices, so obscure dates may return
empty — that's normal, the scanner just skips those combos.
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

    def cheapest_roundtrip(
        self,
        origin: str,
        destination: str,
        depart_date: str,
        return_date: str,
        adults: int,
        cabin: str,  # noqa: ARG002 — kept for API compat with Amadeus client
        currency: str = "TWD",
        verbose: bool = False,
    ) -> FlightQuote | None:
        """Return the cheapest cached roundtrip quote, or None if not available.

        The returned price is multiplied by `adults` so it matches the Amadeus
        client's semantics (grand total for all passengers), keeping existing
        max_price thresholds in watchlist.yaml valid.

        With verbose=True, prints the reason whenever None is returned so we
        can distinguish "no cache for this date" from "API error / bad token".
        """
        params = {
            "origin": origin,
            "destination": destination,
            "departure_at": depart_date,
            "return_at": return_date,
            "currency": currency.lower(),
            "limit": 1,
            "sorting": "price",
            "direct": "false",
            "one_way": "false",
        }
        if self._marker:
            params["marker"] = self._marker

        try:
            r = self._session.get(
                f"{self._BASE}/aviasales/v3/prices_for_dates",
                params=params,
                timeout=self._TIMEOUT,
            )
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as exc:
            if verbose:
                print(f"    API ERROR {depart_date}->{return_date}: {exc}")
            return None

        if not data.get("success"):
            if verbose:
                print(f"    API NOT-OK {depart_date}->{return_date}: {data}")
            return None

        offers = data.get("data") or []
        if not offers:
            if verbose:
                print(f"    NO CACHE  {depart_date}->{return_date}")
            return None

        offer = offers[0]
        per_person = float(offer["price"])
        airline = offer.get("airline")

        return FlightQuote(
            origin=origin,
            destination=destination,
            depart_date=depart_date,
            return_date=return_date,
            price=per_person * adults,
            currency=currency,
            airlines=[airline] if airline else [],
        )
