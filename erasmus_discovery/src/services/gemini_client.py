import json
import os
import re
import time
from json import JSONDecodeError
from typing import Any, Dict, List

import requests

from ..utils import clean_model_text


GEMINI_ENDPOINT_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
EXHAUSTED_GEMINI_KEYS: set[str] = set()


def has_gemini_key() -> bool:
    return bool(get_available_gemini_keys())


def get_gemini_keys() -> List[str]:
    keys: List[str] = []
    combined = os.getenv("GEMINI_API_KEYS", "").strip()
    if combined:
        keys.extend(part.strip() for part in re.split(r"[,;\n]+", combined) if part.strip())

    single = os.getenv("GEMINI_API_KEY", "").strip()
    if single:
        keys.append(single)

    for index in range(1, 10):
        value = os.getenv(f"GEMINI_API_KEY_{index}", "").strip()
        if value:
            keys.append(value)

    deduped: List[str] = []
    seen = set()
    for key in keys:
        if key not in seen:
            deduped.append(key)
            seen.add(key)
    return deduped


def get_available_gemini_keys() -> List[str]:
    return [key for key in get_gemini_keys() if key not in EXHAUSTED_GEMINI_KEYS]


def url_classification_schema() -> Dict[str, Any]:
    categories = [
        "agreements",
        "partner_universities",
        "outgoing_studies",
        "deadlines",
        "application_requirements",
        "learning_agreement",
        "traineeship",
        "general_erasmus_information",
        "irrelevant",
    ]
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "url": {"type": "string"},
                        "selected": {"type": "boolean"},
                        "category": {"type": "string", "enum": categories},
                        "relevance_score": {"type": "integer", "minimum": 0, "maximum": 100},
                        "reason": {"type": "string"},
                        "expected_data": {"type": "array", "items": {"type": "string"}},
                        "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    },
                    "required": [
                        "url",
                        "selected",
                        "category",
                        "relevance_score",
                        "reason",
                        "expected_data",
                        "priority",
                    ],
                },
            }
        },
        "required": ["classifications"],
    }


def call_gemini_json(
    prompt: str,
    schema: Dict[str, Any],
    model: str | None = None,
    timeout_seconds: int = 120,
    max_attempts: int = 8,
    retry_base_delay: float = 30.0,
    system_prompt: str = "Follow the user's instructions exactly and never invent facts.",
) -> Dict[str, Any]:
    api_keys = get_available_gemini_keys()
    if not api_keys:
        configured = len(get_gemini_keys())
        message = "All configured Gemini API keys are exhausted for this run." if configured else "GEMINI_API_KEY is not set"
        return {"error": "Gemini request failed", "message": message}

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"{system_prompt}\nReturn strict JSON only.\n\n{prompt}"}],
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseJsonSchema": schema,
        },
    }
    endpoint = GEMINI_ENDPOINT_TEMPLATE.format(model=model or DEFAULT_GEMINI_MODEL)
    return _post_and_parse_json(endpoint, payload, api_keys, timeout_seconds, max_attempts, retry_base_delay)


