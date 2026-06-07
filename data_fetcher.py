"""
data_fetcher.py
Fuentes de datos:
- The Odds API: cuotas h2h + totals (Over/Under)
- MLB Stats API: stats de pitcher (ERA, WHIP, K%)

TIEMPO:
- Nunca se usa datetime.now() local — el reloj del servidor no es confiable.
- La fecha UTC real se obtiene del header 'Date' de cualquier respuesta HTTP
  a una fuente externa (worldtimeapi.org como primaria, fallback al header
  de The Odds API). Todos los filtros de "hoy" usan esa fecha.

Deportes con Over/Under habilitado: futbol, basquet, mlb
Tenis: solo h2h
"""
import os
import requests
from typing import List, Dict, Optional
from datetime import datetime, timezone, date

ODDS_API_KEY   = os.getenv("ODDS_API_KEY", "")
API_SPORTS_KEY = os.getenv("API_SPORTS_KEY", "")

DEPORTES_CON_TOTALS = {"futbol", "basquet", "mlb"}

SPORTS_ODDSAPI = {
    "futbol":  "soccer_epl",
    "basquet": "basketball_nba",
    "tenis":   "tennis_atp_french_open",
    "mlb":     "baseball_mlb",
}

# ─── HORA UTC CONFIABLE ──────────────────────────────────────────────────────

def obtener_fecha_utc_real() -> date:
    """
    Obtiene la fecha UTC real desde fuentes externas.
    Orden de intento:
      1. worldtimeapi.org  (API de tiempo dedicada, más confiable)
      2. Header 'Date' de la respuesta de The Odds API
      3. Header 'Date' de google.com como último fallback

    NUNCA usa datetime.now() — el reloj local puede estar mal.
    """
    # Intento 1: worldtimeapi.org
    try:
        resp = requests.get(
            "https://worldtimeapi.org/api/timezone/UTC",
            timeout=5,
        )
        if resp.status_code == 200:
            iso = resp.json().get("datetime", "")   # "2025-06-10T14:32:00.000000+00:00"
            dt  = datetime.fromisoformat(iso)
            print(f"[TIME] UTC real desde worldtimeapi: {dt.date()}")
            return dt.date()
    except Exception as e:
        print(f"[TIME] worldtimeapi falló: {e}")

    # Intento 2: header Date de The Odds API (siempre responde, aunque sea error)
    try:
        resp = requests.get(
            "https://api.the-odds-api.com/v4/sports",
            params={"apiKey": ODDS_API_KEY or "x"},
            timeout=5,
        )
        date_header = resp.headers.get("Date", "")
        if date_header:
            dt = datetime.strptime(date_header, "%a, %d %b %Y %H:%M:%S %Z")
            dt = dt.replace(tzinfo=timezone.utc)
            print(f"[TIME] UTC desde header OddsAPI: {dt.date()}")
            return dt.date()
    except Exception as e:
        print(f"[TIME] Header OddsAPI falló: {e}")

    # Intento 3: header Date de google.com
    try:
        resp = requests.get("https://www.google.com", timeout=5)
        date_header = resp.headers.get("Date", "")
        if date_header:
            dt = datetime.strptime(date_header, "%a, %d %b %Y %H:%M:%S %Z")
            dt = dt.replace(tzinfo=timezone.utc)
            print(f"[TIME] UTC desde header Google: {dt.date()}")
            return dt.date()
    except Exception as e:
        print(f"[TIME] Header Google falló: {e}")

    # Nunca debería llegar aquí, pero si todo falla levantamos excepción explícita
    raise RuntimeError(
        "No se pudo obtener la fecha UTC real desde ninguna fuente externa. "
        "Verifica la conexión a internet del servidor."
    )


def evento_es_hoy(commence_time_iso: str, hoy_utc: date) -> bool:
    """
    Verifica si el commence_time ISO del evento corresponde al día de hoy UTC.
    The Odds API devuelve fechas en formato: "2025-06-10T18:00:00Z"
    """
    try:
        dt = datetime.fromisoformat(commence_time_iso.replace("Z", "+00:00"))
        return dt.date() == hoy_utc
    except Exception:
        return False


# ─── CUOTAS ─────────────────────────────────────────────────────────────────

def obtener_cuotas(deporte: str) -> List[Dict]:
    """
    Retorna solo los eventos de HOY (UTC real) con cuotas h2h + totals.
    Filtra por commence_time usando fecha UTC obtenida de fuente externa.
    """
    sport_key = SPORTS_ODDSAPI.get(deporte)
    if not sport_key or not ODDS_API_KEY:
        return []

    hoy_utc = obtener_fecha_utc_real()
    markets  = "h2h,totals" if deporte in DEPORTES_CON_TOTALS else "h2h"

    url    = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {
        "apiKey":      ODDS_API_KEY,
        "regions":     "eu,us",
        "markets":     markets,
        "oddsFormat":  "decimal",
        "dateFormat":  "iso",
    }
    resp = requests.get(url, params=params, timeout=10)
    if resp.status_code != 200:
        print(f"[OddsAPI] Error {resp.status_code}: {resp.text[:200]}")
        return []

    todos = resp.json()

    # Filtrar solo partidos de hoy
    hoy_filtrados = [
        e for e in todos
        if evento_es_hoy(e.get("commence_time", ""), hoy_utc)
    ]

    print(f"[OddsAPI] {deporte}: {len(todos)} eventos totales, {len(hoy_filtrados)} hoy ({hoy_utc})")
    return hoy_filtrados


