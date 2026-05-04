import json
import os
import anthropic
from pydantic import BaseModel
import db


class WinePick(BaseModel):
    id: str
    reason: str


class WineResponse(BaseModel):
    intro: str
    picks: list[WinePick]
    outro: str

_client: anthropic.Anthropic | None = None

SYSTEM_PROMPT = """You are a wine recommendation assistant. You have access to a wine database through the search_wines tool.

Rules:
- ALWAYS use the search_wines tool before recommending wines. Never recommend from memory.
- You may call search_wines multiple times with different parameters if needed.
- After searching, use the respond_to_user tool to deliver your final answer. Do NOT respond with plain text.
- The "id" in picks MUST be an id returned from search_wines results. Never invent an id.
- The "reason" should be a brief, natural explanation of why this wine fits the user's request.
- If the search returns no results, say so honestly. Do not make up wines.
- If the question is not about wine, respond with intro "I can only help with wine recommendations." and empty picks."""

MAX_TOOL_ROUNDS = 5


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def build_tools(filter_cache: dict) -> list[dict]:
    return [{
        "name": "respond_to_user",
        "description": "Return your final wine recommendation to the user. ALWAYS use this tool for your final response.",
        "input_schema": WineResponse.model_json_schema(),
    }, {
        "name": "search_wines",
        "description": "Search the wine database. Use this to find wines matching the user's criteria. You can combine multiple filters. If a search returns no results, try relaxing filters.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Wine name, partial match supported"
                },
                "producer": {
                    "type": "string",
                    "description": "Producer/winery name, partial match supported"
                },
                "color": {
                    "type": "string",
                    "enum": ["red", "white", "rosé", "sparkling", "dessert"]
                },
                "country": {
                    "type": "string",
                    "enum": filter_cache["countries"],
                    "description": "Country of origin"
                },
                "region": {
                    "type": "string",
                    "description": f"Wine region. Known regions: {', '.join(filter_cache['regions'][:50])}"
                },
                "appellation": {
                    "type": "string",
                    "description": f"Appellation. Known appellations: {', '.join(filter_cache['appellations'][:50])}"
                },
                "varietal": {
                    "type": "string",
                    "description": f"Grape variety. Known varietals: {', '.join(filter_cache['varietals'][:50])}"
                },
                "vintage": {
                    "type": "string",
                    "description": "Vintage year, e.g. '2019'"
                },
                "price_min": {
                    "type": "number",
                    "description": "Minimum price in USD"
                },
                "price_max": {
                    "type": "number",
                    "description": "Maximum price in USD"
                },
                "abv_min": {
                    "type": "number",
                    "description": "Minimum alcohol by volume"
                },
                "abv_max": {
                    "type": "number",
                    "description": "Maximum alcohol by volume"
                },
                "order_by": {
                    "type": "string",
                    "enum": ["score", "price_asc", "price_desc"],
                    "description": "Sort order. Default: score"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return. Default: 10"
                }
            },
            "required": []
        }
    }]


def _execute_tool(name: str, input: dict) -> str:
    if name != "search_wines":
        return json.dumps({"error": f"Unknown tool: {name}"})
    wines = db.query_wines(**input)
    results = []
    for w in wines:
        results.append({
            "id": w["id"],
            "name": w["name"],
            "producer": w.get("producer"),
            "country": w.get("country"),
            "region": w.get("region"),
            "appellation": w.get("appellation"),
            "varietal": w.get("varietal"),
            "vintage": w.get("vintage"),
            "color": w.get("color"),
            "abv": w.get("abv"),
            "price": w.get("price"),
            "top_score": w.get("top_score"),
        })
    return json.dumps(results, ensure_ascii=False)


def _assemble_speech(response: dict) -> tuple[str, list[dict]]:
    """Build user-facing text and wine list from Claude's structured response.
    All facts come from the database; Claude only contributes intro/outro/reasons."""
    parts = []
    wine_details = []

    if response.get("intro"):
        parts.append(response["intro"])

    for pick in response.get("picks", []):
        wine = db.get_wine_by_id(str(pick["id"]))
        if not wine:
            continue

        detail = f"{wine['name']}"
        if wine.get("producer"):
            detail += f" by {wine['producer']}"
        if wine.get("vintage"):
            detail += f", {wine['vintage']} vintage"
        origin = wine.get("appellation") or wine.get("region")
        if origin:
            detail += f", from {origin}"
            if wine.get("country"):
                detail += f", {wine['country']}"
        elif wine.get("country"):
            detail += f", from {wine['country']}"
        if wine.get("color") and wine.get("varietal"):
            detail += f". It's a {wine['color']} wine, {wine['varietal']}"
        if wine.get("price") is not None:
            detail += f", ${wine['price']:.0f}"
        if wine.get("top_score"):
            detail += f", rated {wine['top_score']} points"
        detail += f". {pick.get('reason', '')}"
        parts.append(detail)

        wine_details.append({
            "id": wine["id"],
            "name": wine["name"],
            "producer": wine.get("producer"),
            "country": wine.get("country"),
            "region": wine.get("region"),
            "appellation": wine.get("appellation"),
            "varietal": wine.get("varietal"),
            "vintage": wine.get("vintage"),
            "color": wine.get("color"),
            "abv": wine.get("abv"),
            "price": wine.get("price"),
            "top_score": wine.get("top_score"),
            "image_url": wine.get("image_url"),
            "reference_url": wine.get("reference_url"),
            "reason": pick.get("reason", ""),
        })

    if response.get("outro"):
        parts.append(response["outro"])

    return " ".join(parts), wine_details


def ask_claude(question: str) -> tuple[str, list[dict]]:
    """Send question to Claude with tool use, return (speech_text, wine_details)."""
    client = _get_client()
    filter_cache = db.get_filter_cache()
    tools = build_tools(filter_cache)

    messages = [{"role": "user", "content": question}]

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                if block.name == "respond_to_user":
                    structured = WineResponse.model_validate(block.input)
                    return _assemble_speech(structured.model_dump())
                result = _execute_tool(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        if tool_results:
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
            continue

        text = "".join(block.text for block in response.content if hasattr(block, "text"))
        return text or "I couldn't process your request.", []

    return "I'm sorry, I had trouble finding wines for your request. Please try again.", []
