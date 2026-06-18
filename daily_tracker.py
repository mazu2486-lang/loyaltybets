import json
import os
import time
from data_fetcher import obtener_fecha_utc_real

DAILY_STATE_PATH = os.getenv("DAILY_STATE_PATH", "/tmp/daily_state.json")
COOLDOWN_SEGUNDOS = 300  # 5 minutos entre envíos aunque sea forzar=true


def _cargar() -> dict:
    if os.path.exists(DAILY_STATE_PATH):
        with open(DAILY_STATE_PATH) as f:
            return json.load(f)
    return {"ultima_fecha": "", "enviado": False, "ultimo_ts": 0}


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


def enviado_hace_poco() -> bool:
    """True si se envió hace menos de COOLDOWN_SEGUNDOS (evita doble envío por doble llamada)."""
    estado = _cargar()
    ultimo_ts = estado.get("ultimo_ts", 0)
    return (time.time() - ultimo_ts) < COOLDOWN_SEGUNDOS


def marcar_enviados():
    try:
        hoy = obtener_fecha_utc_real().isoformat()
    except Exception:
        return
    _guardar({"ultima_fecha": hoy, "enviado": True, "ultimo_ts": time.time()})


def resetear():
    _guardar({"ultima_fecha": "", "enviado": False, "ultimo_ts": 0})
