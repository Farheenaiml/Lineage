import base64
import json
from typing import Any
from urllib.parse import quote_plus


def _value(item: Any, key: str, default=None):
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _text_outputs(interaction: Any) -> list[str]:
    texts = []
    for output in _value(interaction, "outputs", []) or []:
        if _value(output, "type") == "text":
            text = _value(output, "text")
            if text:
                texts.append(text.strip())
    return texts


def _parse_queries(text: str) -> list[str]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start < 0 or end < start:
        raise ValueError("Gemini did not return a JSON array of search queries.")
    values = json.loads(cleaned[start:end + 1])
    if not isinstance(values, list):
        raise ValueError("Gemini search queries must be a JSON array.")

    unique_queries = []
    seen = set()
    for value in values:
        if not isinstance(value, str):
            continue
        query = " ".join(value.split())[:250]
        if query and query.casefold() not in seen:
            seen.add(query.casefold())
            unique_queries.append(query)
        if len(unique_queries) == 5:
            break
    if not unique_queries:
        raise ValueError("Gemini did not return any usable search queries.")
    return unique_queries


def generate_manual_search_queries(
    *, gemini_api_key: str, model_name: str, image_bytes: bytes, mime_type: str
) -> dict[str, Any]:
    """Describe an image and prepare manual search links without searching the web."""
    from google import genai

    client = genai.Client(api_key=gemini_api_key)
    try:
        encoded_image = base64.b64encode(image_bytes).decode("ascii")
        description_result = client.interactions.create(
            model=model_name,
            store=False,
            input=[
                {"type": "text", "text": (
                    "Describe this image for public-web search. Transcribe clearly visible text. "
                    "Mention distinctive objects, setting, clothing, and composition. Do not identify "
                    "people, infer private attributes, or claim whether the image is manipulated. "
                    "Return a concise factual description only."
                )},
                {"type": "image", "data": encoded_image, "mime_type": mime_type},
            ],
        )
        description = " ".join(_text_outputs(description_result)).strip()
        if not description:
            raise ValueError("Gemini did not return an image description.")

        query_result = client.interactions.create(
            model=model_name,
            store=False,
            input=(
                "Create up to five concise search-engine queries to help a human find public pages "
                "that may discuss or contain an image like the one described. Include distinctive "
                "visible text as quoted terms when useful. Do not identify people or assert that a page "
                "contains the exact image. Return only a JSON array of query strings.\n\n"
                f"Image description:\n{description}"
            ),
        )
        queries = _parse_queries(" ".join(_text_outputs(query_result)))
        search_links = [
            {
                "query": query,
                "google_url": f"https://www.google.com/search?q={quote_plus(query)}",
                "bing_url": f"https://www.bing.com/search?q={quote_plus(query)}",
            }
            for query in queries
        ]
        return {
            "image_description": description[:4000],
            "summary": (
                "Generated search phrases only. LINEAGE did not search the web or collect page results. "
                "Open a search link and manually add any page you verify using + Add Source."
            ),
            "search_queries": search_links,
        }
    finally:
        client.close()