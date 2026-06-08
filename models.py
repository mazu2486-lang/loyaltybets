from pydantic import BaseModel
from typing import Literal, Optional, List

class PickOutput(BaseModel):
    deporte: str
    liga: str
    equipo: str
    tipo_apuesta: str
    cuota: float
    prob_modelo: float
    valor_esperado: float
    edge: float
    semaforo: Literal["🟢", "🟡", "🔴"]
    unidades: float
    bookmaker_ref: str

class Combinada(BaseModel):
    picks: List[PickOutput]
    cuota_combinada: float
    unidades: float
    bookmaker_ref: str

class EstadoBanca(BaseModel):
    modo: Literal["normal", "defensa", "critico"]
    perdidas_consecutivas: int
    unidad_base: float