def _post_and_parse_json(
    endpoint: str,
    payload: Dict[str, Any],
    api_keys: List[str],
    timeout_seconds: int,
    max_attempts: int,
    retry_base_delay: float,
) -> Dict[str, Any]:
    last_error = ""
    last_status = 0
    retryable_statuses = {429, 500, 502, 503, 504}
    max_attempts = max(1, max_attempts)

    exhausted_keys = 0
    for key_index, api_key in enumerate(api_keys):
        headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
        for attempt in range(max_attempts):
            try:
                response = requests.post(endpoint, json=payload, headers=headers, timeout=timeout_seconds)
                if response.status_code == 429 and key_index < len(api_keys) - 1:
                    last_status = response.status_code
                    last_error = _response_error_message(response, endpoint)
                    EXHAUSTED_GEMINI_KEYS.add(api_key)
                    exhausted_keys += 1
                    break
                if response.status_code in retryable_statuses and attempt < max_attempts - 1:
                    last_status = response.status_code
                    last_error = _response_error_message(response, endpoint)
                    time.sleep(_retry_delay_seconds(response, attempt, retry_base_delay))
                    continue
                response.raise_for_status()
                return _parse_json(_gemini_output_text(response.json()))
            except requests.HTTPError as exc:
                response = exc.response
                last_status = response.status_code if response is not None else 0
                last_error = _response_error_message(response, endpoint) if response is not None else str(exc)
                if last_status == 429 and key_index < len(api_keys) - 1:
                    EXHAUSTED_GEMINI_KEYS.add(api_key)
                    exhausted_keys += 1
                    break
                if last_status in retryable_statuses and attempt < max_attempts - 1:
                    time.sleep(_retry_delay_seconds(response, attempt, retry_base_delay))
                    continue
                return {
                    "error": "Gemini request failed",
                    "message": last_error,
                    "status_code": last_status,
                    "retryable": last_status in retryable_statuses,
                    "exhausted_keys": exhausted_keys,
                    "configured_keys": len(api_keys),
                }
            except (requests.RequestException, ValueError, JSONDecodeError) as exc:
                last_error = str(exc)
                if attempt < max_attempts - 1:
                    time.sleep(_retry_delay_seconds(None, attempt, retry_base_delay))
                    continue
        continue
    return {
        "error": "Gemini request failed",
        "message": last_error,
        "status_code": last_status,
        "retryable": True,
        "exhausted_keys": exhausted_keys,
        "configured_keys": len(api_keys),
    }


def _retry_delay_seconds(response: requests.Response | None, attempt: int, retry_base_delay: float) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After", "").strip()
        if retry_after.isdigit():
            return min(float(retry_after) + 5.0, 300.0)
        retry_delay = _retry_delay_from_body(response)
        if retry_delay:
            return min(retry_delay + 5.0, 300.0)
    return min(retry_base_delay * (2**attempt), 300.0)


def _retry_delay_from_body(response: requests.Response) -> float:
    try:
        data = response.json()
    except ValueError:
        data = {}

    if isinstance(data, dict):
        error = data.get("error", {}) if isinstance(data.get("error"), dict) else {}
        for detail in error.get("details", []) or []:
            if not isinstance(detail, dict):
                continue
            retry_delay = detail.get("retryDelay")
            parsed = _parse_duration_seconds(retry_delay)
            if parsed:
                return parsed
        message = str(error.get("message") or "")
    else:
        message = ""

    if not message:
        message = response.text[:1000]
    match = re.search(r"retry in\s+([0-9]+(?:\.[0-9]+)?)s", message, flags=re.IGNORECASE)
    return float(match.group(1)) if match else 0.0


def _parse_duration_seconds(value: Any) -> float:
    if not isinstance(value, str):
        return 0.0
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)s", value.strip())
    return float(match.group(1)) if match else 0.0


def _response_error_message(response: requests.Response, endpoint: str) -> str:
    message = ""
    try:
        data = response.json()
        error = data.get("error", {}) if isinstance(data, dict) else {}
        message = str(error.get("message") or "")
    except ValueError:
        message = response.text[:500]
    suffix = f": {message}" if message else ""
    return f"{response.status_code} Client Error: {response.reason} for url: {endpoint}{suffix}"


def _gemini_output_text(data: Dict[str, Any]) -> str:
    parts: List[str] = []
    for candidate in data.get("candidates", []) or []:
        content = candidate.get("content", {}) or {}
        for part in content.get("parts", []) or []:
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts).strip()


def _parse_json(text: str) -> Dict[str, Any]:
    parsed = json.loads(_extract_json_text(text))
    if not isinstance(parsed, dict):
        raise JSONDecodeError("JSON response is not an object", text, 0)
    return parsed


def _extract_json_text(text: str) -> str:
    text = clean_model_text(text)
    if "```" in text:
        for part in text.split("```"):
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{") and candidate.endswith("}"):
                return candidate

    start = text.find("{")
    if start == -1:
        raise JSONDecodeError("No JSON object found", text, 0)

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    raise JSONDecodeError("Unbalanced JSON object", text, start)
