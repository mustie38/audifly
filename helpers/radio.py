"""
Gerçek internet radyosu: Radio Browser API (radio-browser.info) istasyon arama.

Orijinal mustiefly_helpers.fetch_radio_stations'in birebir portudur — senkron bir
fonksiyondur, çağıran yer arka plan thread'inde kullanmalıdır.
"""
from __future__ import annotations

import requests
from mustiefly_qt.helpers.logging_setup import get_logger


log = get_logger(__name__)
# Tek bir sunucu her zaman ayakta olmayabildiği için birkaç ayna deniyoruz.
RADIO_API_HOSTS = [
    "https://de1.api.radio-browser.info",
    "https://at1.api.radio-browser.info",
    "https://nl1.api.radio-browser.info",
    "https://fr1.api.radio-browser.info",
]

# Hızlı filtre rozetlerinde kullanılan türler
RADIO_GENRE_CHIPS = ["pop", "rock", "arabesk", "türkçe", "news", "dance", "jazz", "classical"]


def fetch_radio_stations(query="", country="", tag="", limit=60):
    """Radio Browser API'sinden çalışır durumdaki istasyonları çeker.
    'country' ISO 3166-1 alpha-2 ÜLKE KODU bekler (örn. "TR") — ülke adı değil.
    Bir ayna yanıt vermezse sıradakini dener; hepsi başarısız olursa boş liste döner."""
    params = {
        "limit": limit,
        "hidebroken": "true",
        "order": "clickcount",
        "reverse": "true",
    }
    if query:
        params["name"] = query
    if country:
        params["countrycode"] = country
    if tag:
        params["tag"] = tag
    headers = {"User-Agent": "Audifly/1.0"}

    for host in RADIO_API_HOSTS:
        try:
            resp = requests.get(f"{host}/json/stations/search", params=params,
                                headers=headers, timeout=6)
            resp.raise_for_status()
            data = resp.json()
            stations = []
            for s in data:
                url = s.get("url_resolved") or s.get("url")
                if not url:
                    continue
                name = (s.get("name") or "").strip() or "Bilinmeyen İstasyon"
                stations.append({
                    "stationuuid": s.get("stationuuid"),
                    "name": name,
                    "url": url,
                    "favicon": s.get("favicon") or "",
                    "tags": s.get("tags", ""),
                    "country": s.get("country", ""),
                    "bitrate": s.get("bitrate", 0),
                    "codec": s.get("codec", ""),
                })
            return stations
        except Exception as e:
            log.error("%s %s", f"Radyo API ({host}) yanıt vermedi, sıradaki sunucu deneniyor:", e)
            continue
    return []
