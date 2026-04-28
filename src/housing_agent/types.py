from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class SupportCategory(str, Enum):
    SOURCE_FILTER = "source_filter"
    PATH_SEGMENT = "path_segment"
    QUERY_PARAM = "query_param"
    NETWORK_PAYLOAD = "network_payload"
    POST_FILTER = "post_filter"
    DETAIL_ENRICHMENT = "detail_enrichment"
    INFERENCE_ONLY = "inference_only"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


SOURCE_APPLICABLE_CATEGORIES = frozenset(
    {
        SupportCategory.SOURCE_FILTER,
        SupportCategory.PATH_SEGMENT,
        SupportCategory.QUERY_PARAM,
        SupportCategory.NETWORK_PAYLOAD,
    }
)


@dataclass(frozen=True)
class HousingSearchIntent:
    location: str | None = None
    neighborhoods: tuple[str, ...] = ()
    avoid_neighborhoods: tuple[str, ...] = ()
    min_price: int | None = None
    max_price: int | None = None
    price_basis: str = "unknown"
    bedrooms: int | None = None
    bedroom_min: int | None = None
    bedroom_max: int | None = None
    bathrooms: float | None = None
    bathroom_min: float | None = None
    property_types: tuple[str, ...] = ()
    type_of_places: tuple[str, ...] = ()
    pet_policy: tuple[str, ...] = ()
    furnished: bool | None = None
    move_in_date: str | None = None
    move_out_date: str | None = None
    lease_length: str | None = None
    campus_or_school: str | None = None
    commute_target: str | None = None
    max_commute_minutes: int | None = None
    roommate_count: int | None = None
    amenities: tuple[str, ...] = ()
    required_amenities: tuple[str, ...] = ()
    preferred_amenities: tuple[str, ...] = ()
    dealbreakers: tuple[str, ...] = ()
    safety_priority: str = "unknown"
    student_priority: str = "unknown"
    sort: str | None = None
    map_bounds: Mapping[str, float] | None = None
    photos: bool = False
    verified_listings: bool = False
    featured: bool = False
    page: int | None = None
    section8: bool = False
    income_restricted: bool = False
    wheelchair_accessible: bool = False
    utilities_included: bool = False
    washer_dryer: bool = False
    keyword: str | None = None
    intent_kind: str | None = None
    flexibility_notes: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchReadiness:
    ready_to_search: bool = False
    ready_to_recommend: bool = False
    confidence: str = "low"
    next_action: str = "ask_followup"
    missing_required_fields: tuple[str, ...] = ()
    hard_constraints: tuple[str, ...] = ()
    soft_preferences: tuple[str, ...] = ()
    safe_assumptions: tuple[str, ...] = ()
    followup_questions: tuple[str, ...] = ()
    reasoning_summary: str = ""


@dataclass(frozen=True)
class RankedListing:
    listing_id: str = ""
    title: str = ""
    url: str = ""
    fit_score: float = 0.0
    matched_constraints: tuple[str, ...] = ()
    missing_info: tuple[str, ...] = ()
    concerns: tuple[str, ...] = ()
    why_it_fits: str = ""
    provider: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ListingRankingResult:
    recommended: tuple[RankedListing, ...] = ()
    needs_verification: tuple[RankedListing, ...] = ()
    excluded: tuple[RankedListing, ...] = ()
    overall_summary: str = ""
    followup_suggestions: tuple[str, ...] = ()
    raw_response: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FilterCapability:
    filter_name: str
    category: SupportCategory
    verified: bool
    source_field: str | None = None
    notes: str = ""
    warning: str = ""
    post_filter_possible: bool = False
    supported_values: tuple[str, ...] = ()

    @property
    def is_verified_source_filter(self) -> bool:
        return self.verified and self.category in SOURCE_APPLICABLE_CATEGORIES


@dataclass(frozen=True)
class ProviderCapabilities:
    provider: str
    implemented: bool
    requires_login: bool = False
    public: bool = True
    specialized: bool = False
    experimental: bool = False
    canonical_url_pattern: str = ""
    filters: Mapping[str, FilterCapability] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def capability_for(self, filter_name: str) -> FilterCapability:
        capability = self.filters.get(filter_name)
        if capability is not None:
            return capability
        return FilterCapability(
            filter_name=filter_name,
            category=SupportCategory.UNKNOWN,
            verified=False,
            notes=f"No capability research recorded for {filter_name}.",
        )


@dataclass(frozen=True)
class FilterApplicationReport:
    provider: str
    applied_at_source: Mapping[str, Any] = field(default_factory=dict)
    post_filters: Mapping[str, Any] = field(default_factory=dict)
    unsupported: Mapping[str, Any] = field(default_factory=dict)
    unknown_unverified: Mapping[str, Any] = field(default_factory=dict)
    capabilities: Mapping[str, FilterCapability] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderQueryPlan:
    provider: str
    score: float
    quality: str
    implemented: bool
    requires_login: bool
    experimental: bool
    report: FilterApplicationReport
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueryPlan:
    intent: HousingSearchIntent
    provider_plans: tuple[ProviderQueryPlan, ...]

    @property
    def ranked_provider_names(self) -> tuple[str, ...]:
        return tuple(plan.provider for plan in self.provider_plans)

    def for_provider(self, provider: str) -> ProviderQueryPlan:
        for plan in self.provider_plans:
            if plan.provider == provider:
                return plan
        raise KeyError(f"No query plan for provider: {provider}")


@dataclass(frozen=True)
class NormalizedListing:
    provider: str
    title: str = ""
    listing_url: str = ""
    address: str = ""
    price: str = ""
    price_min: int | None = None
    price_max: int | None = None
    bedrooms: str = ""
    bathrooms: str = ""
    property_type: str = ""
    availability: str = ""
    image_urls: tuple[str, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)
