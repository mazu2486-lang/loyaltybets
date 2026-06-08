from dataclasses import dataclass, field, asdict
from typing import Literal, List

@dataclass
class PickOutput:
    deporte: str
    liga: str
    equipo: str
    tipo_apuesta: str
    cuota: float
    prob_modelo: float
    valor_esperado: float
    edge: float
    semaforo: str  # "🟢", "🟡", "🔴"
    unidades: float
    bookmaker_ref: str

    def dict(self):
        return asdict(self)

@dataclass
class Combinada:
    picks: List[PickOutput]
    cuota_combinada: float
    unidades: float
    bookmaker_ref: str

    def dict(self):
        return asdict(self)

@dataclass
class EstadoBanca:
    modo: str  # "normal", "defensa", "critico"
    perdidas_consecutivas: int
    unidad_base: float

    def dict(self):
        return asdict(self)
