import json
import os
from models import EstadoBanca

ESTADO_PATH = os.getenv("BANKROLL_STATE_PATH", "/tmp/bankroll_state.json")

DEFAULT_STATE = {"modo": "normal", "perdidas_consecutivas": 0, "unidad_base": 0.02}

def cargar_estado() -> EstadoBanca:
    if os.path.exists(ESTADO_PATH):
        with open(ESTADO_PATH) as f:
            d = json.load(f)
        return EstadoBanca(**d)
    return EstadoBanca(**DEFAULT_STATE)

def guardar_estado(estado: EstadoBanca):
    with open(ESTADO_PATH, "w") as f:
        json.dump(estado.dict(), f)

def actualizar_resultado(gano: bool) -> EstadoBanca:
    estado = cargar_estado()
    if gano:
        estado.perdidas_consecutivas = 0
        estado.modo = "normal"
        estado.unidad_base = 0.02
    else:
        estado.perdidas_consecutivas += 1
        if estado.perdidas_consecutivas >= 5:
            estado.modo = "critico"
            estado.unidad_base = 0.005
        elif estado.perdidas_consecutivas >= 3:
            estado.modo = "defensa"
            estado.unidad_base = 0.01
        else:
            estado.modo = "normal"
            estado.unidad_base = 0.02
    guardar_estado(estado)
    return estado

def reset_estado() -> EstadoBanca:
    estado = EstadoBanca(**DEFAULT_STATE)
    guardar_estado(estado)
    return estado

def calcular_unidades(edge: float, estado: EstadoBanca) -> float:
    if edge >= 0.11:
        raw = 3.0
    elif edge >= 0.07:
        raw = 2.0
    elif
