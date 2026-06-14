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
    get_stats_futbol, get_standings_basquet, get_standings_mlb, get_stats_mlb,
    similitud, get_forma_reciente_futbol, get_h2h_futbol,
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


def _dc_tau(x: int, y: int, lam_h: float, lam_a: float, rho: float = -0.13) -> float:
    """Dixon-Coles correction for low-score results (reduces Poisson bias)."""
    if x == 0 and y == 0:
        return 1 - lam_h * lam_a * rho
    if x == 0 and y == 1:
        return 1 + lam_h * rho
    if x == 1 and y == 0:
        return 1 + lam_a * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


def _probs_poisson(lam_h: float, lam_a: float) -> tuple:
    p_home = p_draw = p_away = 0.0
    for i in range(10):
        for j in range(10):
            p = _poisson_pmf(i, lam_h) * _poisson_pmf(j, lam_a) * _dc_tau(i, j, lam_h, lam_a)
            if i > j:
                p_home += p
            elif i == j:
                p_draw += p
            else:
                p_away += p
    return p_home, p_draw, p_away


def _log5(wp_a: float, wp_b: float) -> float:
    """Bill James log5 — more accurate than simple ratio for win probability."""
    num = wp_a - wp_a * wp_b
    den = wp_a + wp_b - 2 * wp_a * wp_b
    return num / den if den > 0 else 0.5


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

    league_avg = LEAGUE_AVG_GOALS / 2

    atk_h = stats_h["goals_for"] / league_avg
    def_h = stats_h["goals_against"] / league_avg
    atk_a = stats_a["goals_for"] / league_avg
    def_a = stats_a["goals_against"] / league_avg

    lam_h = atk_h * def_a * league_avg * HOME_FACTOR_FUTBOL
    lam_a = atk_a * def_h * league_avg

    # Adjust by recent form (last 5 games)
    lam_h *= get_forma_reciente_futbol(home)
    lam_a *= get_forma_reciente_futbol(away)

    p_home, p_draw, p_away = _probs_poisson(lam_h, lam_a)
    total = p_home + p_draw + p_away
    if total <= 0:
        return None

    ph = p_home / total
    pd = p_draw / total
    pa = p_away / total

    # Blend 70% Poisson + 30% H2H history when available
    h2h = get_h2h_futbol(home, away)
    if h2h:
        ph = 0.70 * ph + 0.30 * h2h["home_wr"]
        pd = 0.70 * pd + 0.30 * h2h["draw_r"]
        pa = 0.70 * pa + 0.30 * h2h["away_wr"]

    return {
        "home":  round(ph, 4),
        "draw":  round(pd, 4),
        "away":  round(pa, 4),
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
    prob_home = _log5(wp_h, wp_a)

    return {
        "home": round(prob_home, 4),
        "away": round(1 - prob_home, 4),
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
    prob_home = _log5(wp_h, wp_a)

    return {
        "home": round(prob_home, 4),
        "away": round(1 - prob_home, 4),
    }


NBA_TOTAL_STD = 11.0   # NBA game total standard deviation ≈ 11 pts
MLB_TOTAL_STD = 4.5    # MLB run total standard deviation ≈ 4.5 runs


def _normal_prob_over(expected: float, std: float, linea: float) -> float:
    """P(X > linea) where X ~ Normal(expected, std)."""
    z = (linea - expected) / (std * math.sqrt(2))
    return round(0.5 * (1 - math.erf(z)), 4)


def predecir_total_futbol(home: str, away: str, linea: float) -> Optional[Dict]:
    """P(Over/Under linea goals) using Poisson model."""
    stats_h = get_stats_futbol(home)
    stats_a = get_stats_futbol(away)
    if not stats_h or not stats_a:
        return None

    league_avg = LEAGUE_AVG_GOALS / 2
    lam_h = (stats_h["goals_for"] / league_avg) * (stats_a["goals_against"] / league_avg) * league_avg * HOME_FACTOR_FUTBOL
    lam_a = (stats_a["goals_for"] / league_avg) * (stats_h["goals_against"] / league_avg) * league_avg
    lam_h *= get_forma_reciente_futbol(home)
    lam_a *= get_forma_reciente_futbol(away)

    prob_over = 0.0
    for i in range(15):
        for j in range(15):
            if i + j > linea:
                prob_over += _poisson_pmf(i, lam_h) * _poisson_pmf(j, lam_a)

    return {"over": round(prob_over, 4), "under": round(1 - prob_over, 4)}


def predecir_total_basquet(home: str, away: str, linea: float) -> Optional[Dict]:
    """P(Over/Under linea pts) using ppg/papg from standings + normal dist."""
    standings = get_standings_basquet()
    if not standings:
        return None

    th = _buscar_en_standings(home, standings)
    ta = _buscar_en_standings(away, standings)
    if not th or not ta:
        return None

    # Weight own offense (60%) vs opponent defense (40%) — offense more predictive in NBA
    exp_home = th["ppg"] * 0.6 + ta["papg"] * 0.4
    exp_away = ta["ppg"] * 0.6 + th["papg"] * 0.4
    expected_total = exp_home + exp_away

    prob_over = _normal_prob_over(expected_total, NBA_TOTAL_STD, linea)
    return {"over": prob_over, "under": round(1 - prob_over, 4)}


def predecir_total_mlb(home: str, away: str, linea: float) -> Optional[Dict]:
    """P(Over/Under linea runs) using real rpg/rapg from API + normal dist."""
    stats_h = get_stats_mlb(home)
    stats_a = get_stats_mlb(away)

    if stats_h and stats_a:
        # Use actual runs scored/allowed per game — weight offense 60% / defense 40%
        exp_home = stats_h["rpg"] * 0.6 + stats_a["rapg"] * 0.4
        exp_away = stats_a["rpg"] * 0.6 + stats_h["rapg"] * 0.4
        expected_total = exp_home + exp_away
    else:
        # Fallback to win%-based estimate
        standings = get_standings_mlb()
        if not standings:
            return None
        th = _buscar_en_standings(home, standings)
        ta = _buscar_en_standings(away, standings)
        if not th or not ta:
            return None
        expected_total = (4.5 + (th["win_pct"] - 0.5) * 4) + (4.5 + (ta["win_pct"] - 0.5) * 4)

    prob_over = _normal_prob_over(expected_total, MLB_TOTAL_STD, linea)
    return {"over": prob_over, "under": round(1 - prob_over, 4)}


# ── Dispatchers ───────────────────────────────────────────────────────────────

def predecir(home: str, away: str, sport: str) -> Optional[Dict]:
    """H2H model probabilities. Returns None → fallback to market probs."""
    try:
        if sport == "futbol":
            return predecir_futbol(home, away)
        if sport == "basquet":
            return predecir_basquet(home, away)
        if sport == "mlb":
            return predecir_mlb(home, away)
    except Exception as e:
        print(f"[predictor] h2h {sport} {home} vs {away}: {e}")
    return None


def predecir_total(home: str, away: str, sport: str, linea: float) -> Optional[Dict]:
    """Totals model probabilities. Returns None → fallback to market probs."""
    try:
        if sport == "futbol":
            return predecir_total_futbol(home, away, linea)
        if sport == "basquet":
            return predecir_total_basquet(home, away, linea)
        if sport == "mlb":
            return predecir_total_mlb(home, away, linea)
    except Exception as e:
        print(f"[predictor] total {sport} {home} vs {away} {linea}: {e}")
    return None
