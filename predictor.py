"""
Statistical probability models — independent from market odds.

Football : Dixon-Coles simplified Poisson model using season averages.
           Falls back to FIFA ranking points for World Cup when stats unavailable.
MLB      : Win-% ratio (Log5) with home advantage + recent form.
           Totals adjusted by probable pitcher ERA + ballpark factor.

Returns None on failure so pick_engine can fall back gracefully.
"""
import math
from typing import Dict, Optional, List
from sports_data import (
    get_stats_futbol, get_standings_mlb, get_stats_mlb,
    similitud, get_forma_reciente_futbol, get_h2h_futbol,
    FOOTBALL_LEAGUE, FOOTBALL_SEASON,
    WORLD_CUP_LEAGUE, WORLD_CUP_SEASON,
    CHAMPIONS_LEAGUE, CHAMPIONS_SEASON,
)

_FUTBOL_LEAGUES = {
    "futbol":    (FOOTBALL_LEAGUE,  FOOTBALL_SEASON),
    "mundial":   (WORLD_CUP_LEAGUE, WORLD_CUP_SEASON),
    "champions": (CHAMPIONS_LEAGUE, CHAMPIONS_SEASON),
}

LEAGUE_AVG_GOALS = 2.65
HOME_FACTOR_FUTBOL = 1.12
HOME_EDGE_MLB = 0.025
MIN_MATCH_SCORE = 0.50
MUNDIAL_GROUP_STAGE_FACTOR = 0.88  # group stage produces ~12% fewer goals than domestic leagues

# FIFA ranking points (approximate June 2026) — used as fallback when WC stats unavailable
FIFA_RANKING_POINTS = {
    "argentina": 1900, "france": 1850, "england": 1800,
    "brazil": 1780, "belgium": 1770, "portugal": 1750,
    "spain": 1740, "netherlands": 1720, "germany": 1710,
    "italy": 1700, "croatia": 1640, "uruguay": 1635,
    "usa": 1615, "united states": 1615, "mexico": 1605,
    "colombia": 1590, "senegal": 1585, "denmark": 1575,
    "austria": 1565, "switzerland": 1555, "morocco": 1545,
    "australia": 1538, "japan": 1532, "south korea": 1522,
    "korea republic": 1522, "republic of korea": 1522,
    "ecuador": 1515, "canada": 1505, "poland": 1498,
    "nigeria": 1492, "peru": 1480, "chile": 1478,
    "czech republic": 1468, "czechia": 1468, "hungary": 1462, "scotland": 1458,
    "slovakia": 1448, "turkey": 1442, "turkiye": 1442, "ukraine": 1438,
    "cameroon": 1422, "ghana": 1418, "ivory coast": 1412,
    "cote d'ivoire": 1412, "côte d'ivoire": 1412, "egypt": 1408, "algeria": 1402,
    "iran": 1392, "ir iran": 1392, "south africa": 1382, "paraguay": 1372,
    "venezuela": 1368, "bolivia": 1362, "panama": 1352, "costa rica": 1348,
    "honduras": 1338, "el salvador": 1328, "jamaica": 1325, "new zealand": 1312,
    "saudi arabia": 1308, "qatar": 1298, "indonesia": 1288,
    "iraq": 1282, "jordan": 1275, "uzbekistan": 1268, "oman": 1248,
    "tunisia": 1418, "mali": 1378, "dr congo": 1342, "congo dr": 1342,
    "democratic republic of congo": 1342, "dr. congo": 1342,
    "cape verde": 1322, "cabo verde": 1322,
    "trinidad and tobago": 1298, "trinidad & tobago": 1298,
    "guatemala": 1232, "cuba": 1195,
    "curacao": 1180, "curaçao": 1180,
    "bosnia": 1388, "bosnia & herzegovina": 1388, "bosnia and herzegovina": 1388,
    "nigeria": 1492, "kenya": 1185, "zimbabwe": 1148,
    "new caledonia": 1050, "tahiti": 1020,
    "haiti": 1210, "bermuda": 980,
    "sweden": 1530, "norway": 1480, "republic of ireland": 1445, "ireland": 1445,
    "finland": 1412, "iceland": 1438,
}

