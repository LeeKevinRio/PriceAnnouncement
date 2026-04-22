from dataclasses import dataclass

from amadeus import Client, ResponseError


@dataclass
class FlightQuote:
    origin: str
    destination: str
    depart_date: str
    return_date: str
    price: float
    currency: str
    airlines: list[str]


class AmadeusClient:
    def __init__(self, api_key: str, api_secret: str):
        self._client = Client(client_id=api_key, client_secret=api_secret)

    def cheapest_roundtrip(
        self,
        origin: str,
        destination: str,
        depart_date: str,
        return_date: str,
        adults: int,
        cabin: str,
        currency: str = "TWD",
    ) -> FlightQuote | None:
        try:
            response = self._client.shopping.flight_offers_search.get(
                originLocationCode=origin,
                destinationLocationCode=destination,
                departureDate=depart_date,
                returnDate=return_date,
                adults=adults,
                travelClass=cabin,
                currencyCode=currency,
                max=1,
            )
        except ResponseError:
            return None

        offers = response.data
        if not offers:
            return None

        offer = offers[0]
        price_info = offer["price"]
        return FlightQuote(
            origin=origin,
            destination=destination,
            depart_date=depart_date,
            return_date=return_date,
            price=float(price_info["grandTotal"]),
            currency=price_info["currency"],
            airlines=offer.get("validatingAirlineCodes", []),
        )
