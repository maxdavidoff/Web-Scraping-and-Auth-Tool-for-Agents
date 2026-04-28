from __future__ import annotations

from types import MappingProxyType

from .types import FilterCapability, ProviderCapabilities, SupportCategory


OHANA = "ohana"
RENTALSOURCE = "rentalsource"
AFFORDABLEHOUSING = "affordablehousing"
APARTMENTS_COM = "apartments_com"


def _cap(
    filter_name: str,
    category: SupportCategory,
    *,
    verified: bool,
    source_field: str | None = None,
    notes: str = "",
    warning: str = "",
    post_filter_possible: bool = False,
    supported_values: tuple[str, ...] = (),
) -> FilterCapability:
    return FilterCapability(
        filter_name=filter_name,
        category=category,
        verified=verified,
        source_field=source_field,
        notes=notes,
        warning=warning,
        post_filter_possible=post_filter_possible,
        supported_values=supported_values,
    )


_OHANA_FILTERS = {
    "location": _cap(
        "location",
        SupportCategory.PATH_SEGMENT,
        verified=True,
        source_field="location_slug",
        notes="Canonical search pattern is /sublet/{location_slug}.",
    ),
    "min_price": _cap("min_price", SupportCategory.SOURCE_FILTER, verified=True),
    "max_price": _cap("max_price", SupportCategory.SOURCE_FILTER, verified=True),
    "bedrooms": _cap("bedrooms", SupportCategory.SOURCE_FILTER, verified=True, source_field="num_bedrooms"),
    "property_types": _cap("property_types", SupportCategory.SOURCE_FILTER, verified=True),
    "type_of_places": _cap(
        "type_of_places",
        SupportCategory.SOURCE_FILTER,
        verified=True,
        source_field="place_type",
        notes="Also observed as type_of_places in the current Ohana URL builder.",
    ),
    "place_type": _cap("place_type", SupportCategory.SOURCE_FILTER, verified=True, source_field="type_of_places"),
    "pet_policy": _cap("pet_policy", SupportCategory.SOURCE_FILTER, verified=True),
    "furnished": _cap("furnished", SupportCategory.SOURCE_FILTER, verified=True, source_field="furnished_status"),
    "move_in_date": _cap(
        "move_in_date",
        SupportCategory.UNKNOWN,
        verified=False,
        source_field="movein",
        notes="Date URL fields exist in code paths, but research has not verified source behavior.",
    ),
    "move_out_date": _cap(
        "move_out_date",
        SupportCategory.UNKNOWN,
        verified=False,
        source_field="moveout",
        notes="Date URL fields exist in code paths, but research has not verified source behavior.",
    ),
    "bathrooms": _cap("bathrooms", SupportCategory.UNKNOWN, verified=False, notes="Unsupported or unknown."),
    "bathroom_min": _cap("bathroom_min", SupportCategory.UNKNOWN, verified=False, notes="Unsupported or unknown."),
    "amenities": _cap("amenities", SupportCategory.UNKNOWN, verified=False, notes="Unsupported or unknown."),
    "sort": _cap("sort", SupportCategory.UNKNOWN, verified=False, notes="Unsupported or unknown."),
    "map_bounds": _cap("map_bounds", SupportCategory.UNKNOWN, verified=False, notes="Unsupported or unknown."),
}