# MLB park run factors (home team's park inflates/deflates run totals)
MLB_PARK_FACTORS = {
    "colorado rockies": 1.150,
    "cincinnati reds": 1.080,
    "boston red sox": 1.055,
    "philadelphia phillies": 1.040,
    "texas rangers": 1.030,
    "baltimore orioles": 1.020,
    "chicago cubs": 1.010,
    "new york yankees": 1.005,
    "atlanta braves": 1.000,
    "houston astros": 0.995,
    "toronto blue jays": 0.995,
    "washington nationals": 0.985,
    "minnesota twins": 0.985,
    "detroit tigers": 0.975,
    "kansas city royals": 0.975,
    "chicago white sox": 0.970,
    "tampa bay rays": 0.960,
    "miami marlins": 0.960,
    "cleveland guardians": 0.958,
    "st. louis cardinals": 0.958,
    "milwaukee brewers": 0.950,
    "pittsburgh pirates": 0.948,
    "new york mets": 0.945,
    "arizona diamondbacks": 0.945,
    "los angeles angels": 0.943,
    "seattle mariners": 0.940,
    "los angeles dodgers": 0.932,
    "athletics": 0.928,
    "san diego padres": 0.920,
    "san francisco giants": 0.910,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def _dc_tau(x: int, y: int, lam_h: float, lam_a: float, rho: float = -0.13) -> float:
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
    num = wp_a - wp_a * wp_b
    den = wp_a + wp_b - 2 * wp_a * wp_b
    return num / den if den > 0 else 0.5


def _buscar_en_standings(name: str, standings: List[Dict]) -> Optional[Dict]:
    best = max(standings, key=lambda s: similitud(name, s["name"]), default=None)
    if best and similitud(name, best["name"]) >= MIN_MATCH_SCORE:
        return best
    return None


def _get_park_factor(home_team: str) -> float:
    name = home_team.lower().strip()
    for k, v in MLB_PARK_FACTORS.items():
        if k in name or name in k:
            return v
    return 1.0


def _best_fifa_pts(team: str) -> Optional[float]:
    best_score = 0.0
    best_pts = None
    for key, pts in FIFA_RANKING_POINTS.items():
        s = similitud(team, key)
        if s > best_score:
            best_score = s
            best_pts = pts
    return best_pts if best_score >= 0.55 else None


def _fifa_prob(home: str, away: str) -> Optional[Dict]:
    """Estimate H2H win probability using FIFA ranking points."""
    h_pts = _best_fifa_pts(home)
    a_pts = _best_fifa_pts(away)
    if not h_pts or not a_pts:
        return None

    # Logistic ELO-style: +50 pts home advantage
    diff = (h_pts - a_pts) + 50
    prob_home_raw = 1 / (1 + 10 ** (-diff / 600))

    # Draw estimation: higher when teams are evenly matched
    closeness = 1 - abs(prob_home_raw - 0.5) * 2
    prob_draw = 0.15 + closeness * 0.15  # [0.15, 0.30]

    prob_home = prob_home_raw * (1 - prob_draw)
    prob_away = (1 - prob_home_raw) * (1 - prob_draw)
    total = prob_home + prob_draw + prob_away

    return {
        "home": round(prob_home / total, 4),
        "draw": round(prob_draw / total, 4),
        "away": round(prob_away / total, 4),
    }


# ── Football model ────────────────────────────────────────────────────────────

def predecir_futbol(home: str, away: str, deporte: str = "futbol") -> Optional[Dict]:
    league_id, season = _FUTBOL_LEAGUES.get(deporte, (FOOTBALL_LEAGUE, FOOTBALL_SEASON))
    stats_h = get_stats_futbol(home, league_id, season)
    stats_a = get_stats_futbol(away, league_id, season)

    if not stats_h or not stats_a:
        if deporte == "mundial":
            return _fifa_prob(home, away)
        return None

    league_avg = LEAGUE_AVG_GOALS / 2

    atk_h = stats_h["goals_for"] / league_avg
    def_h = stats_h["goals_against"] / league_avg
    atk_a = stats_a["goals_for"] / league_avg
    def_a = stats_a["goals_against"] / league_avg

    lam_h = atk_h * def_a * league_avg * HOME_FACTOR_FUTBOL
    lam_a = atk_a * def_h * league_avg

    lam_h *= get_forma_reciente_futbol(home)
    lam_a *= get_forma_reciente_futbol(away)

    p_home, p_draw, p_away = _probs_poisson(lam_h, lam_a)
    total = p_home + p_draw + p_away
    if total <= 0:
        return None

    ph = p_home / total
    pd = p_draw / total
    pa = p_away / total

    h2h = get_h2h_futbol(home, away)
    if h2h:
        ph = 0.70 * ph + 0.30 * h2h["home_wr"]
        pd = 0.70 * pd + 0.30 * h2h["draw_r"]
        pa = 0.70 * pa + 0.30 * h2h["away_wr"]

    return {
        "home": round(ph, 4),
        "draw": round(pd, 4),
        "away": round(pa, 4),
    }


# ── MLB model ─────────────────────────────────────────────────────────────────

def predecir_mlb(home: str, away: str) -> Optional[Dict]:
    # Free official MLB API first — preserves API-Sports quota
    try:
        from mlb_stats import get_standings_free
        standings = get_standings_free()
    except Exception:
        standings = None
    if not standings:
        standings = get_standings_mlb()
    if not standings:
        return None

    th = _buscar_en_standings(home, standings)
    ta = _buscar_en_standings(away, standings)
    if not th or not ta:
        return None

    wp_h_season = min(th["win_pct"] + HOME_EDGE_MLB, 0.99)
    wp_a_season = ta["win_pct"]

    try:
        from mlb_stats import get_forma_reciente_mlb
        forma_h = get_forma_reciente_mlb(home)
        forma_a = get_forma_reciente_mlb(away)
        # Convert form factor [0.88, 1.12] to recent win rate, capped to [0.30, 0.70]
        # so a 10-0 or 0-10 streak doesn't swing probabilities to impossible extremes
        recent_wp_h = max(0.30, min(0.70, (forma_h - 0.88) / 0.24))
        recent_wp_a = max(0.30, min(0.70, (forma_a - 0.88) / 0.24))
        # Blend: 85% season win%, 15% last-10-games win%
        wp_h = min(wp_h_season * 0.85 + recent_wp_h * 0.15, 0.99)
        wp_a = wp_a_season * 0.85 + recent_wp_a * 0.15
    except Exception:
        wp_h = wp_h_season
        wp_a = wp_a_season

    prob_home = _log5(wp_h, wp_a)
    return {
        "home": round(prob_home, 4),
        "away": round(1 - prob_home, 4),
    }


MLB_TOTAL_STD = 3.0     # Normal distribution std for total runs per game
LEAGUE_RPG = 4.50       # MLB average runs per team per game
LEAGUE_BULLPEN_ERA = 3.80  # Bullpen ERA is lower than starter ERA
STARTER_IP = 5.5        # Average starter innings pitched before bullpen


def _normal_prob_over(expected: float, std: float, linea: float) -> float:
    z = (linea - expected) / (std * math.sqrt(2))
    return round(0.5 * (1 - math.erf(z)), 4)


def predecir_total_mlb(home: str, away: str, linea: float) -> Optional[Dict]:
    """
    P(Over/Under linea runs) — professional sharp model:

    1. Baseline: team offense × (opposing defense / league avg)  [Dixon-Coles style]
    2. Pitcher: replace defense component with game-level ERA
               (starter ~5.5 innings + bullpen ~3.5 innings at league bullpen ERA)
               Good pitcher (low ERA) → factor < 1 → opposing team scores less
    3. Park factor, weather, umpire
    """
    try:
        from mlb_stats import get_stats_mlb_free
        stats_h = get_stats_mlb_free(home)
        stats_a = get_stats_mlb_free(away)
    except Exception:
        stats_h = stats_a = None
    if not stats_h:
        stats_h = get_stats_mlb(home)
    if not stats_a:
        stats_a = get_stats_mlb(away)

    if stats_h and stats_a:
        h_rpg = stats_h["rpg"]
        a_rpg = stats_a["rpg"]
        # Base: team offense × (opposing defense quality / league average)
        exp_home = h_rpg * (stats_a.get("rapg", LEAGUE_RPG) / LEAGUE_RPG)
        exp_away = a_rpg * (stats_h.get("rapg", LEAGUE_RPG) / LEAGUE_RPG)
    else:
        try:
            from mlb_stats import get_standings_free
            standings = get_standings_free()
        except Exception:
            standings = None
        if not standings:
            standings = get_standings_mlb()
        if not standings:
            return None
        th = _buscar_en_standings(home, standings)
        ta = _buscar_en_standings(away, standings)
        if not th or not ta:
            return None
        exp_home = max(3.5, min(5.5, 4.5 + (th["win_pct"] - 0.5) * 2))
        exp_away = max(3.5, min(5.5, 4.5 + (ta["win_pct"] - 0.5) * 2))
        stats_h = stats_a = None

    # Pitcher adjustment: game-level ERA = starter ERA × starter innings + bullpen ERA × bullpen innings
    # A good starting pitcher (low ERA) reduces the opposing team's expected runs.
    pitcher_data_disponible = False
    try:
        from mlb_stats import get_probable_pitchers, LEAGUE_ERA
        # League average game ERA (starter portion + bullpen portion)
        LEAGUE_GAME_RA = (LEAGUE_ERA * STARTER_IP + LEAGUE_BULLPEN_ERA * (9.0 - STARTER_IP)) / 9.0
        pitchers = get_probable_pitchers(home, away)
        if pitchers:
            pitcher_data_disponible = True
            if pitchers.get("home_era") and stats_h is not None:
                # Home pitcher faces away batters → game-level ERA for today's matchup
                home_game_ra = (pitchers["home_era"] * STARTER_IP + LEAGUE_BULLPEN_ERA * (9.0 - STARTER_IP)) / 9.0
                # Replace defense component with today's pitcher projection
                exp_away = stats_a["rpg"] * (home_game_ra / LEAGUE_GAME_RA)
            if pitchers.get("away_era") and stats_a is not None:
                away_game_ra = (pitchers["away_era"] * STARTER_IP + LEAGUE_BULLPEN_ERA * (9.0 - STARTER_IP)) / 9.0
                exp_home = stats_h["rpg"] * (away_game_ra / LEAGUE_GAME_RA)
    except Exception as e:
        print(f"[predictor] pitcher adjustment: {e}")

    park_f = _get_park_factor(home)
    expected_total = (exp_home + exp_away) * park_f

    try:
        from mlb_weather import get_weather_factor
        expected_total *= get_weather_factor(home)
    except Exception as e:
        print(f"[predictor] weather: {e}")

    try:
        from mlb_stats import get_umpire_factor
        expected_total *= get_umpire_factor(home, away)
    except Exception as e:
        print(f"[predictor] umpire: {e}")

    # Without today's pitcher data the model can't compete with the market — widen std
    std = MLB_TOTAL_STD if pitcher_data_disponible else MLB_TOTAL_STD * 1.6
    if not pitcher_data_disponible:
        print(f"[predictor] {home} vs {away}: sin pitcher data — STD={std:.1f}")

    prob_over = _normal_prob_over(expected_total, std, linea)
    return {"over": prob_over, "under": round(1 - prob_over, 4)}


# ── Football totals model ─────────────────────────────────────────────────────

def predecir_total_futbol(home: str, away: str, linea: float, deporte: str = "futbol") -> Optional[Dict]:
    league_id, season = _FUTBOL_LEAGUES.get(deporte, (FOOTBALL_LEAGUE, FOOTBALL_SEASON))
    stats_h = get_stats_futbol(home, league_id, season)
    stats_a = get_stats_futbol(away, league_id, season)

    if not stats_h or not stats_a:
        # World Cup Under 2.5 model: ONLY for the 2.5 line (not 1.5 / 2.0 / 2.25).
        # Those lines have very different base rates and the FIFA ranking model
        # doesn't have enough resolution to price them reliably.
        if deporte == "mundial" and linea == 2.5:
            h_pts = _best_fifa_pts(home)
            a_pts = _best_fifa_pts(away)
            if h_pts and a_pts:
                diff = abs(h_pts - a_pts)
                if diff < 100:
                    prob_under = 0.58
                elif diff < 200:
                    prob_under = 0.56
                elif diff < 350:
                    prob_under = 0.54
                else:
                    return None
                return {"over": round(1 - prob_under, 4), "under": round(prob_under, 4)}
        return None

    league_avg = LEAGUE_AVG_GOALS / 2
    lam_h = (stats_h["goals_for"] / league_avg) * (stats_a["goals_against"] / league_avg) * league_avg * HOME_FACTOR_FUTBOL
    lam_a = (stats_a["goals_for"] / league_avg) * (stats_h["goals_against"] / league_avg) * league_avg
    lam_h *= get_forma_reciente_futbol(home)
    lam_a *= get_forma_reciente_futbol(away)

    # Group stage correction: teams score ~12% fewer goals than in domestic leagues
    if deporte == "mundial":
        lam_h *= MUNDIAL_GROUP_STAGE_FACTOR
        lam_a *= MUNDIAL_GROUP_STAGE_FACTOR

    prob_over = 0.0
    for i in range(15):
        for j in range(15):
            if i + j > linea:
                prob_over += _poisson_pmf(i, lam_h) * _poisson_pmf(j, lam_a)

    return {"over": round(prob_over, 4), "under": round(1 - prob_over, 4)}


# ── Dispatchers ───────────────────────────────────────────────────────────────

def predecir(home: str, away: str, sport: str) -> Optional[Dict]:
    try:
        if sport in ("futbol", "mundial", "champions"):
            return predecir_futbol(home, away, sport)
        if sport == "mlb":
            return predecir_mlb(home, away)
    except Exception as e:
        print(f"[predictor] h2h {sport} {home} vs {away}: {e}")
    return None


def predecir_total(home: str, away: str, sport: str, linea: float) -> Optional[Dict]:
    try:
        if sport in ("futbol", "mundial", "champions"):
            return predecir_total_futbol(home, away, linea, sport)
        if sport == "mlb":
            return predecir_total_mlb(home, away, linea)
    except Exception as e:
        print(f"[predictor] total {sport} {home} vs {away} {linea}: {e}")
    return None
