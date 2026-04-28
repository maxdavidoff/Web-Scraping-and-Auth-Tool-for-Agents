from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .config import PROCESSED_DIR
from .decision_packet import CampusLocation, create_housing_decision_packet
from .search_runner import OhanaSearchOptions, OhanaSearchResult, run_ohana_search
from .storage import write_json


DEFAULT_AGENT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


@dataclass(frozen=True)
class StudentHousingSearchPlan:
    location: str
    movein: str | None = None
    moveout: str | None = None
    property_types: list[str] | None = None
    type_of_places: list[str] | None = None
    num_bedrooms: int | None = None
    min_price: int | None = None
    max_price: int | None = None
    pet_policy: list[str] | None = None
    furnished_status: list[str] | None = None
    max_listings: int = 10
    notes: list[str] | None = None
    assumptions: list[str] | None = None


@dataclass(frozen=True)
class StudentHousingAgentResult:
    plan: StudentHousingSearchPlan
    search: OhanaSearchResult
    summary: str
    decision_packet: dict[str, Any] | None = None
    decision_packet_output: Path | None = None


@dataclass(frozen=True)
class IntakeDecision:
    status: str
    message: str
    refined_request: str


PLANNER_SYSTEM_PROMPT = """
You plan Ohana housing searches for students.

Convert the student's request into one JSON object with exactly these keys:
location, movein, moveout, property_types, type_of_places, num_bedrooms,
min_price, max_price, pet_policy, furnished_status, max_listings, notes,
assumptions.

Rules:
- location is required. Use a city/neighborhood/university area that Ohana search can understand.
- Format movein and moveout as 'Month D, YYYY', for example 'May 1, 2026'.
- Use null when the student did not specify a filter.
- property_types can include values such as 'Apartment' or 'House'.
- type_of_places can include values such as 'Private room', 'Shared room', or 'Entire place'.
- pet_policy and furnished_status should be lists only when explicitly requested.
- Convert budgets like 'under 1800' into max_price.
- If the student wants to sublet a room alone, prefer type_of_places like 'Private room' or 'Shared room' when stated.
- If the student wants a longer lease with friends, capture the friend count/group size in notes and use num_bedrooms when clear.
- max_listings should be a small integer from 1 to 50. Default to 10.
- Put preferences that Ohana cannot directly filter on in notes.
- Always preserve whether this is a solo room/sublet search or a longer lease/group search in notes.
- Put any inference you made in assumptions.
- Return JSON only.
""".strip()


INTAKE_SYSTEM_PROMPT = """
You are a student-housing intake assistant before an Ohana search.

Given the conversation so far, either ask one follow-up question, finalize the
search request, or end without searching. Return one JSON object with exactly:
status, message, refined_request.

status must be:
- ask: ask one concise follow-up question.
- ready: enough detail is known or the user said they are done.
- end: the user explicitly canceled or does not want to search.

You should try to learn:
- location, neighborhood, campus, or city.
- dates or timing.
- budget.
- whether the user wants to sublet a room alone from someone, or wants a longer lease with multiple friends.
- if solo: private room, shared room, entire place, furnished, pets, or other essentials.
- if with friends: number of friends/group size, bedrooms, lease length, and combined or per-person budget.

Ask at most one question at a time. Do not ask more once the user says things
like "that's all", "thats all", "that's it", "done", "no more", "run it", or
"search now"; in those cases, status must be ready. If the location is missing,
ask for it unless the user has already said they are done.

refined_request should be a compact plain-English search request that preserves
all known criteria, especially solo room/sublet versus longer lease with friends.
Return JSON only.
""".strip()


SUMMARY_SYSTEM_PROMPT = """
You help students compare housing results. Be concise, practical, and honest.
Use only the supplied listing data. Do not invent amenities, distances, safety
claims, availability, or contact details. If results are thin or noisy, say so.
""".strip()


FOLLOW_UP_QUESTION_SYSTEM_PROMPT = """
You generate decision-driving follow-up questions for a student comparing
housing options. Use only the supplied decision packet data. Do not invent
commutes, amenities, neighborhood facts, safety claims, or availability.

Return one JSON object with exactly this shape:
{"questions":[{"question":"...","why":"...","option_ids":["..."]}]}

Rules:
- Write 3 to 5 questions.
- Each question should emphasize an actual difference between options, such as
  price versus campus distance, furnished versus unfurnished, move-in timing,
  stronger photos, amenity gaps, or whether to enrich neighborhood data first.
- Ask concise questions that help the student decide or choose the next zoom-in.
- Use option_ids only from the supplied options.
- If data is missing, ask whether to run the specific enrichment before ranking.
""".strip()


