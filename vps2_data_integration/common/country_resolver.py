"""Country resolution utilities shared across ETL phases.

Provides ISO-3 lookup by name or code, with fuzzy matching fallback.
Used by both stage_to_ods (trade partner resolution) and ods_to_nds
(FTA member country resolution).
"""

from __future__ import annotations

import country_converter as coco
import pycountry
from rapidfuzz import fuzz, process

cc = coco.CountryConverter()

COUNTRY_NAMES: list[str] = [c.name for c in pycountry.countries]

COUNTRY_ALIASES: dict[str, str] = {
    "MYANMA": "Myanmar",
    "MEHICO": "Mexico",
    "BRAXIN": "Brazil",
    "HUNGARI": "Hungary",
    "ACHENTINA": "Argentina",
    "PHILIPIN": "Philippines",
    "NIGIERIA": "Nigeria",
    "UCRAINA": "Ukraine",
}

NAME_TO_ALPHA3: dict[str, str] = {
    c.name.upper(): c.alpha_3 for c in pycountry.countries
}

ALPHA3_TO_META: dict[str, dict] = {
    c.alpha_3: {
        "name": c.name,
        "continent": cc.convert(names=c.alpha_3, to="continent"),
        "region": cc.convert(names=c.alpha_3, to="UNregion"),
    }
    for c in pycountry.countries
}

FUZZY_THRESHOLD = 70


def resolve_from_country_name(name: str) -> tuple[str | None, str | None, str | None, str]:
    """Resolve a country name string to (iso3, region, continent, canonical_name).

    Returns (None, None, None, original_name) if no match found above threshold.
    """
    country = str(name).strip()
    country = COUNTRY_ALIASES.get(country.upper(), country)

    code = NAME_TO_ALPHA3.get(country.upper())
    if code:
        meta = ALPHA3_TO_META[code]
        return code, meta["region"], meta["continent"], country

    try:
        iso3 = cc.convert(names=country, to="ISO3")
        if iso3 and iso3 != "not found":
            meta = ALPHA3_TO_META.get(iso3)
            if meta:
                return iso3, meta["region"], meta["continent"], country
    except Exception:
        pass

    match = process.extractOne(country, COUNTRY_NAMES, scorer=fuzz.WRatio)
    if match and match[1] > FUZZY_THRESHOLD:
        best = match[0]
        code = NAME_TO_ALPHA3.get(best.upper())
        meta = ALPHA3_TO_META.get(code)
        if code and meta:
            return code, meta["region"], meta["continent"], country

    return None, None, None, country


def resolve_from_country_code(code: str) -> tuple[str | None, str | None, str | None]:
    """Look up (country_name, region, continent) from an ISO-3 code.

    Returns (None, None, None) if code is not recognised.
    """
    code_str = str(code).strip().upper()
    meta = ALPHA3_TO_META.get(code_str)
    if meta:
        return meta["name"], meta["region"], meta["continent"]
    return None, None, None