_RENTALSOURCE_FILTERS = {
    "location": _cap("location", SupportCategory.PATH_SEGMENT, verified=True, source_field="location_slug"),
    "min_price": _cap("min_price", SupportCategory.QUERY_PARAM, verified=True, source_field="min"),
    "max_price": _cap("max_price", SupportCategory.QUERY_PARAM, verified=True, source_field="max"),
    "bedrooms": _cap("bedrooms", SupportCategory.QUERY_PARAM, verified=True, source_field="beds"),
    "bedroom_min": _cap(
        "bedroom_min",
        SupportCategory.QUERY_PARAM,
        verified=True,
        source_field="beds",
        notes="RentalSource exposes a beds query parameter; the planner treats minimum bedroom intent as targetable.",
    ),
    "bathrooms": _cap("bathrooms", SupportCategory.QUERY_PARAM, verified=True, source_field="baths"),
    "bathroom_min": _cap(
        "bathroom_min",
        SupportCategory.QUERY_PARAM,
        verified=True,
        source_field="baths",
        notes="RentalSource exposes a baths query parameter; the planner treats minimum bathroom intent as targetable.",
    ),
    "property_types": _cap("property_types", SupportCategory.QUERY_PARAM, verified=True, source_field="types[]"),
    "pet_policy": _cap("pet_policy", SupportCategory.QUERY_PARAM, verified=True, source_field="pets"),
    "photos": _cap("photos", SupportCategory.QUERY_PARAM, verified=True, source_field="photos"),
    "verified_listings": _cap("verified_listings", SupportCategory.QUERY_PARAM, verified=True, source_field="verified"),
    "featured": _cap("featured", SupportCategory.QUERY_PARAM, verified=True, source_field="featured"),
    "sort": _cap("sort", SupportCategory.QUERY_PARAM, verified=True, source_field="sort"),
    "page": _cap("page", SupportCategory.QUERY_PARAM, verified=True, source_field="page"),
    "furnished": _cap("furnished", SupportCategory.UNKNOWN, verified=False, notes="Weak/unverified support."),
    "type_of_places": _cap(
        "type_of_places",
        SupportCategory.UNKNOWN,
        verified=False,
        notes="Private-room/shared-room targeting is weak on RentalSource.",
    ),
    "move_in_date": _cap("move_in_date", SupportCategory.UNKNOWN, verified=False, notes="Weak/unverified support."),
    "move_out_date": _cap("move_out_date", SupportCategory.UNKNOWN, verified=False, notes="Weak/unverified support."),
    "amenities": _cap("amenities", SupportCategory.UNKNOWN, verified=False),
    "keyword": _cap("keyword", SupportCategory.UNKNOWN, verified=False),
    "map_bounds": _cap("map_bounds", SupportCategory.UNSUPPORTED, verified=True),
    "section8": _cap("section8", SupportCategory.UNSUPPORTED, verified=True),
    "income_restricted": _cap("income_restricted", SupportCategory.UNSUPPORTED, verified=True),
    "wheelchair_accessible": _cap("wheelchair_accessible", SupportCategory.UNSUPPORTED, verified=True),
    "utilities_included": _cap("utilities_included", SupportCategory.UNSUPPORTED, verified=True),
    "washer_dryer": _cap("washer_dryer", SupportCategory.UNSUPPORTED, verified=True),
}


_AFFORDABLEHOUSING_FILTERS = {
    "location": _cap("location", SupportCategory.PATH_SEGMENT, verified=True, source_field="location_slug"),
    "property_types": _cap("property_types", SupportCategory.PATH_SEGMENT, verified=True, source_field="property_type"),
    "bedrooms": _cap("bedrooms", SupportCategory.PATH_SEGMENT, verified=True, source_field="bedroom_slug"),
    "max_price": _cap("max_price", SupportCategory.PATH_SEGMENT, verified=True, source_field="under-{max_price}"),
    "pet_policy": _cap("pet_policy", SupportCategory.PATH_SEGMENT, verified=True, source_field="pet-friendly"),
    "pet_friendly": _cap("pet_friendly", SupportCategory.PATH_SEGMENT, verified=True, source_field="pet-friendly"),
    "section8": _cap("section8", SupportCategory.PATH_SEGMENT, verified=True, source_field="section8-owners"),
    "income_restricted": _cap(
        "income_restricted",
        SupportCategory.PATH_SEGMENT,
        verified=True,
        source_field="income-restricted",
    ),
    "wheelchair_accessible": _cap(
        "wheelchair_accessible",
        SupportCategory.PATH_SEGMENT,
        verified=True,
        source_field="wheelchair-accessible",
    ),
    "utilities_included": _cap(
        "utilities_included",
        SupportCategory.PATH_SEGMENT,
        verified=True,
        source_field="utilities-included",
    ),
    "washer_dryer": _cap("washer_dryer", SupportCategory.PATH_SEGMENT, verified=True, source_field="washer-dryer"),
    "min_price": _cap(
        "min_price",
        SupportCategory.POST_FILTER,
        verified=True,
        warning="AffordableHousing has no verified source-side minimum price filter; apply after retrieval.",
        post_filter_possible=True,
    ),
    "bathrooms": _cap("bathrooms", SupportCategory.UNKNOWN, verified=False),
    "bathroom_min": _cap("bathroom_min", SupportCategory.UNKNOWN, verified=False),
    "move_in_date": _cap("move_in_date", SupportCategory.UNKNOWN, verified=False),
    "move_out_date": _cap("move_out_date", SupportCategory.UNKNOWN, verified=False),
    "amenities": _cap("amenities", SupportCategory.UNKNOWN, verified=False),
    "sort": _cap("sort", SupportCategory.UNKNOWN, verified=False),
    "map_bounds": _cap("map_bounds", SupportCategory.UNSUPPORTED, verified=True),
    "keyword": _cap("keyword", SupportCategory.UNKNOWN, verified=False),
}


