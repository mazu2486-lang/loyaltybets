"""
Fetches team statistics from API-Sports with a 23-hour file cache.
Used by predictor.py to build independent probability estimates.
"""
import os
import json
import time
import requests
from typing import Dict, List, Optional
from difflib import SequenceMatcher

API_SPORTS_KEY = os.getenv("API_SPORTS_KEY", "")
CACHE_PATH = os.getenv("STATS_CACHE_PATH", "/tmp/stats_cache.json")
CACHE_TTL = 82800  # 23 hours

# API-Sports league/season config
FOOTBALL_LEAGUE = 39       # Premier League
FOOTBALL_SEASON = 2025
BASKETBALL_LEAGUE = 12     # NBA
BASKETBALL_SEASON = "2025-2026"
MLB_LEAGUE = 1
MLB_SEASON = 2026

TEAM_ALIASES = {
    "man city": "manchester city",
    "man utd": "manchester united",
    "man united": "manchester united",
    "wolves": "wolverhampton wanderers",
    "spurs": "tottenham hotspur",
    "newcastle": "newcastle united",
    "la rams": "los angeles rams",
    "la lakers": "los angeles lakers",
    "la clippers": "los angeles clippers",
}


def similitud(a: str, b: str) -> float:
    def norm(s):
        s = s.lower().strip()
        return TEAM_ALIASES.get(s, s)
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


# ── Cache ────────────────────────────────────────────────────────────────────

def _cache_load() -> Dict:
    try:
        if os.path.exists(CACHE_PATH):
            return json.load(open(CACHE_PATH))
    except Exception:
        pass
    return {}


def _cache_save(cache: Dict):
    try:
        json.dump(cache, open(CACHE_PATH, "w"))
    except Exception:
        pass


def _cache_get(key: str):
    cache = _cache_load()
    entry = cache.get(key)
    if entry and time.time() - entry.get("ts", 0) < CACHE_TTL:
        return entry["data"]
    return None


def _cache_set(key: str, data):
    cache = _cache_load()
    cache[key] = {"data": data, "ts": time.time()}
    _cache_save(cache)


# ── HTTP helper ───────────────────────────────────────────────────────────────

def _get(base_url: str, endpoint: str, params: Dict) -> Optional[Dict]:
    if not API_SPORTS_KEY:
        return None
    try:
        resp = requests.get(
            f"{base_url}/{endpoint}",
            headers={"x-apisports-key": API_SPORTS_KEY},
            params=params,
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        print(f"[sports_data] {endpoint} → HTTP {resp.status_code}")
    except Exception as e:
        print(f"[sports_data] {endpoint} error: {e}")
    return None


# ── Football ─────────────────────────────────────────────────────────────────

def _buscar_team_id_futbol(name: str) -> Optional[int]:
    cache_key = f"fb_id_{name.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = _get("https://v3.football.api-sports.io", "teams", {"search": name[:25]})
    if not data or not data.get("response"):
        _cache_set(cache_key, None)
        return None

    teams = data["response"]
    best = max(teams, key=lambda t: similitud(name, t["team"]["name"]), default=None)
    if not best or similitud(name, best["team"]["name"]) < 0.5:
        _cache_set(cache_key, None)
        return None

    tid = best["team"]["id"]
    _cache_set(cache_key, tid)
    return tid


def get_stats_futbol(team_name: str) -> Optional[Dict]:
    """
    Returns {"goals_for": float, "goals_against": float} averaged per game
    for the current Premier League season.
    """
    cache_key = f"fb_stats_{team_name.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    team_id = _buscar_team_id_futbol(team_name)
    if not team_id:
        _cache_set(cache_key, None)
        return None

    data = _get(
        "https://v3.football.api-sports.io", "teams/statistics",
        {"league": FOOTBALL_LEAGUE, "season": FOOTBALL_SEASON, "team": team_id},
    )
    if not data or not data.get("response"):
        _cache_set(cache_key, None)
        return None

    r = data["response"]
    gf = r.get("goals", {}).get("for", {}).get("average", {}).get("total")
    ga = r.get("goals", {}).get("against", {}).get("average", {}).get("total")
    if gf is None or ga is None:
        _cache_set(cache_key, None)
        return None

    result = {"goals_for": float(gf), "goals_against": float(ga)}
    _cache_set(cache_key, result)
    return result


# ── Basketball (NBA) ──────────────────────────────────────────────────────────

def get_standings_basquet() -> Optional[List[Dict]]:
    """Returns list of {name, win_pct, ppg, papg} for NBA teams."""
    cache_key = "basquet_standings"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = _get(
        "https://v1.basketball.api-sports.io", "standings",
        {"league": BASKETBALL_LEAGUE, "season": BASKETBALL_SEASON},
    )
    if not data or not data.get("response"):
        _cache_set(cache_key, None)
        return None

    result = []
    for group in data["response"]:
        entries = group if isinstance(group, list) else [group]
        for entry in entries:
            name = entry.get("team", {}).get("name", "")
            games = entry.get("games", {})
            wins = games.get("wins", {}).get("total", 0) or 0
            losses = games.get("losses", {}).get("total", 0) or 0
            total = wins + losses
            wp = wins / total if total > 0 else 0.5
            pts = entry.get("points", {})
            ppg = float(pts.get("for", {}).get("average", {}).get("total") or 110)
            papg = float(pts.get("against", {}).get("average", {}).get("total") or 110)
            result.append({"name": name, "win_pct": wp, "ppg": ppg, "papg": papg})

    _cache_set(cache_key, result)
    return result or None


# ── MLB ───────────────────────────────────────────────────────────────────────

def get_standings_mlb() -> Optional[List[Dict]]:
    """Returns list of {name, win_pct} for MLB teams."""
    cache_key = "mlb_standings"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = _get(
        "https://v1.baseball.api-sports.io", "standings",
        {"league": MLB_LEAGUE, "season": MLB_SEASON},
    )
    if not data or not data.get("response"):
        _cache_set(cache_key, None)
        return None

    result = []
    for entry in data["response"]:
        name = entry.get("team", {}).get("name", "")
        games = entry.get("games", {})
        wins = games.get("wins", {}).get("total", 0) or 0
        losses = games.get("losses", {}).get("total", 0) or 0
        total = wins + losses
        wp = wins / total if total > 0 else 0.5
        result.append({"name": name, "win_pct": wp})

    _cache_set(cache_key, result)
    return result or None
