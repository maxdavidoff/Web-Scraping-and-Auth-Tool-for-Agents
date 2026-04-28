from .provider_capabilities import (
    AFFORDABLEHOUSING,
    OHANA,
    PROVIDER_CAPABILITIES,
    RENTALSOURCE,
    capability_matrix,
    get_provider_capabilities,
    list_provider_capabilities,
)
from .intent_extractor import (
    INTENT_SYSTEM_PROMPT,
    INTENT_UPDATE_SYSTEM_PROMPT,
    IntentExtractionResult,
    build_intent_messages,
    build_intent_update_messages,
    extract_housing_intent,
    intent_from_mapping,
    parse_json_object,
    update_housing_intent,
)
from .llm_client import (
    DEFAULT_MISTRAL_MODEL,
    LLMClientError,
    MistralChatClient,
)
from .listing_ranker import (
    LISTING_RANKER_SYSTEM_PROMPT,
    build_listing_ranker_messages,
    rank_listings,
    ranking_from_mapping,
)
from .query_planner import (
    classify_filters,
    coerce_intent,
    plan_provider_query,
    plan_query,
    requested_filters,
    score_provider_query,
)
from .readiness_evaluator import (
    READINESS_SYSTEM_PROMPT,
    apply_readiness_guards,
    build_readiness_messages,
    evaluate_search_readiness,
    readiness_from_mapping,
)
from .topic_guard import (
    TOPIC_GUARD_SYSTEM_PROMPT,
    MessageTopicResult,
    build_topic_guard_messages,
    evaluate_message_topic,
    topic_result_from_mapping,
)
from .types import (
    FilterApplicationReport,
    FilterCapability,
    HousingSearchIntent,
    ListingRankingResult,
    NormalizedListing,
    ProviderCapabilities,
    ProviderQueryPlan,
    QueryPlan,
    RankedListing,
    SearchReadiness,
    SupportCategory,
)


def __getattr__(name):
    if name in {"AgentTurn", "InteractiveHousingAgent"}:
        from .interactive_agent import AgentTurn, InteractiveHousingAgent

        return {"AgentTurn": AgentTurn, "InteractiveHousingAgent": InteractiveHousingAgent}[name]
    raise AttributeError(name)


__all__ = [
    "AFFORDABLEHOUSING",
    "OHANA",
    "PROVIDER_CAPABILITIES",
    "RENTALSOURCE",
    "FilterApplicationReport",
    "FilterCapability",
    "HousingSearchIntent",
    "INTENT_SYSTEM_PROMPT",
    "INTENT_UPDATE_SYSTEM_PROMPT",
    "LISTING_RANKER_SYSTEM_PROMPT",
    "READINESS_SYSTEM_PROMPT",
    "TOPIC_GUARD_SYSTEM_PROMPT",
    "AgentTurn",
    "InteractiveHousingAgent",
    "IntentExtractionResult",
    "LLMClientError",
    "ListingRankingResult",
    "MessageTopicResult",
    "MistralChatClient",
    "NormalizedListing",
    "ProviderCapabilities",
    "ProviderQueryPlan",
    "QueryPlan",
    "RankedListing",
    "SearchReadiness",
    "SupportCategory",
    "DEFAULT_MISTRAL_MODEL",
    "apply_readiness_guards",
    "build_intent_messages",
    "build_intent_update_messages",
    "build_listing_ranker_messages",
    "build_readiness_messages",
    "build_topic_guard_messages",
    "capability_matrix",
    "classify_filters",
    "coerce_intent",
    "evaluate_search_readiness",
    "evaluate_message_topic",
    "extract_housing_intent",
    "get_provider_capabilities",
    "intent_from_mapping",
    "list_provider_capabilities",
    "parse_json_object",
    "plan_provider_query",
    "plan_query",
    "rank_listings",
    "ranking_from_mapping",
    "readiness_from_mapping",
    "requested_filters",
    "score_provider_query",
    "topic_result_from_mapping",
    "update_housing_intent",
]