_APARTMENTS_COM_FILTERS = {
    "location": _cap("location", SupportCategory.PATH_SEGMENT, verified=True, source_field="location_slug"),
    "min_price": _cap("min_price", SupportCategory.PATH_SEGMENT, verified=True, source_field="price_min"),
    "max_price": _cap("max_price", SupportCategory.PATH_SEGMENT, verified=True, source_field="price_max"),
    "bedrooms": _cap(
        "bedrooms",
        SupportCategory.PATH_SEGMENT,
        verified=True,
        source_field="beds",
        notes="Exact bedroom intent can be represented by matching min/max bedroom URL filters.",
    ),
    "bedroom_min": _cap("bedroom_min", SupportCategory.PATH_SEGMENT, verified=True, source_field="bed_min"),
    "bedroom_max": _cap("bedroom_max", SupportCategory.PATH_SEGMENT, verified=True, source_field="bed_max"),
    "bathroom_min": _cap("bathroom_min", SupportCategory.PATH_SEGMENT, verified=True, source_field="bath_min"),
    "bathrooms": _cap(
        "bathrooms",
        SupportCategory.PATH_SEGMENT,
        verified=True,
        source_field="bath_min",
        notes="Apartments.com research verified bathroom minimum, not exact bathroom matching.",
    ),
    "map_bounds": _cap("map_bounds", SupportCategory.QUERY_PARAM, verified=True, source_field="bb"),
    "amenities": _cap(
        "amenities",
        SupportCategory.NETWORK_PAYLOAD,
        verified=False,
        notes="Observed in network payload fields but not verified as stable.",
    ),
    "move_in_date": _cap(
        "move_in_date",
        SupportCategory.NETWORK_PAYLOAD,
        verified=False,
        notes="Observed in network payload fields but not verified as stable.",
    ),
    "property_types": _cap(
        "property_types",
        SupportCategory.NETWORK_PAYLOAD,
        verified=False,
        source_field="home_type",
        notes="Observed as home_type in network payload fields but not verified as stable.",
    ),
    "home_type": _cap(
        "home_type",
        SupportCategory.NETWORK_PAYLOAD,
        verified=False,
        notes="Observed in network payload fields but not verified as stable.",
    ),
    "pet_policy": _cap(
        "pet_policy",
        SupportCategory.NETWORK_PAYLOAD,
        verified=False,
        notes="Observed in network payload fields but not verified as stable.",
    ),
    "sort": _cap(
        "sort",
        SupportCategory.NETWORK_PAYLOAD,
        verified=False,
        notes="Observed in network payload fields but not verified as stable.",
    ),
    "keyword": _cap(
        "keyword",
        SupportCategory.NETWORK_PAYLOAD,
        verified=False,
        notes="Observed in network payload fields but not verified as stable.",
    ),
    "furnished": _cap("furnished", SupportCategory.UNKNOWN, verified=False),
    "move_out_date": _cap("move_out_date", SupportCategory.UNKNOWN, verified=False),
    "section8": _cap("section8", SupportCategory.UNSUPPORTED, verified=True),
    "income_restricted": _cap("income_restricted", SupportCategory.UNSUPPORTED, verified=True),
    "wheelchair_accessible": _cap("wheelchair_accessible", SupportCategory.UNKNOWN, verified=False),
    "utilities_included": _cap("utilities_included", SupportCategory.UNKNOWN, verified=False),
    "washer_dryer": _cap("washer_dryer", SupportCategory.NETWORK_PAYLOAD, verified=False),
}


