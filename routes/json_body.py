"""Разбор JSON-тела запроса — один на все маршруты."""
import json

from flask import request


def json_body() -> dict:
    """JSON body of a request — including the beacon form.

    `navigator.sendBeacon` (used when the tab closes, so the reviewed marks
    are not lost) may arrive as text/plain; Flask then leaves get_json()
    empty, and the request would silently fall back to the default view.
    Anything that is not a JSON object is treated as an empty body.
    """
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    raw = request.get_data(as_text=True) or ""
    if raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}
