"""
Statistical probability models — independent from market odds.

Football : Dixon-Coles simplified Poisson model using season averages.
Basketball: Win-% adjusted Elo formula with home advantage.
MLB       : Win-% ratio with home advantage.
Tennis    : No model yet — falls back to market probabilities.

Returns None on failure so pick_engine can fall back gracefully.
"""
import math
from typing import Dict, Optional, List
from sports_data import (
    get_stats_futbol, get_standings_basquet, get_standings_mlb, similitud,
)

LEAGUE_AVG_GOALS = 2.65      # Premier League goals/game (both teams combined)
HOME_FACTOR_FUTBOL = 1.12    # home teams score ~12% more on average
HOME_EDGE_BASQUET = 0.03     # NBA home teams win ~53% → add 3pp to home wp
HOME_EDGE_MLB = 0.025        # MLB home teams win ~54%
MIN_MATCH_SCORE = 0.50       # minimum name-similarity to accept a team match


# ── Helpers ───────────────────────────────────────────────────────────────────

def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def _probs_poisson(lam_h: float, lam_a: float) -> tuple:
    p_home = p_draw = p_away = 0.0
    for i in range(8):
        for j in range(8):
            p = _poisson_pmf(i, lam_h) * _poisson_pmf(j, lam_a)
            if i > j:
                p_home += p
            elif i == j:
                p_draw += p
            else:
                p_away += p
    return p_home, p_draw, p_away


def _buscar_en_standings(name: str, standings: List[Dict]) -> Optional[Dict]:
    best = max(standings, key=lambda s: similitud(name, s["name"]), default=None)
    if best and similitud(name, best["name"]) >= MIN_MATCH_SCORE:
        return best
    return None


# ── Models ────────────────────────────────────────────────────────────────────

def predecir_futbol(home: str, away: str) -> Optional[Dict]:
    stats_h = get_stats_futbol(home)
    stats_a = get_stats_futbol(away)
    if not stats_h or not stats_a:
        return None

    league_avg = LEAGUE_AVG_GOALS / 2  # per team per game

    atk_h = stats_h["goals_for"] / league_avg
    def_h = stats_h["goals_against"] / league_avg
    atk_a = stats_a["goals_for"] / league_avg
    def_a = stats_a["goals_against"] / league_avg

    lam_h = atk_h * def_a * league_avg * HOME_FACTOR_FUTBOL
    lam_a = atk_a * def_h * league_avg

    p_home, p_draw, p_away = _probs_poisson(lam_h, lam_a)
    total = p_home + p_draw + p_away
    if total <= 0:
        return None

    return {
        "home":  round(p_home / total, 4),
        "draw":  round(p_draw / total, 4),
        "away":  round(p_away / total, 4),
    }


def predecir_basquet(home: str, away: str) -> Optional[Dict]:
    standings = get_standings_basquet()
    if not standings:
        return None

    th = _buscar_en_standings(home, standings)
    ta = _buscar_en_standings(away, standings)
    if not th or not ta:
        return None

    wp_h = min(th["win_pct"] + HOME_EDGE_BASQUET, 0.99)
    wp_a = ta["win_pct"]
    total = wp_h + wp_a
    if total <= 0:
        return None

    return {
        "home": round(wp_h / total, 4),
        "away": round(wp_a / total, 4),
    }


def predecir_mlb(home: str, away: str) -> Optional[Dict]:
    standings = get_standings_mlb()
    if not standings:
        return None

    th = _buscar_en_standings(home, standings)
    ta = _buscar_en_standings(away, standings)
    if not th or not ta:
        return None

    wp_h = min(th["win_pct"] + HOME_EDGE_MLB, 0.99)
    wp_a = ta["win_pct"]
    total = wp_h + wp_a
    if total <= 0:
        return None

    return {
        "home": round(wp_h / total, 4),
        "away": round(wp_a / total, 4),
    }


# ── Dispatcher ───────────────────────────────────────────────────────────────

def predecir(home: str, away: str, sport: str) -> Optional[Dict]:
    """
    Returns model probability dict for a match, or None if unavailable.
    None → pick_engine falls back to market-derived probabilities.
    """
    try:
        if sport == "futbol":
            return predecir_futbol(home, away)
        if sport == "basquet":
            return predecir_basquet(home, away)
        if sport == "mlb":
            return predecir_mlb(home, away)
    except Exception as e:
        print(f"[predictor] {sport} {home} vs {away}: {e}")
    return None
