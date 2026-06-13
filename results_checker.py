"""
Fetches match results from API-Sports and resolves pending picks.
Posts win/loss updates to the Telegram channel automatically.
"""
from typing import Optional, List, Dict
from sports_data import (
    _get, _cache_get, _cache_set, similitud,
    FOOTBALL_LEAGUE, FOOTBALL_SEASON,
    WORLD_CUP_LEAGUE, WORLD_CUP_SEASON,
    CHAMPIONS_LEAGUE, CHAMPIONS_SEASON,
    BASKETBALL_LEAGUE, BASKETBALL_SEASON,
    MLB_LEAGUE, MLB_SEASON,
)

# Maps deporte key → (API-Sports league_id, season)
FOOTBALL_LEAGUES = {
    "futbol":    (FOOTBALL_LEAGUE,  FOOTBALL_SEASON),
    "mundial":   (WORLD_CUP_LEAGUE, WORLD_CUP_SEASON),
    "champions": (CHAMPIONS_LEAGUE, CHAMPIONS_SEASON),
}
from picks_tracker import cargar_picks_pendientes_de_fecha, marcar_resultado, get_stats
from bankroll import actualizar_resultado
from telegram_bot import enviar_mensaje

MATCH_THRESHOLD = 0.55


def _coincide(name_api: str, name_pick: str) -> bool:
    return similitud(name_api, name_pick) >= MATCH_THRESHOLD


# ── Per-sport result fetchers ─────────────────────────────────────────────────

def _resultado_futbol(pick: Dict, fecha: str) -> Optional[str]:
    deporte = pick.get("deporte", "futbol")
    league_id, season = FOOTBALL_LEAGUES.get(deporte, (FOOTBALL_LEAGUE, FOOTBALL_SEASON))
    cache_key = f"res_{deporte}_{fecha}"
    fixtures = _cache_get(cache_key)
    if fixtures is None:
        data = _get("https://v3.football.api-sports.io", "fixtures",
                    {"league": league_id, "season": season, "date": fecha})
        fixtures = data.get("response", []) if data else []
        _cache_set(cache_key, fixtures)

    equipo = pick.get("equipo", "")
    tipo = pick.get("tipo_apuesta", "")

    for f in fixtures:
        teams = f.get("teams", {})
        h_name = teams.get("home", {}).get("name", "")
        a_name = teams.get("away", {}).get("name", "")

        # For totals, equipo is "Home vs Away"
        if " vs " in equipo:
            partes = equipo.split(" vs ")
            home_ok = _coincide(h_name, partes[0]) or _coincide(a_name, partes[0])
            away_ok = _coincide(h_name, partes[1]) or _coincide(a_name, partes[1])
            if not (home_ok and away_ok):
                continue
        else:
            if not (_coincide(h_name, equipo) or _coincide(a_name, equipo)):
                continue

        status = f.get("fixture", {}).get("status", {}).get("short", "")
        if status not in ("FT", "AET", "PEN"):
            return None  # still in progress

        g = f.get("goals", {})
        gh = g.get("home") or 0
        ga = g.get("away") or 0

        if "Over" in tipo:
            linea = float(tipo.split()[1])
            return "ganado" if (gh + ga) > linea else "perdido"
        if "Under" in tipo:
            linea = float(tipo.split()[1])
            return "ganado" if (gh + ga) < linea else "perdido"

        # H2H — equipo is the team we backed
        if _coincide(h_name, equipo):
            return "ganado" if gh > ga else "perdido"
        else:
            return "ganado" if ga > gh else "perdido"

    return None


