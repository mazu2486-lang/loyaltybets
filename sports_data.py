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
WORLD_CUP_LEAGUE = 1       # FIFA World Cup 2026
WORLD_CUP_SEASON = 2026
CHAMPIONS_LEAGUE = 2       # UEFA Champions League
CHAMPIONS_SEASON = 2025
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

def get_forma_reciente_futbol(team_name: str) -> float:
    """Returns a form multiplier [0.85, 1.15] based on points earned in last 5 games."""
    team_id = _buscar_team_id_futbol(team_name)
    if not team_id:
        return 1.0

    cache_key = f"fb_forma_{team_name.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = _get("https://v3.football.api-sports.io", "fixtures", {"team": team_id, "last": 5})
    if not data or not data.get("response"):
        _cache_set(cache_key, 1.0)
        return 1.0

    puntos = 0
    partidos = 0
    for f in data["response"]:
        status = f.get("fixture", {}).get("status", {}).get("short", "")
        if status not in ("FT", "AET", "PEN"):
            continue
        teams = f.get("teams", {})
        goals = f.get("goals", {})
        gh = goals.get("home") or 0
        ga = goals.get("away") or 0
        es_local = teams.get("home", {}).get("id") == team_id
        if es_local:
            puntos += 3 if gh > ga else (1 if gh == ga else 0)
        else:
            puntos += 3 if ga > gh else (1 if gh == ga else 0)
        partidos += 1

    factor = 0.85 + (puntos / (partidos * 3)) * 0.30 if partidos > 0 else 1.0
    _cache_set(cache_key, factor)
    return factor


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


def get_h2h_futbol(home: str, away: str) -> Optional[Dict]:
    """
    Returns H2H win rates from last 5 meetings between the two teams.
    {"home_wr": float, "draw_r": float, "away_wr": float}
    """
    id_h = _buscar_team_id_futbol(home)
    id_a = _buscar_team_id_futbol(away)
    if not id_h or not id_a:
        return None

    cache_key = f"fb_h2h_{min(id_h,id_a)}_{max(id_h,id_a)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = _get("https://v3.football.api-sports.io", "fixtures/headtohead",
                {"h2h": f"{id_h}-{id_a}", "last": 6})
    if not data or not data.get("response"):
        _cache_set(cache_key, None)
        return None

    wins_h = wins_a = draws = total = 0
    for f in data["response"]:
        status = f.get("fixture", {}).get("status", {}).get("short", "")
        if status not in ("FT", "AET", "PEN"):
            continue
        teams = f.get("teams", {})
        goals = f.get("goals", {})
        gh = goals.get("home") or 0
        ga = goals.get("away") or 0
        fid_h = teams.get("home", {}).get("id")
        if gh > ga:
            if fid_h == id_h: wins_h += 1
            else: wins_a += 1
        elif ga > gh:
            if fid_h == id_h: wins_a += 1
            else: wins_h += 1
        else:
            draws += 1
        total += 1

    if total == 0:
        _cache_set(cache_key, None)
        return None

    result = {
        "home_wr": wins_h / total,
        "draw_r":  draws  / total,
        "away_wr": wins_a / total,
    }
    _cache_set(cache_key, result)
    return result


def get_stats_futbol(team_name: str, league_id: int = FOOTBALL_LEAGUE, season: int = FOOTBALL_SEASON) -> Optional[Dict]:
    """
    Returns {"goals_for": float, "goals_against": float} averaged per game
    for the given league/season. Defaults to Premier League.
    """
    cache_key = f"fb_stats_{team_name.lower()}_{league_id}_{season}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    team_id = _buscar_team_id_futbol(team_name)
    if not team_id:
        _cache_set(cache_key, None)
        return None

    data = _get(
        "https://v3.football.api-sports.io", "teams/statistics",
        {"league": league_id, "season": season, "team": team_id},
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

def _buscar_team_id_mlb(name: str) -> Optional[int]:
    cache_key = f"mlb_id_{name.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = _get("https://v1.baseball.api-sports.io", "teams", {"search": name[:25]})
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


def get_stats_mlb(team_name: str) -> Optional[Dict]:
    """Returns {rpg, rapg} (runs per game scored/allowed) for an MLB team."""
    cache_key = f"mlb_stats_{team_name.lower()}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    team_id = _buscar_team_id_mlb(team_name)
    if not team_id:
        _cache_set(cache_key, None)
        return None

    data = _get(
        "https://v1.baseball.api-sports.io", "teams/statistics",
        {"league": MLB_LEAGUE, "season": MLB_SEASON, "team": team_id},
    )
    if not data or not data.get("response"):
        _cache_set(cache_key, None)
        return None

    r = data["response"]
    runs_for = r.get("runs", {}).get("for", {})
    runs_against = r.get("runs", {}).get("against", {})
    rpg = runs_for.get("average")
    rapg = runs_against.get("average")

    if rpg is None or rapg is None:
        _cache_set(cache_key, None)
        return None

    result = {"rpg": float(rpg), "rapg": float(rapg)}
    _cache_set(cache_key, result)
    return result


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
