import json
import os
import anthropic

_client: anthropic.Anthropic | None = None

SYSTEM_PROMPT = """You are a friendly, knowledgeable wine sommelier. You answer questions
based ONLY on the wine catalog provided. Keep answers conversational and concise
(3-4 sentences max, unless the user asks for a list). If listing wines, limit to
5 unless asked for more. Always mention the wine name, price, and rating when
recommending. If the question cannot be answered from the catalog, say so politely.
If the question is ambiguous, make a reasonable interpretation and state your
assumption. Never invent or fabricate any data — not wines, prices, ratings, regions, or any other details. Every fact in your answer must come directly from the provided catalog."""


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def ask_claude(question: str, wines: list[dict]) -> str:
    """Send question + wine context to Claude and return the answer text."""
    # Trim ratings to keep context concise but informative
    catalog = []
    for w in wines:
        entry = {
            "id": w.get("id"),
            "name": w.get("name"),
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
            "ratings": w.get("ratings"),
        }
        catalog.append(entry)

    user_message = (
        f"Wine catalog (JSON):\n{json.dumps(catalog, ensure_ascii=False)}\n\n"
        f'User question: "{question}"'
    )

    client = _get_client()
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    return message.content[0].text