PROVIDER_CAPABILITIES = MappingProxyType(
    {
        OHANA: ProviderCapabilities(
            provider=OHANA,
            implemented=True,
            requires_login=True,
            public=False,
            canonical_url_pattern="https://liveohana.ai/sublet/{location_slug}",
            filters=MappingProxyType(_OHANA_FILTERS),
            notes=(
                "Student/sublet oriented.",
                "Requires an authenticated Ohana session before scraping.",
            ),
        ),
        RENTALSOURCE: ProviderCapabilities(
            provider=RENTALSOURCE,
            implemented=True,
            requires_login=False,
            public=True,
            canonical_url_pattern="https://www.rentalsource.com/{location_slug}/?min=&max=&beds=&baths=",
            filters=MappingProxyType(_RENTALSOURCE_FILTERS),
            notes=("Strong public URL query targeting for general rentals.",),
        ),
        AFFORDABLEHOUSING: ProviderCapabilities(
            provider=AFFORDABLEHOUSING,
            implemented=True,
            requires_login=False,
            public=True,
            specialized=True,
            canonical_url_pattern="https://www.affordablehousing.com/{location_slug}/{seo_filter_segments}/",
            filters=MappingProxyType(_AFFORDABLEHOUSING_FILTERS),
            notes=("Specialized affordable, voucher, and income-restricted housing source.",),
        ),
        APARTMENTS_COM: ProviderCapabilities(
            provider=APARTMENTS_COM,
            implemented=False,
            requires_login=False,
            public=True,
            experimental=True,
            canonical_url_pattern="https://www.apartments.com/{location_slug}/{url_filter_segments}/?bb={bounds}",
            filters=MappingProxyType(_APARTMENTS_COM_FILTERS),
            notes=(
                "Experimental research target; no scraper is implemented in this repository yet.",
                "Some network-payload fields were observed but remain unverified.",
            ),
        ),
    }
)


PROVIDER_ALIASES = MappingProxyType(
    {
        "ohana": OHANA,
        "liveohana": OHANA,
        "rental-source": RENTALSOURCE,
        "rental_source": RENTALSOURCE,
        "rental source": RENTALSOURCE,
        "rentalsource": RENTALSOURCE,
        "affordable": AFFORDABLEHOUSING,
        "affordable-housing": AFFORDABLEHOUSING,
        "affordable_housing": AFFORDABLEHOUSING,
        "affordable housing": AFFORDABLEHOUSING,
        "affordablehousing": AFFORDABLEHOUSING,
        "affordablehousing.com": AFFORDABLEHOUSING,
        "apartments": APARTMENTS_COM,
        "apartments-com": APARTMENTS_COM,
        "apartments_com": APARTMENTS_COM,
        "apartments.com": APARTMENTS_COM,
    }
)


def capability_matrix() -> dict[str, ProviderCapabilities]:
    return dict(PROVIDER_CAPABILITIES)


def get_provider_capabilities(provider: str) -> ProviderCapabilities:
    key = PROVIDER_ALIASES.get(provider.strip().lower(), provider.strip().lower())
    try:
        return PROVIDER_CAPABILITIES[key]
    except KeyError as exc:
        expected = ", ".join(PROVIDER_CAPABILITIES)
        raise KeyError(f"Unknown provider {provider!r}. Expected one of: {expected}.") from exc


def list_provider_capabilities() -> tuple[ProviderCapabilities, ...]:
    return tuple(PROVIDER_CAPABILITIES.values())
