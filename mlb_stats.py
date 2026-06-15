"""
MLB Stats API (statsapi.mlb.com) — free, official, no API key required.
Provides probable pitchers and recent team form for the current season.
"""
import requests
from datetime import date as date_cls, timedelta
from typing import Optional, Dict
from sports_data import _cache_get, _cache_set, similitud

MLB_STATS_BASE = "https://statsapi.mlb.com/api/v1"
LEAGUE_ERA = 4.20   # MLB league-average ERA ~2025-26
MIN_IP = 15.0       # minimum innings pitched to trust ERA


def _get(endpoint: str, params: dict = None) -> Optional[Dict]:
    try:
        resp = requests.get(f"{MLB_STATS_BASE}/{endpoint}", params=params or {}, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        print(f"[mlb_stats] {endpoint} → HTTP {resp.status_code}")
    except Exception as e:
        print(f"[mlb_stats] {endpoint} error: {e}")
    return None


def _buscar_team_id(name: str) -> Optional[int]:
    cache_key = f"mlbs_tid_{name.lower()[:20]}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = _get("teams", {"sportId": 1})
    if not data:
        _cache_set(cache_key, None)
        return None

    teams = data.get("teams", [])
    best = max(teams, key=lambda t: similitud(name, t.get("name", "")), default=None)
    if not best or similitud(name, best.get("name", "")) < 0.45:
        _cache_set(cache_key, None)
        return None

    tid = best["id"]
    _cache_set(cache_key, tid)
    return tid


def _pitcher_stats(player_id: int) -> Optional[Dict]:
    cache_key = f"mlbs_p_{player_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = _get(f"people/{player_id}/stats", {
        "stats": "season", "group": "pitching", "season": 2026,
    })
    if not data:
        _cache_set(cache_key, None)
        return None

    for sg in data.get("stats", []):
        splits = sg.get("splits", [])
        if not splits:
            continue
        stat = splits[0].get("stat", {})
        try:
            ip = float(stat.get("inningsPitched") or 0)
            era = float(stat.get("era") or LEAGUE_ERA)
            whip = float(stat.get("whip") or 1.30)
        except (TypeError, ValueError):
            continue
        if ip < MIN_IP:
            _cache_set(cache_key, None)
            return None
        result = {"era": era, "whip": whip, "ip": ip}
        _cache_set(cache_key, result)
        return result

    _cache_set(cache_key, None)
    return None


def get_probable_pitchers(home: str, away: str, fecha: str = None) -> Optional[Dict]:
    """Returns {home_era, home_whip, away_era, away_whip} or None."""
    if fecha is None:
        fecha = date_cls.today().isoformat()

    cache_key = f"mlbs_pp_{home.lower()[:10]}_{away.lower()[:10]}_{fecha}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = _get("schedule", {
        "sportId": 1, "date": fecha,
        "hydrate": "probablePitcher,team",
    })
    if not data:
        _cache_set(cache_key, None)
        return None

    for de in data.get("dates", []):
        for game in de.get("games", []):
            t = game.get("teams", {})
            h_name = t.get("home", {}).get("team", {}).get("name", "")
            a_name = t.get("away", {}).get("team", {}).get("name", "")
            if similitud(h_name, home) < 0.45 or similitud(a_name, away) < 0.45:
                continue

            result = {}
            for side, key in [("home", "home"), ("away", "away")]:
                pitcher = t.get(side, {}).get("probablePitcher", {})
                pid = pitcher.get("id")
                if pid:
                    stats = _pitcher_stats(pid)
                    if stats:
                        result[f"{key}_era"] = stats["era"]
                        result[f"{key}_whip"] = stats["whip"]

            out = result or None
            _cache_set(cache_key, out)
            return out

    _cache_set(cache_key, None)
    return None