def _resultado_basquet(pick: Dict, fecha: str) -> Optional[str]:
    cache_key = f"res_bq_{fecha}"
    games = _cache_get(cache_key)
    if games is None:
        data = _get("https://v1.basketball.api-sports.io", "games",
                    {"league": BASKETBALL_LEAGUE, "date": fecha})
        games = data.get("response", []) if data else []
        _cache_set(cache_key, games)

    equipo = pick.get("equipo", "")
    tipo = pick.get("tipo_apuesta", "")

    for g in games:
        teams = g.get("teams", {})
        h_name = teams.get("home", {}).get("name", "")
        a_name = teams.get("visitors", {}).get("name", "")
        home_ok = _coincide(h_name, equipo)
        away_ok = _coincide(a_name, equipo)
        if not (home_ok or away_ok):
            continue

        if g.get("status", {}).get("short") != "FT":
            return None

        scores = g.get("scores", {})
        sh = scores.get("home", {}).get("total") or 0
        sa = scores.get("visitors", {}).get("total") or 0

        if "Over" in tipo:
            linea = float(tipo.split()[1])
            return "ganado" if (sh + sa) > linea else "perdido"
        if "Under" in tipo:
            linea = float(tipo.split()[1])
            return "ganado" if (sh + sa) < linea else "perdido"

        return "ganado" if (home_ok and sh > sa) or (away_ok and sa > sh) else "perdido"

    return None


def _resultado_mlb(pick: Dict, fecha: str) -> Optional[str]:
    cache_key = f"res_mlb_{fecha}"
    games = _cache_get(cache_key)
    if games is None:
        data = _get("https://v1.baseball.api-sports.io", "games",
                    {"league": MLB_LEAGUE, "season": MLB_SEASON, "date": fecha})
        games = data.get("response", []) if data else []
        _cache_set(cache_key, games)

    equipo = pick.get("equipo", "")

    for g in games:
        teams = g.get("teams", {})
        h_name = teams.get("home", {}).get("name", "")
        a_name = teams.get("away", {}).get("name", "")
        home_ok = _coincide(h_name, equipo)
        away_ok = _coincide(a_name, equipo)
        if not (home_ok or away_ok):
            continue

        if g.get("status", {}).get("short") != "FT":
            return None

        scores = g.get("scores", {})
        sh = scores.get("home", {}).get("total") or 0
        sa = scores.get("away", {}).get("total") or 0

        return "ganado" if (home_ok and sh > sa) or (away_ok and sa > sh) else "perdido"

    return None


# ── Main verification function ────────────────────────────────────────────────

def verificar_picks_fecha(fecha: str) -> Dict:
    """
    Checks API-Sports for results of all pending picks from a given date.
    Updates results, bankroll state, and posts to Telegram.
    """
    pendientes = cargar_picks_pendientes_de_fecha(fecha)
    if not pendientes:
        return {"verificados": 0, "stats": get_stats()}

    verificadores = {
        "futbol":    _resultado_futbol,
        "mundial":   _resultado_futbol,
        "champions": _resultado_futbol,
        "basquet":   _resultado_basquet,
        "mlb":       _resultado_mlb,
    }

    actualizados = []
    for pick in pendientes:
        deporte = pick.get("deporte", "")
        fn = verificadores.get(deporte)
        if not fn:
            continue
        resultado = fn(pick, fecha)
        if resultado:
            marcar_resultado(fecha, pick["id"], resultado)
            actualizar_resultado(resultado == "ganado")
            actualizados.append({"pick": pick, "resultado": resultado})

    if actualizados:
        _publicar_resultados(actualizados)

    return {"verificados": len(actualizados), "stats": get_stats()}


def _publicar_resultados(actualizados: List[Dict]):
    lines = ["📊 *RESULTADOS DEL DÍA*", "━━━━━━━━━━━━━━━━━━━━━━"]
    for item in actualizados:
        p = item["pick"]
        r = item["resultado"]
        ico = "✅" if r == "ganado" else "❌"
        u_txt = f"+{round(p['unidades']*(p['cuota']-1),2)}u" if r == "ganado" else f"-{p['unidades']}u"
        lines.append(f"{ico} *{p['equipo']}* — cuota {p['cuota']} → {u_txt}")

    s = get_stats()
    racha_txt = f"{'🔥' if s['racha'] > 0 else '❄️'} Racha: {'+' if s['racha']>0 else ''}{s['racha']}"
    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"🎯 *Acierto:* {s['win_pct']}%  ({s['ganados']}✅/{s['perdidos']}❌/{s['total']} picks)",
        f"💰 *Unidades:* {'+' if s['unidades']>=0 else ''}{s['unidades']}u  |  ROI: {'+' if s['roi_pct']>=0 else ''}{s['roi_pct']}%",
        racha_txt,
    ]
    enviar_mensaje("\n".join(lines))
