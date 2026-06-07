"""
bankroll.py
Gestión de estado de banca: normal / defensa / crítico
Persiste en archivo JSON local (Railway volume o filesystem efímero con reset diario).
"""
import json
import os
from models import EstadoBanca

ESTADO_PATH = os.getenv("BANKROLL_STATE_PATH", "/tmp/bankroll_state.json")

DEFAULT_STATE = {
    "modo": "normal",
    "perdidas_consecutivas": 0,
    "unidad_base": 0.02,  # 2% de banca como unidad base
}

def cargar_estado() -> EstadoBanca:
    if os.path.exists(ESTADO_PATH):
        with open(ESTADO_PATH, "r") as f:
            data = json.load(f)
        return EstadoBanca(**data)
    return EstadoBanca(**DEFAULT_STATE)

def guardar_estado(estado: EstadoBanca):
    with open(ESTADO_PATH, "w") as f:
        json.dump(estado.dict(), f)

def actualizar_resultado(gano: bool) -> EstadoBanca:
    """Llamar después de cada resultado conocido."""
    estado = cargar_estado()
    if gano:
        estado.perdidas_consecutivas = 0
        estado.modo = "normal"
        estado.unidad_base = 0.02
    else:
        estado.perdidas_consecutivas += 1
        if estado.perdidas_consecutivas >= 5:
            estado.modo = "critico"
            estado.unidad_base = 0.005   # 0.5% — stakes mínimos
        elif estado.perdidas_consecutivas >= 3:
            estado.modo = "defensa"
            estado.unidad_base = 0.01    # 1% — stakes a la mitad
        else:
            estado.modo = "normal"
            estado.unidad_base = 0.02
    guardar_estado(estado)
    return estado

def reset_estado():
    """Reset manual desde endpoint admin."""
    estado = EstadoBanca(**DEFAULT_STATE)
    guardar_estado(estado)
    return estado

def calcular_unidades(edge: float, estado: EstadoBanca) -> float:
    """
    Sistema de unidades escalado al edge:
    - 1 unidad: edge 4–7% (prob 54–57%)
    - 2 unidades: edge 7–11% (prob 57–61%)
    - 3 unidades: edge >11% (prob >61%)
    En modo defensa: máximo 1 unidad sin importar edge.
    En modo crítico: máximo 0.5 unidades.
    """
    if edge >= 0.11:
        raw = 3.0
    elif edge >= 0.07:
        raw = 2.0
    elif edge >= 0.04:
        raw = 1.0
    else:
        raw = 0.0  # no cumple mínimo, no apostar

    if estado.modo == "critico":
        return min(raw, 0.5)
    elif estado.modo == "defensa":
        return min(raw, 1.0)
    return raw