DONE_PHRASES = {
    "done",
    "go ahead",
    "no more",
    "run it",
    "run search",
    "search now",
    "start search",
    "thats all",
    "that's all",
    "that is all",
    "thats it",
    "that's it",
    "use that",
}
CANCEL_PHRASES = {"cancel", "exit", "quit", "stop"}


def _openai_client():
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Set OPENAI_API_KEY in your environment or .env before running the housing agent.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("The housing agent needs the openai package. Run: pip install -r requirements.txt") from exc

    return OpenAI()


def user_wants_to_finalize_intake(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.lower().replace("’", "'")).strip(" .!,")
    return normalized in DONE_PHRASES or any(phrase in normalized for phrase in DONE_PHRASES if " " in phrase)


def user_wants_to_cancel_intake(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.lower().replace("’", "'")).strip(" .!,")
    return normalized in CANCEL_PHRASES


def _json_from_text(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise
        data = json.loads(match.group(0))

    if not isinstance(data, dict):
        raise ValueError("LLM planner returned JSON, but it was not an object.")
    return data


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any, *, minimum: int | None = None, maximum: int | None = None) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if minimum is not None:
        number = max(number, minimum)
    if maximum is not None:
        number = min(number, maximum)
    return number


def _optional_string_list(value: Any) -> list[str] | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = value
    else:
        return None

    cleaned = [str(item).strip() for item in items if str(item).strip()]
    return cleaned or None


def _intake_decision_from_dict(data: dict[str, Any]) -> IntakeDecision:
    status = _optional_string(data.get("status")) or "ask"
    if status not in {"ask", "ready", "end"}:
        status = "ask"

    return IntakeDecision(
        status=status,
        message=_optional_string(data.get("message")) or "",
        refined_request=_optional_string(data.get("refined_request")) or "",
    )


def _plan_from_dict(data: dict[str, Any]) -> StudentHousingSearchPlan:
    location = _optional_string(data.get("location"))
    if not location:
        raise ValueError("The housing request did not include enough information to infer a location.")

    return StudentHousingSearchPlan(
        location=location,
        movein=_optional_string(data.get("movein")),
        moveout=_optional_string(data.get("moveout")),
        property_types=_optional_string_list(data.get("property_types")),
        type_of_places=_optional_string_list(data.get("type_of_places")),
        num_bedrooms=_optional_int(data.get("num_bedrooms"), minimum=0),
        min_price=_optional_int(data.get("min_price"), minimum=0),
        max_price=_optional_int(data.get("max_price"), minimum=0),
        pet_policy=_optional_string_list(data.get("pet_policy")),
        furnished_status=_optional_string_list(data.get("furnished_status")),
        max_listings=_optional_int(data.get("max_listings"), minimum=1, maximum=50) or 10,
        notes=_optional_string_list(data.get("notes")),
        assumptions=_optional_string_list(data.get("assumptions")),
    )


def format_intake_transcript(messages: list[dict[str, str]]) -> str:
    lines = ["Student housing intake transcript:"]
    for message in messages:
        role = "Assistant" if message["role"] == "assistant" else "Student"
        lines.append(f"{role}: {message['content']}")
    return "\n".join(lines)


def decide_next_intake_step(
    messages: list[dict[str, str]],
    *,
    model: str = DEFAULT_AGENT_MODEL,
) -> IntakeDecision:
    if messages:
        last_user_messages = [message["content"] for message in messages if message["role"] == "user"]
        if last_user_messages:
            last_user_message = last_user_messages[-1]
            if user_wants_to_cancel_intake(last_user_message):
                return IntakeDecision(status="end", message="Okay, ending the housing search session.", refined_request="")
            if user_wants_to_finalize_intake(last_user_message):
                return IntakeDecision(
                    status="ready",
                    message="Got it. I will search with what you have shared.",
                    refined_request=format_intake_transcript(messages),
                )

    client = _openai_client()
    response = client.chat.completions.create(
        model=model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": INTAKE_SYSTEM_PROMPT},
            {"role": "user", "content": format_intake_transcript(messages)},
        ],
    )
    decision = _intake_decision_from_dict(_json_from_text(response.choices[0].message.content or "{}"))
    if not decision.refined_request:
        decision = IntakeDecision(
            status=decision.status,
            message=decision.message,
            refined_request=format_intake_transcript(messages),
        )
    return decision


