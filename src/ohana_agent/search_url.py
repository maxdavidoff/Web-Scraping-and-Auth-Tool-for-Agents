from urllib.parse import urlencode, quote


OHANA_BASE_SEARCH_URL = "https://liveohana.ai/search"


def _double_encoded_list(values: list[str]) -> str:
    """
    Ohana/Bubble expects some multi-word filter values double encoded.

    Example:
    "Private room" -> "Private%20room" -> "Private%2520room"
    """
    return ",".join(quote(value) for value in values)


def build_ohana_search_url(
    location: str,
    movein: str | None = None,
    moveout: str | None = None,
    property_types: list[str] | None = None,
    type_of_places: list[str] | None = None,
    num_bedrooms: int | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    pet_policy: list[str] | None = None,
    furnished_status: list[str] | None = None,
) -> str:
    params = {
        "location": location,
    }

    if movein:
        params["movein"] = movein

    if moveout:
        params["moveout"] = moveout

    if property_types:
        params["property_types"] = ",".join(property_types)

    if type_of_places:
        params["type_of_places"] = _double_encoded_list(type_of_places)

    if num_bedrooms is not None:
        params["num_bedrooms"] = str(num_bedrooms)

    if min_price is not None:
        params["min_price"] = str(min_price)

    if max_price is not None:
        params["max_price"] = str(max_price)

    if pet_policy:
        params["pet_policy"] = _double_encoded_list(pet_policy)

    if furnished_status:
        params["furnished_status"] = _double_encoded_list(furnished_status)

    return f"{OHANA_BASE_SEARCH_URL}?{urlencode(params)}"