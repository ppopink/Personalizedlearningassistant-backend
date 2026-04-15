import json
from typing import Any, List


def ensure_list(value: Any):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        normalized = value.replace("，", ",").replace("、", ",")
        return [item.strip() for item in normalized.split(",") if item.strip()]
    return []


def parse_json_response(content: str):
    text = (content or "").strip()
    if text.startswith("```json"):
        text = text.replace("```json", "").replace("```", "").strip()
    elif text.startswith("```"):
        text = text.replace("```", "").strip()
    return json.loads(text)


def merge_unique_items(existing: List[str], new_items: List[str], limit: int = 12):
    merged = []
    seen = set()

    for item in list(existing) + list(new_items):
        normalized = str(item).strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            merged.append(normalized)
        if len(merged) >= limit:
            break

    return merged