def get_forma_reciente_mlb(team_name: str, fecha: str = None) -> float:
    """Returns form multiplier [0.88, 1.12] from last 10 completed games."""
    if fecha is None:
        fecha = date_cls.today().isoformat()

    cache_key = f"mlbs_forma_{team_name.lower()[:18]}_{fecha}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    team_id = _buscar_team_id(team_name)
    if not team_id:
        _cache_set(cache_key, 1.0)
        return 1.0

    try:
        hoy = date_cls.fromisoformat(fecha)
    except Exception:
        hoy = date_cls.today()
    start = (hoy - timedelta(days=25)).isoformat()

    data = _get("schedule", {
        "sportId": 1, "teamId": team_id,
        "startDate": start, "endDate": fecha,
        "gameType": "R",
    })
    if not data:
        _cache_set(cache_key, 1.0)
        return 1.0

    wins = losses = 0
    for de in data.get("dates", []):
        for game in de.get("games", []):
            if game.get("status", {}).get("abstractGameState") != "Final":
                continue
            teams = game.get("teams", {})
            for side in ("home", "away"):
                t = teams.get(side, {})
                if t.get("team", {}).get("id") == team_id:
                    if t.get("isWinner"):
                        wins += 1
                    else:
                        losses += 1
            if wins + losses >= 10:
                break
        if wins + losses >= 10:
            break

    total = wins + losses
    factor = (0.88 + (wins / total) * 0.24) if total > 0 else 1.0
    _cache_set(cache_key, factor)
    return factor


# Umpire historical Over% tendency (public data, ~51% is neutral)
# Each 1pp above 51% adds ~1.5% to expected run total
_UMPIRE_OVER_PCT: Dict[str, float] = {
    "Dan Iassogna": 0.56, "Lance Barrett": 0.56, "Nick Mahrley": 0.55,
    "Paul Emmel": 0.54, "Jeremie Rehak": 0.54, "Angel Hernandez": 0.54,
    "Chris Conroy": 0.54, "Mark Wegner": 0.53, "Laz Diaz": 0.53,
    "Roberto Ortiz": 0.53, "Brennan Miller": 0.53, "Tim Timmons": 0.52,
    "Vic Carapazza": 0.52, "Mike Muchlinski": 0.52, "James Hoye": 0.52,
    "Todd Tichenor": 0.52, "John Tumpane": 0.51, "Phil Cuzzi": 0.50,
    "Joe West": 0.50, "Gary Cederstrom": 0.50, "Sam Holbrook": 0.50,
    "Ted Barrett": 0.51, "Brian Gorman": 0.51, "Mike Everitt": 0.49,
    "Mike Winters": 0.49, "Doug Eddings": 0.49, "Ron Kulpa": 0.49,
    "Alan Porter": 0.48, "Bill Miller": 0.48, "CB Bucknor": 0.48,
}


def get_umpire_factor(home: str, away: str, fecha: str = None) -> float:
    """Returns a run total multiplier [0.92, 1.08] based on home plate umpire O/U tendency."""
    if fecha is None:
        fecha = date_cls.today().isoformat()

    cache_key = f"mlbs_ump_{home.lower()[:10]}_{away.lower()[:10]}_{fecha}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    data = _get("schedule", {"sportId": 1, "date": fecha, "hydrate": "officials,team"})
    if not data:
        _cache_set(cache_key, 1.0)
        return 1.0

    for de in data.get("dates", []):
        for game in de.get("games", []):
            t = game.get("teams", {})
            h_name = t.get("home", {}).get("team", {}).get("name", "")
            a_name = t.get("away", {}).get("team", {}).get("name", "")
            if similitud(h_name, home) < 0.45 or similitud(a_name, away) < 0.45:
                continue

            for official in game.get("officials", []):
                if official.get("officialType") == "Home Plate":
                    name = official.get("official", {}).get("fullName", "")
                    over_pct = _UMPIRE_OVER_PCT.get(name)
                    if over_pct is not None:
                        factor = round(max(0.92, min(1.08, 1.0 + (over_pct - 0.51) * 1.5)), 4)
                        print(f"[umpire] {name}: {over_pct:.0%} Over → factor={factor}")
                        _cache_set(cache_key, factor)
                        return factor
                    print(f"[umpire] {name}: sin datos históricos")

    _cache_set(cache_key, 1.0)
    return 1.0