def collect_interactive_housing_request(
    *,
    model: str = DEFAULT_AGENT_MODEL,
    initial_request: str | None = None,
    max_followups: int = 6,
) -> str | None:
    messages: list[dict[str, str]] = []

    if initial_request:
        print(f"Student housing request: {initial_request}")
        messages.append({"role": "user", "content": initial_request})
    else:
        print("What are you looking for in a sublet or student housing lease?")
        first_answer = input("> ").strip()
        if not first_answer or user_wants_to_cancel_intake(first_answer):
            print("Okay, ending the housing search session.")
            return None
        messages.append({"role": "user", "content": first_answer})

    final_request = format_intake_transcript(messages)

    for _ in range(max_followups):
        decision = decide_next_intake_step(messages, model=model)
        if decision.refined_request:
            final_request = decision.refined_request

        if decision.status == "end":
            if decision.message:
                print(decision.message)
            return None

        if decision.status == "ready":
            if decision.message:
                print(decision.message)
            return final_request

        question = decision.message.strip()
        if not question:
            return final_request

        print(question)
        messages.append({"role": "assistant", "content": question})
        answer = input("> ").strip()
        if not answer:
            print("Got it. I will search with what you have shared.")
            return final_request
        messages.append({"role": "user", "content": answer})
        final_request = format_intake_transcript(messages)

        if user_wants_to_cancel_intake(answer):
            print("Okay, ending the housing search session.")
            return None
        if user_wants_to_finalize_intake(answer):
            print("Got it. I will search with what you have shared.")
            return format_intake_transcript(messages)

    print("I have enough to start searching.")
    return final_request


def plan_student_housing_search(
    user_request: str,
    *,
    model: str = DEFAULT_AGENT_MODEL,
    today: date | None = None,
) -> StudentHousingSearchPlan:
    client = _openai_client()
    current_date = today or date.today()

    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Today's date is {current_date.isoformat()}.\n"
                    f"Student housing request:\n{user_request}"
                ),
            },
        ],
    )

    content = response.choices[0].message.content or "{}"
    return _plan_from_dict(_json_from_text(content))


def plan_to_ohana_options(
    plan: StudentHousingSearchPlan,
    *,
    state_file: str | None = None,
    selectors_file: str | None = None,
    max_listings_override: int | None = None,
    scrolls: int = 3,
    headless: bool = True,
    fetch_listing_api: bool = False,
    capture_detail_urls: bool = False,
) -> OhanaSearchOptions:
    return OhanaSearchOptions(
        location=plan.location,
        movein=plan.movein,
        moveout=plan.moveout,
        property_types=plan.property_types,
        type_of_places=plan.type_of_places,
        num_bedrooms=plan.num_bedrooms,
        min_price=plan.min_price,
        max_price=plan.max_price,
        pet_policy=plan.pet_policy,
        furnished_status=plan.furnished_status,
        state_file=state_file,
        selectors_file=selectors_file,
        max_listings=max_listings_override or plan.max_listings,
        scrolls=scrolls,
        headless=headless,
        fetch_listing_api=fetch_listing_api,
        capture_detail_urls=capture_detail_urls,
    )


def summarize_housing_results(
    *,
    user_request: str,
    plan: StudentHousingSearchPlan,
    records: list[dict[str, Any]],
    model: str = DEFAULT_AGENT_MODEL,
) -> str:
    if not records:
        return "I did not find any extracted listings for that search. Check the debug screenshot/HTML to see whether Ohana showed results or whether selectors need updating."

    client = _openai_client()
    compact_records = [
        {
            "title": record.get("title"),
            "price": record.get("price"),
            "location": record.get("location") or record.get("listing_address"),
            "dates": record.get("dates"),
            "bedrooms": record.get("bedrooms"),
            "url": record.get("detail_url") or record.get("url"),
            "raw_text": str(record.get("raw_text", ""))[:800],
        }
        for record in records[: min(len(records), 12)]
    ]

    response = client.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "student_request": user_request,
                        "search_plan": asdict(plan),
                        "listings": compact_records,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    )
    return (response.choices[0].message.content or "").strip()


