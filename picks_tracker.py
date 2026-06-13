"""
Persists daily picks and tracks win/loss results.
Used by results_checker.py to verify outcomes and update stats.
"""
import json
import os
import uuid
from typing import Dict, List, Optional

PICKS_LOG_PATH = os.getenv("PICKS_LOG_PATH", "/tmp/picks_log.json")


def _cargar() -> Dict:
    try:
        if os.path.exists(PICKS_LOG_PATH):
            return json.load(open(PICKS_LOG_PATH))
    except Exception:
        pass
    return {}


def _guardar(log: Dict):
    try:
        json.dump(log, open(PICKS_LOG_PATH, "w"), default=str)
    except Exception:
        pass


def guardar_picks_dia(picks: List, fecha: str):
    """Saves the day's picks if not already saved."""
    log = _cargar()
    if fecha in log:
        return
    entries = []
    for p in picks:
        d = p.dict()
        d["id"] = str(uuid.uuid4())[:8]
        d["resultado"] = None
        entries.append(d)
    log[fecha] = entries
    _guardar(log)


def cargar_picks_por_fecha(fecha: str) -> List[Dict]:
    return _cargar().get(fecha, [])


def cargar_picks_pendientes_de_fecha(fecha: str) -> List[Dict]:
    """Returns picks from a specific date that have no result yet."""
    return [p for p in cargar_picks_por_fecha(fecha) if p.get("resultado") is None]


def marcar_resultado(fecha: str, pick_id: str, resultado: str):
    """Marks a pick as 'ganado', 'perdido', or 'anulado'."""
    log = _cargar()
    for pick in log.get(fecha, []):
        if pick.get("id") == pick_id:
            pick["resultado"] = resultado
            break
    _guardar(log)


def get_stats() -> Dict:
    """Returns cumulative stats across all tracked picks."""
    log = _cargar()
    total = ganados = perdidos = 0
    unidades = 0.0
    racha = 0

    resultados_orden = []
    for fecha in sorted(log):
        for pick in log[fecha]:
            r = pick.get("resultado")
            if r in ("ganado", "perdido"):
                resultados_orden.append((r, pick.get("unidades", 1.0), pick.get("cuota", 2.0)))

    for r, u, cuota in resultados_orden:
        total += 1
        if r == "ganado":
            ganados += 1
            unidades += u * (cuota - 1)
            racha = racha + 1 if racha >= 0 else 1
        else:
            perdidos += 1
            unidades -= u
            racha = racha - 1 if racha <= 0 else -1

    return {
        "total": total,
        "ganados": ganados,
        "perdidos": perdidos,
        "win_pct": round(ganados / total * 100, 1) if total else 0.0,
        "unidades": round(unidades, 2),
        "roi_pct": round(unidades / total * 100, 1) if total else 0.0,
        "racha": racha,
    }
