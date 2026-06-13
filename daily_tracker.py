import json
import os
from data_fetcher import obtener_fecha_utc_real

DAILY_STATE_PATH = os.getenv("DAILY_STATE_PATH", "/tmp/daily_state.json")


def _cargar() -> dict:
    if os.path.exists(DAILY_STATE_PATH):
        with open(DAILY_STATE_PATH) as f:
            return json.load(f)
    return {"ultima_fecha": "", "enviado": False}


def _guardar(estado: dict):
    with open(DAILY_STATE_PATH, "w") as f:
        json.dump(estado, f)


def ya_se_enviaron_hoy() -> bool:
    estado = _cargar()
    try:
        hoy = obtener_fecha_utc_real().isoformat()
        return estado.get("ultima_fecha") == hoy and estado.get("enviado", False)
    except Exception:
        return False


def marcar_enviados():
    try:
        hoy = obtener_fecha_utc_real().isoformat()
    except Exception:
        return
    _guardar({"ultima_fecha": hoy, "enviado": True})


def resetear():
    _guardar({"ultima_fecha": "", "enviado": False})
