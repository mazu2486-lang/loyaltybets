from pydantic import BaseModel
from typing import Literal, Optional

class PickOutput(BaseModel):
    deporte: str
    liga: str
    equipo: str
    tipo_apuesta: str          # "Local", "Visitante", "Over 2.5", etc.
    cuota: float
    prob_modelo: float         # probabilidad implícita corregida (interna)
    valor_esperado: float      # EV interno, no se muestra al canal
    edge: float                # edge % sobre la cuota
    semaforo: Literal["🟢", "🟡", "🔴"]
    unidades: float
    bookmaker_ref: str         # bookmaker recomendado

class Combinada(BaseModel):
    picks: list[PickOutput]
    cuota_combinada: float
    unidades: float
    bookmaker_ref: str

class EstadoBanca(BaseModel):
    modo: Literal["normal", "defensa", "critico"]
    perdidas_consecutivas: int
    unidad_base: float         # en % de banca
