# Country Enrichment

Enrich partner country data: name or ISO3 code → (ISO3, region, continent).

## Setup (module-level, run once)

```python
import country_converter as coco
import pycountry
from rapidfuzz import process, fuzz

cc = coco.CountryConverter()

COUNTRY_NAMES = [c.name for c in pycountry.countries]
NAME_TO_ALPHA3 = {c.name.upper(): c.alpha_3 for c in pycountry.countries}
ALPHA3_TO_META = {
    c.alpha_3: {
        "name": c.name,
        "continent": cc.convert(names=c.alpha_3, to="continent"),
        "region": cc.convert(names=c.alpha_3, to="UNregion"),
    }
    for c in pycountry.countries
}

# Add aliases for common misspellings in source data
COUNTRY_ALIASES = {
    "MYANMA": "Myanmar",
    "MEHICO": "Mexico",
    "BRAXIN": "Brazil",
    "UCRAINA": "Ukraine",
}
```

## Resolve from ISO3 Code

```python
def resolve_from_country_code(code) -> tuple[str, str, str]:
    """ISO3 code → (name, region, continent)"""
    meta = ALPHA3_TO_META.get(str(code).strip().upper())
    if meta:
        return meta["name"], meta["region"], meta["continent"]
    return None, None, None
```

## Resolve from Country Name

```python
def resolve_from_country_name(name: str) -> tuple[str, str, str, str]:
    """Country name → (iso3_code, region, continent, cleaned_name)"""
    country = COUNTRY_ALIASES.get(str(name).strip().upper(), str(name).strip())

    # 1. Exact match
    code = NAME_TO_ALPHA3.get(country.upper())
    if code:
        meta = ALPHA3_TO_META[code]
        return code, meta["region"], meta["continent"], country

    # 2. country_converter lookup
    try:
        iso3 = cc.convert(names=country, to="ISO3")
        if iso3 and iso3 != "not found":
            meta = ALPHA3_TO_META.get(iso3)
            return iso3, meta["region"], meta["continent"], country
    except Exception:
        pass

    # 3. Fuzzy match (threshold 70)
    match = process.extractOne(country, COUNTRY_NAMES, scorer=fuzz.WRatio)
    if match and match[1] > 70:
        code = NAME_TO_ALPHA3.get(match[0].upper())
        meta = ALPHA3_TO_META.get(code)
        return code, meta["region"], meta["continent"], country

    return None, None, None, country
```

## Apply in DataFrame

```python
# Rows that have partner_code → resolve name/region/continent from code
mask_code = df["partner_code"].notna()
if mask_code.any():
    resolved = df.loc[mask_code, "partner_code"].apply(
        lambda x: pd.Series(resolve_from_country_code(x))
    )
    df.loc[mask_code, "partner_name"] = resolved[0].values
    df.loc[mask_code, "partner_region"] = resolved[1].values
    df.loc[mask_code, "partner_continent"] = resolved[2].values

# Rows that only have partner_name → resolve code/region/continent from name
mask_name = ~mask_code
if mask_name.any():
    resolved = df.loc[mask_name, "partner_name"].apply(
        lambda x: pd.Series(resolve_from_country_name(x))
    )
    df.loc[mask_name, "partner_code"] = resolved[0].values
    df.loc[mask_name, "partner_region"] = resolved[1].values
    df.loc[mask_name, "partner_continent"] = resolved[2].values
    df.loc[mask_name, "partner_name"] = resolved[3].values
```
