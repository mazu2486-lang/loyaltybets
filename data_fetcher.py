import os
import requests
from typing import List, Dict, Optional
from datetime import datetime, timezone, date

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
API_SPORTS_KEY = os.getenv("API_SPORTS_KEY", "")

DEPORTES_CON_TOTALS = {"futbol", "basquet", "mlb", "mundial", "champions"}

SPORTS_ODDSAPI = {
    "mundial":   "soccer_fifa_world_cup",
    "champions": "soccer_uefa_champs_league",
    "futbol":    "soccer_epl",
    "basquet":   "basketball_nba",
    "mlb":       "baseball_mlb",
    "tenis":     "tennis_atp_wimbledon",
}

def obtener_fecha_utc_real() -> date:
    try:
        resp = requests.get("https://worldtimeapi.org/api/timezone/UTC", timeout=5)
        if resp.status_code == 200:
            iso = resp.json().get("datetime", "")
            dt = datetime.fromisoformat(iso)
            return dt.date()
    except Exception:
        pass

    try:
        resp = requests.get("https://api.the-odds-api.com/v4/sports", params={"apiKey": ODDS_API_KEY or "x"}, timeout=5)
        date_header = resp.headers.get("Date", "")
        if date_header:
            dt = datetime.strptime(date_header, "%a, %d %b %Y %H:%M:%S %Z")
            dt = dt.replace(tzinfo=timezone.utc)
            return dt.date()
    except Exception:
        pass

    try:
        resp = requests.get("https://www.google.com", timeout=5)
        date_header = resp.headers.get("Date", "")
        if date_header:
            dt = datetime.strptime(date_header, "%a, %d %b %Y %H:%M:%S %Z")
            dt = dt.replace(tzinfo=timezone.utc)
            return dt.date()
    except Exception:
        pass

    raise RuntimeError("No se pudo obtener la fecha UTC real desde ninguna fuente externa.")

def evento_es_hoy(commence_time_iso: str, hoy_utc: date) -> bool:
    try:
        dt = datetime.fromisoformat(commence_time_iso.replace("Z", "+00:00"))
        return dt.date() == hoy_utc
    except Exception:
        return False

def evento_tiene_margen(commence_time_iso: str, horas_min: float = 2.0) -> bool:
    try:
        dt = datetime.fromisoformat(commence_time_iso.replace("Z", "+00:00"))
        ahora = datetime.now(timezone.utc)
        return (dt - ahora).total_seconds() >= horas_min * 3600
    except Exception:
        return True

def obtener_cuotas(deporte: str, hoy_utc=None) -> List[Dict]:
    sport_key = SPORTS_ODDSAPI.get(deporte)
    if not sport_key or not ODDS_API_KEY:
        return []

    if hoy_utc is None:
        hoy_utc = obtener_fecha_utc_real()
    markets = "h2h,totals" if deporte in DEPORTES_CON_TOTALS else "h2h"

    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu,us",
        "markets": markets,
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    resp = requests.get(url, params=params, timeout=10)
    if resp.status_code != 200:
        print(f"[OddsAPI] Error {resp.status_code}: {resp.text[:200]}")
        return []

    todos = resp.json()
    hoy_filtrados = [
        e for e in todos
        if evento_es_hoy(e.get("commence_time", ""), hoy_utc)
        and evento_tiene_margen(e.get("commence_time", ""))
    ]

    print(f"[OddsAPI] {deporte}: {len(todos)} eventos totales, {len(hoy_filtrados)} con margen ≥2h ({hoy_utc})")
    return hoy_filtrados

def extraer_mejores_cuotas(evento_odds: Dict) -> Dict:
    h2h: Dict[str, tuple] = {}
    totals: Dict[str, tuple] = {}

    for bookmaker in evento_odds.get("bookmakers", []):
        bk = bookmaker["key"]
        for market in bookmaker.get("markets", []):
            key = market["key"]
            if key == "h2h":
                for outcome in market["outcomes"]:
                    name = outcome["name"]
                    price = outcome["price"]
                    if name not in h2h or price > h2h[name][0]:
                        h2h[name] = (price, bk)
            elif key == "totals":
                for outcome in market["outcomes"]:
                    direction = outcome["name"]
                    point = outcome.get("point", "?")
                    label = f"{direction} {point}"
                    price = outcome["price"]
                    if label not in totals or price > totals[label][0]:
                        totals[label] = (price, bk)
    return {"h2h": h2h, "totals": totals}

def prob_implicita_sin_margen(cuota_a: float, cuota_b: float, cuota_empate: Optional[float] = None) -> Dict:
    outcomes = [cuota_a, cuota_b] + ([cuota_empate] if cuota_empate else [])
    probs_raw = [1 / c for c in outcomes]
    overround = sum(probs_raw)
    probs_ok = [p / overround for p in probs_raw]
    keys = ["local", "visitante"] + (["empate"] if cuota_empate else [])
    return dict(zip(keys, probs_ok))

def calcular_ev(prob_modelo: float, cuota: float) -> float:
    return round(prob_modelo * cuota - 1, 4)

def calcular_edge(prob_modelo: float, cuota: float) -> float:
    return round(prob_modelo - (1 / cuota), 4)
