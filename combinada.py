from typing import List, Optional
from models import PickOutput, Combinada, EstadoBanca
from collections import Counter

MIN_PICKS_COMBINADA = 3
MAX_PICKS_COMBINADA = 4
CUOTA_COMBINADA_MAX = 15.0
UNIDADES_COMBINADA = 0.5   # siempre fija, conservadora

def armar_combinada(picks: List[PickOutput], estado: EstadoBanca) -> Optional[Combinada]:
    if estado.modo in ("defensa", "critico"):
        return None

    candidatos = [p for p in picks if p.semaforo in ("🟢", "🟡")]

    if len(candidatos) < MIN_PICKS_COMBINADA:
        return None

    seleccionados = sorted(candidatos, key=lambda p: p.edge, reverse=True)[:MAX_PICKS_COMBINADA]

    cuota_combinada = 1.0
    for p in seleccionados:
        cuota_combinada *= p.cuota
    cuota_combinada = round(cuota_combinada, 2)

    if cuota_combinada > CUOTA_COMBINADA_MAX:
        seleccionados = seleccionados[:3]
        cuota_combinada = round(
            seleccionados[0].cuota * seleccionados[1].cuota * seleccionados[2].cuota, 2
        )

    if cuota_combinada > CUOTA_COMBINADA_MAX:
        return None

    bk_counter = Counter(p.bookmaker_ref for p in seleccionados)
    bookmaker_combinada = bk_counter.most_common(1)[0][0]

    return Combinada(
        picks=seleccionados,
        cuota_combinada=cuota_combinada,
        unidades=UNIDADES_COMBINADA,
        bookmaker_ref=bookmaker_combinada,
    )
