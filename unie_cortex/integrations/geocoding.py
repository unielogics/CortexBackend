"""ZIP/postal -> rough lat/lon for distance proxy (Mapbox or Nominatim)."""

import httpx

from unie_cortex.config import settings


class GeocodingService:
    async def _geoapify_coords(self, text: str, country: str) -> tuple[float | None, float | None, str | None]:
        key = settings.geoapify_api_key
        if not key or not text.strip():
            return None, None, None
        cc = (country or "US").lower()
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    "https://api.geoapify.com/v1/geocode/search",
                    params={
                        "text": text.strip(),
                        "apiKey": key,
                        "limit": 1,
                        "filter": f"countrycode:{cc}",
                    },
                )
                if r.status_code != 200:
                    return None, None, None
                feats = r.json().get("features") or []
                if not feats:
                    return None, None, None
                geom = feats[0].get("geometry") or {}
                coords = geom.get("coordinates") or []
                props = feats[0].get("properties") or {}
                label = props.get("formatted") or props.get("name")
                if len(coords) >= 2:
                    return float(coords[1]), float(coords[0]), label
        except Exception:
            pass
        return None, None, None

    async def postal_to_coords(self, postal: str, country: str = "US") -> tuple[float | None, float | None]:
        postal = (postal or "").strip()
        if not postal:
            return None, None
        lat, lon, _ = await self._geoapify_coords(postal, country)
        if lat is not None and lon is not None:
            return lat, lon
        if settings.geocoding_mapbox_token:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{postal}.json"
                    r = await client.get(
                        url,
                        params={"access_token": settings.geocoding_mapbox_token, "country": country, "limit": 1},
                    )
                    if r.status_code == 200:
                        feat = (r.json().get("features") or [{}])[0]
                        c = feat.get("center") or []
                        if len(c) >= 2:
                            return float(c[1]), float(c[0])
            except Exception:
                pass
        if settings.geocoding_nominatim:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    r = await client.get(
                        "https://nominatim.openstreetmap.org/search",
                        params={"postalcode": postal, "country": country, "format": "json", "limit": 1},
                        headers={"User-Agent": "UnieCortex/1.0"},
                    )
                    if r.status_code == 200 and r.json():
                        j = r.json()[0]
                        return float(j["lat"]), float(j["lon"])
            except Exception:
                pass
        return None, None

    async def forward_geocode(
        self, query: str, country: str = "US"
    ) -> tuple[float | None, float | None, str | None]:
        """Full address or place string -> (lat, lon, place_label)."""
        q = (query or "").strip()
        if not q:
            return None, None, None
        lat, lon, label = await self._geoapify_coords(q, country)
        if lat is not None:
            return lat, lon, label
        if settings.geocoding_mapbox_token:
            try:
                from urllib.parse import quote

                async with httpx.AsyncClient(timeout=15.0) as client:
                    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{quote(q)}.json"
                    r = await client.get(
                        url,
                        params={
                            "access_token": settings.geocoding_mapbox_token,
                            "country": country,
                            "limit": 1,
                        },
                    )
                    if r.status_code == 200:
                        feat = (r.json().get("features") or [{}])[0]
                        c = feat.get("center") or []
                        if len(c) >= 2:
                            label = feat.get("place_name") or feat.get("text")
                            return float(c[1]), float(c[0]), label
            except Exception:
                pass
        if settings.geocoding_nominatim:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    r = await client.get(
                        "https://nominatim.openstreetmap.org/search",
                        params={"q": q, "country": country, "format": "json", "limit": 1},
                        headers={"User-Agent": "UnieCortex/1.0"},
                    )
                    if r.status_code == 200 and r.json():
                        j = r.json()[0]
                        return float(j["lat"]), float(j["lon"]), j.get("display_name")
            except Exception:
                pass
        return None, None, None

    async def distance_km_between_postals(
        self, postal_a: str, postal_b: str, country: str = "US"
    ) -> float | None:
        la, loa = await self.postal_to_coords(postal_a, country)
        lb, lob = await self.postal_to_coords(postal_b, country)
        if la is None or lb is None:
            return None
        return round(self.haversine_km(la, loa, lb, lob), 2)

    @staticmethod
    def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        from math import asin, cos, radians, sin, sqrt

        r = 6371.0
        la1, lo1, la2, lo2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat, dlon = la2 - la1, lo2 - lo1
        h = sin(dlat / 2) ** 2 + cos(la1) * cos(la2) * sin(dlon / 2) ** 2
        return 2 * r * asin(sqrt(min(1.0, h)))
