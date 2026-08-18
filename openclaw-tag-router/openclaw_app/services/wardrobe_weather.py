from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any


GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_TIMEOUT_SECONDS = 8.0

BUILTIN_LOCATION_COORDINATES: dict[str, dict[str, Any]] = {
    "深圳": {"name": "深圳", "latitude": 22.54554, "longitude": 114.0683, "timezone": "Asia/Shanghai"},
    "深圳市": {"name": "深圳", "latitude": 22.54554, "longitude": 114.0683, "timezone": "Asia/Shanghai"},
}

WEATHER_CODE_LABELS: dict[int, str] = {
    0: "晴",
    1: "多云间晴",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "大毛毛雨",
    56: "冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "阵雨",
    81: "强阵雨",
    82: "暴阵雨",
    85: "阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴强冰雹",
}


class WardrobeWeatherError(RuntimeError):
    pass


def fetch_wardrobe_weather(location_name: str) -> dict[str, Any]:
    location = _resolve_location(location_name)
    params = {
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "current": ",".join(
            [
                "temperature_2m",
                "apparent_temperature",
                "precipitation",
                "rain",
                "weather_code",
                "relative_humidity_2m",
                "wind_speed_10m",
            ]
        ),
        "timezone": "auto",
        "forecast_days": "1",
    }
    payload = _get_json(f"{FORECAST_URL}?{urllib.parse.urlencode(params)}")
    current = payload.get("current")
    if not isinstance(current, dict):
        raise WardrobeWeatherError("Open-Meteo forecast response missing current weather")
    temperature = current.get("temperature_2m")
    weather_code = _as_int(current.get("weather_code"))
    summary = WEATHER_CODE_LABELS.get(weather_code, "天气未分类")
    precipitation = _as_float(current.get("precipitation"))
    rain = _as_float(current.get("rain"))
    if (precipitation or rain) and "雨" not in summary:
        summary = f"{summary}，有降水"
    return {
        "summary": summary,
        "temperature": _format_temperature(temperature),
        "apparent_temperature": _format_temperature(current.get("apparent_temperature")),
        "humidity": _format_percent(current.get("relative_humidity_2m")),
        "wind_speed": _format_speed(current.get("wind_speed_10m")),
        "precipitation": precipitation,
        "rain": rain,
        "weather_code": weather_code,
        "time": str(current.get("time") or ""),
        "source": "open-meteo",
        "source_url": FORECAST_URL,
        "location": location["name"],
        "resolved_location": location,
    }


def _resolve_location(location_name: str) -> dict[str, Any]:
    query = _normalize_location_query(location_name)
    if not query or query == "未定位":
        raise WardrobeWeatherError("missing weather location")
    if query == "行李中":
        raise WardrobeWeatherError("location 行李中 requires a destination/weather location")

    configured = _configured_coordinates()
    if query in configured:
        return dict(configured[query])
    if query in BUILTIN_LOCATION_COORDINATES:
        return dict(BUILTIN_LOCATION_COORDINATES[query])

    params = {"name": query, "count": "5", "language": "zh", "format": "json"}
    payload = _get_json(f"{GEOCODING_URL}?{urllib.parse.urlencode(params)}")
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        raise WardrobeWeatherError(f"cannot geocode weather location: {query}")
    result = _prefer_geocoding_result(results)
    return {
        "name": str(result.get("name") or query),
        "latitude": float(result["latitude"]),
        "longitude": float(result["longitude"]),
        "timezone": str(result.get("timezone") or "auto"),
        "country": str(result.get("country") or ""),
        "admin1": str(result.get("admin1") or ""),
        "admin2": str(result.get("admin2") or ""),
    }


def _normalize_location_query(location_name: str) -> str:
    query = str(location_name or "").strip()
    if query == "老家":
        query = os.getenv("WARDROBE_HOME_LOCATION", "").strip() or query
    aliases = _configured_aliases()
    return aliases.get(query, query)


def _prefer_geocoding_result(results: list[Any]) -> dict[str, Any]:
    for item in results:
        if isinstance(item, dict) and item.get("country_code") == "CN" and item.get("latitude") is not None and item.get("longitude") is not None:
            return item
    for item in results:
        if isinstance(item, dict) and item.get("latitude") is not None and item.get("longitude") is not None:
            return item
    raise WardrobeWeatherError("geocoding response has no usable coordinates")


def _configured_aliases() -> dict[str, str]:
    raw = os.getenv("WARDROBE_LOCATION_ALIASES_JSON", "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key).strip(): str(value).strip() for key, value in payload.items() if str(key).strip() and str(value).strip()}


def _configured_coordinates() -> dict[str, dict[str, Any]]:
    raw = os.getenv("WARDROBE_LOCATION_COORDINATES_JSON", "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        name = str(key or "").strip()
        if not name:
            continue
        if isinstance(value, dict) and value.get("latitude") is not None and value.get("longitude") is not None:
            result[name] = {
                "name": str(value.get("name") or name),
                "latitude": float(value["latitude"]),
                "longitude": float(value["longitude"]),
                "timezone": str(value.get("timezone") or "Asia/Shanghai"),
            }
        elif isinstance(value, list) and len(value) >= 2:
            result[name] = {"name": name, "latitude": float(value[0]), "longitude": float(value[1]), "timezone": "Asia/Shanghai"}
    return result


def _get_json(url: str) -> dict[str, Any]:
    timeout = _timeout_seconds()
    request = urllib.request.Request(url, headers={"User-Agent": "OpenClaw-WardrobeOS/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except Exception as exc:
        raise WardrobeWeatherError(f"weather provider request failed: {exc}") from exc
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise WardrobeWeatherError("weather provider returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise WardrobeWeatherError("weather provider returned non-object JSON")
    return payload


def _timeout_seconds() -> float:
    raw = os.getenv("WARDROBE_WEATHER_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return max(1.0, min(float(raw), 30.0))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _format_temperature(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{number:g}°C"


def _format_percent(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{number:g}%"


def _format_speed(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{number:g}km/h"