def generate_decision_follow_up_questions(
    *,
    decision_packet: dict[str, Any],
    model: str = DEFAULT_AGENT_MODEL,
) -> list[dict[str, Any]]:
    ranked_options = decision_packet.get("ranked_options", [])
    if not ranked_options:
        return []

    compact_options = [
        {
            "id": option.get("id"),
            "title": option.get("title"),
            "price": option.get("price"),
            "price_amount": option.get("price_amount"),
            "distance_to_campus_miles": option.get("distance_to_campus_miles"),
            "move_in_dates": option.get("move_in_dates"),
            "bedrooms": option.get("bedrooms"),
            "amenities": option.get("amenities", [])[:8],
            "fit_signals": option.get("fit_signals", []),
            "concerns": option.get("concerns", []),
            "score": option.get("score"),
        }
        for option in ranked_options[: min(len(ranked_options), 8)]
    ]

    client = _openai_client()
    response = client.chat.completions.create(
        model=model,
        temperature=0.25,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": FOLLOW_UP_QUESTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "student_request": decision_packet.get("student_request"),
                        "decision_weights": decision_packet.get("decision_weights"),
                        "missing_data": decision_packet.get("missing_data"),
                        "suggested_next_tool_calls": decision_packet.get("suggested_next_tool_calls"),
                        "options": compact_options,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    )

    data = _json_from_text(response.choices[0].message.content or "{}")
    questions = data.get("questions")
    if not isinstance(questions, list):
        return []

    valid_ids = {str(option.get("id")) for option in compact_options if option.get("id")}
    cleaned: list[dict[str, Any]] = []
    for item in questions:
        if not isinstance(item, dict):
            continue
        question = _optional_string(item.get("question"))
        if not question:
            continue
        option_ids = [
            str(option_id)
            for option_id in item.get("option_ids", [])
            if str(option_id) in valid_ids
        ]
        cleaned.append(
            {
                "question": question,
                "why": _optional_string(item.get("why")) or "",
                "option_ids": option_ids,
            }
        )

    return cleaned[:5]


def decision_packet_output_path(search: OhanaSearchResult) -> Path:
    stem = search.csv_output.stem.replace("ohana_results", "housing_decision_packet")
    if stem == search.csv_output.stem:
        stem = f"housing_decision_packet_{search.csv_output.stem}"
    return PROCESSED_DIR / f"{stem}.json"


def run_student_housing_agent(
    user_request: str,
    *,
    model: str = DEFAULT_AGENT_MODEL,
    state_file: str | None = None,
    selectors_file: str | None = None,
    max_listings: int | None = None,
    scrolls: int = 3,
    headless: bool = True,
    fetch_listing_api: bool = False,
    capture_detail_urls: bool = False,
    summarize: bool = True,
    build_decision_packet: bool = True,
    campus_location: str | None = None,
    campus_latitude: float | None = None,
    campus_longitude: float | None = None,
) -> StudentHousingAgentResult:
    plan = plan_student_housing_search(user_request, model=model)
    search = run_ohana_search(
        plan_to_ohana_options(
            plan,
            state_file=state_file,
            selectors_file=selectors_file,
            max_listings_override=max_listings,
            scrolls=scrolls,
            headless=headless,
            fetch_listing_api=fetch_listing_api,
            capture_detail_urls=capture_detail_urls,
        )
    )
    summary = ""
    if summarize:
        try:
            summary = summarize_housing_results(
                user_request=user_request,
                plan=plan,
                records=search.records,
                model=model,
            )
        except Exception as exc:
            summary = f"Summary unavailable after scraping: {exc}"

    decision_packet: dict[str, Any] | None = None
    packet_output: Path | None = None
    if build_decision_packet:
        campus = CampusLocation(
            label=campus_location or plan.location,
            latitude=campus_latitude,
            longitude=campus_longitude,
        )
        decision_packet = create_housing_decision_packet(
            user_request=user_request,
            search_plan=asdict(plan),
            records=search.records,
            campus=campus,
        )
        try:
            generated_questions = generate_decision_follow_up_questions(
                decision_packet=decision_packet,
                model=model,
            )
            if generated_questions:
                decision_packet["recommended_follow_up_questions"] = generated_questions
        except Exception as exc:
            decision_packet["follow_up_question_generation_error"] = str(exc)

        packet_output = write_json(decision_packet, decision_packet_output_path(search))

    return StudentHousingAgentResult(
        plan=plan,
        search=search,
        summary=summary,
        decision_packet=decision_packet,
        decision_packet_output=packet_output,
    )
