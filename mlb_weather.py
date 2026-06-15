"""
Real-time weather for MLB stadiums via Open-Meteo (free, no API key).
Wind direction relative to center field + temperature affect expected run totals.
"""
import math
import requests
from typing import Optional, Dict
from sports_data import _cache_get, _cache_set, similitud

# Stadium lat, lon, and compass bearing from home plate to center field
MLB_STADIUMS = {
    "colorado rockies":      {"lat": 39.7560, "lon": -104.9942, "bearing": 135},
    "boston red sox":        {"lat": 42.3467, "lon": -71.0972,  "bearing": 60},
    "chicago cubs":          {"lat": 41.9484, "lon": -87.6553,  "bearing": 210},
    "chicago white sox":     {"lat": 41.8300, "lon": -87.6340,  "bearing": 225},
    "new york yankees":      {"lat": 40.8296, "lon": -73.9262,  "bearing": 225},
    "new york mets":         {"lat": 40.7571, "lon": -73.8458,  "bearing": 135},
    "texas rangers":         {"lat": 32.7473, "lon": -97.0827,  "bearing": 225},
    "philadelphia phillies": {"lat": 39.9056, "lon": -75.1665,  "bearing": 135},
    "atlanta braves":        {"lat": 33.8908, "lon": -84.4678,  "bearing": 270},
    "detroit tigers":        {"lat": 42.3390, "lon": -83.0485,  "bearing": 225},
    "cleveland guardians":   {"lat": 41.4962, "lon": -81.6852,  "bearing": 225},
    "milwaukee brewers":     {"lat": 43.0281, "lon": -87.9713,  "bearing": 225},
    "baltimore orioles":     {"lat": 39.2838, "lon": -76.6219,  "bearing": 225},
    "washington nationals":  {"lat": 38.8730, "lon": -77.0074,  "bearing": 135},
    "pittsburgh pirates":    {"lat": 40.4469, "lon": -80.0057,  "bearing": 315},
    "cincinnati reds":       {"lat": 39.0979, "lon": -84.5082,  "bearing": 225},
    "st. louis cardinals":   {"lat": 38.6226, "lon": -90.1928,  "bearing": 225},
    "kansas city royals":    {"lat": 39.0517, "lon": -94.4803,  "bearing": 225},
    "san francisco giants":  {"lat": 37.7786, "lon": -122.3893, "bearing": 90},
    "los angeles dodgers":   {"lat": 34.0739, "lon": -118.2400, "bearing": 225},
    "los angeles angels":    {"lat": 33.8003, "lon": -117.8827, "bearing": 225},
    "san diego padres":      {"lat": 32.7076, "lon": -117.1570, "bearing": 270},
    "seattle mariners":      {"lat": 47.5914, "lon": -122.3325, "bearing": 225},
    "oakland athletics":     {"lat": 37.7516, "lon": -122.2005, "bearing": 225},
    # Retractable roof parks — weather neutral
    "houston astros":        {"lat": 29.7572, "lon": -95.3555,  "bearing": 0, "roof": True},
    "minnesota twins":       {"lat": 44.9817, "lon": -93.2778,  "bearing": 0, "roof": True},
    "arizona diamondbacks":  {"lat": 33.4453, "lon": -112.0667, "bearing": 0, "roof": True},
    "tampa bay rays":        {"lat": 27.7683, "lon": -82.6534,  "bearing": 0, "roof": True},
    "miami marlins":         {"lat": 25.7781, "lon": -80.2197,  "bearing": 0, "roof": True},
    "toronto blue jays":     {"lat": 43.6415, "lon": -79.3893,  "bearing": 0, "roof": True},
}


def _find_stadium(team_name: str) -> Optional[Dict]:
    name = team_name.lower().strip()
    best_score = 0.0
    best_val = None
    for k, v in MLB_STADIUMS.items():
        s = similitud(name, k)
        if s > best_score:
            best_score = s
            best_val = v
    return best_val if best_score >= 0.50 else None


def get_weather_factor(home_team: str, fecha: str = None) -> float:
    """
    Returns a run total multiplier [0.87, 1.13] based on wind and temperature.
    Retractable roof stadiums always return 1.0.
    """
    stadium = _find_stadium(home_team)
    if not stadium:
        return 1.0
    if stadium.get("roof"):
        return 1.0

    cache_key = f"wth_{stadium['lat']}_{stadium['lon']}_{fecha or 'today'}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": stadium["lat"],
                "longitude": stadium["lon"],
                "current": "wind_speed_10m,wind_direction_10m,temperature_2m",
                "wind_speed_unit": "mph",
                "temperature_unit": "fahrenheit",
            },
            timeout=8,
        )
        if resp.status_code != 200:
            _cache_set(cache_key, 1.0)
            return 1.0

        cur = resp.json().get("current", {})
        wind_mph = float(cur.get("wind_speed_10m") or 0)
        wind_dir = float(cur.get("wind_direction_10m") or 0)
        temp_f   = float(cur.get("temperature_2m") or 72)

    except Exception as e:
        print(f"[weather] {home_team}: {e}")
        _cache_set(cache_key, 1.0)
        return 1.0

    # Component of wind blowing toward center field (positive = out = hitter's park)
    bearing = stadium.get("bearing", 225)
    wind_toward_cf = math.cos(math.radians(wind_dir - bearing)) * wind_mph

    if wind_toward_cf > 10:
        wind_factor = 1.05 + min((wind_toward_cf - 10) * 0.004, 0.05)
    elif wind_toward_cf < -10:
        wind_factor = 0.95 - min((-wind_toward_cf - 10) * 0.004, 0.05)
    else:
        wind_factor = 1.0 + wind_toward_cf * 0.003

    if temp_f < 50:
        temp_factor = 0.93
    elif temp_f < 60:
        temp_factor = 0.96
    elif temp_f > 85:
        temp_factor = 1.04
    elif temp_f > 75:
        temp_factor = 1.02
    else:
        temp_factor = 1.0

    factor = round(max(0.87, min(1.13, wind_factor * temp_factor)), 4)
    print(f"[weather] {home_team}: wind={wind_mph:.1f}mph→CF={wind_toward_cf:.1f} temp={temp_f:.0f}°F → {factor}")
    _cache_set(cache_key, factor)
    return factor