def extraer_mejores_cuotas(evento_odds: Dict) -> Dict:
    """
    Extrae la mejor cuota disponible por outcome (best odds approach).

    Retorna:
    - h2h:    { nombre_equipo: (cuota, bookmaker) }
    - totals: { "Over 2.5": (cuota, bk), "Under 2.5": (cuota, bk), ... }
    """
    h2h:    Dict[str, tuple] = {}
    totals: Dict[str, tuple] = {}

    for bookmaker in evento_odds.get("bookmakers", []):
        bk = bookmaker["key"]
        for market in bookmaker.get("markets", []):
            key = market["key"]

            if key == "h2h":
                for outcome in market["outcomes"]:
                    name  = outcome["name"]
                    price = outcome["price"]
                    if name not in h2h or price > h2h[name][0]:
                        h2h[name] = (price, bk)

            elif key == "totals":
                for outcome in market["outcomes"]:
                    direction = outcome["name"]           # "Over" | "Under"
                    point     = outcome.get("point", "?")
                    label     = f"{direction} {point}"   # "Over 2.5"
                    price     = outcome["price"]
                    if label not in totals or price > totals[label][0]:
                        totals[label] = (price, bk)

    return {"h2h": h2h, "totals": totals}


# ─── PROBABILIDADES MODELO ───────────────────────────────────────────────────

def prob_implicita_sin_margen(
    cuota_a: float,
    cuota_b: float,
    cuota_empate: Optional[float] = None,
) -> Dict:
    """Método Shin simplificado: remueve el margen del book."""
    outcomes   = [cuota_a, cuota_b] + ([cuota_empate] if cuota_empate else [])
    probs_raw  = [1 / c for c in outcomes]
    overround  = sum(probs_raw)
    probs_ok   = [p / overround for p in probs_raw]
    keys       = ["local", "visitante"] + (["empate"] if cuota_empate else [])
    return dict(zip(keys, probs_ok))

def calcular_ev(prob_modelo: float, cuota: float) -> float:
    return round(prob_modelo * cuota - 1, 4)

def calcular_edge(prob_modelo: float, cuota: float) -> float:
    return round(prob_modelo - (1 / cuota), 4)


# ─── MLB: PITCHERS ───────────────────────────────────────────────────────────

def obtener_pitchers_probables_hoy() -> Dict:
    """
    Usa MLB Stats API (pública, sin key) con fecha UTC real.
    Retorna { game_pk: { home, away, home_team, away_team } }
    """
    try:
        hoy_utc = obtener_fecha_utc_real()
    except RuntimeError:
        return {}

    url    = "https://statsapi.mlb.com/api/v1/schedule"
    params = {
        "sportId": 1,
        "date":    hoy_utc.strftime("%Y-%m-%d"),
        "hydrate": "probablePitcher(stats(type=season))",
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return {}
        resultado = {}
        for date_entry in resp.json().get("dates", []):
            for game in date_entry.get("games", []):
                gid = game["gamePk"]
                resultado[gid] = {
                    "home":      game.get("teams", {}).get("home", {}).get("probablePitcher"),
                    "away":      game.get("teams", {}).get("away", {}).get("probablePitcher"),
                    "home_team": game["teams"]["home"]["team"]["name"],
                    "away_team": game["teams"]["away"]["team"]["name"],
                }
        return resultado
    except Exception as e:
        print(f"[MLB Schedule] Error: {e}")
        return {}


def score_pitcher(pitcher_stats: Optional[Dict]) -> float:
    """Score 0–1 basado en ERA + WHIP del pitcher titular."""
    if not pitcher_stats:
        return 0.5
    stats = pitcher_stats.get("stats", [])
    if not stats:
        return 0.5
    era  = float(stats[0].get("era",  4.5))
    whip = float(stats[0].get("whip", 1.3))
    era_norm  = max(0, min(1, (6.0 - era)  / 4.5))
    whip_norm = max(0, min(1, (1.8 - whip) / 0.9))
    return round(era_norm * 0.6 + whip_norm * 0.4, 3)


# ─── NBA ─────────────────────────────────────────────────────────────────────

def verificar_load_management_nba(equipo: str) -> bool:
    """Placeholder — integrar ESPN injuries API en producción."""
    return False
