from typing import List
from models import PickOutput, Combinada, EstadoBanca
from collections import Counter

CUOTA_EXPRESS_MAX = 6.0
CUOTA_NORMAL_MAX = 12.0
CUOTA_ACUMULADA_MAX = 20.0


def _picks_independientes(candidatos: List[PickOutput], n: int) -> List[PickOutput]:
    """Selecciona n picks de partidos distintos, priorizando deportes distintos."""
    seleccionados: List[PickOutput] = []
    deportes_usados: set = set()
    partidos_usados: set = set()

    def _partido(p: PickOutput) -> str:
        return p.equipo if " vs " in p.equipo else p.equipo

    # First pass: one pick per sport, one per game
    for pick in candidatos:
        if len(seleccionados) >= n:
            break
        partido = _partido(pick)
        if pick.deporte not in deportes_usados and partido not in partidos_usados:
            seleccionados.append(pick)
            deportes_usados.add(pick.deporte)
            partidos_usados.add(partido)

    # Second pass: fill remaining slots (different game required)
    for pick in candidatos:
        if len(seleccionados) >= n:
            break
        partido = _partido(pick)
        if pick not in seleccionados and partido not in partidos_usados:
            seleccionados.append(pick)
            partidos_usados.add(partido)

    return seleccionados


def _cuota_combinada(picks: List[PickOutput]) -> float:
    result = 1.0
    for p in picks:
        result *= p.cuota
    return round(result, 2)


def _bookmaker_principal(picks: List[PickOutput]) -> str:
    return Counter(p.bookmaker_ref for p in picks).most_common(1)[0][0]


def armar_combinadas(picks: List[PickOutput], estado: EstadoBanca) -> List[Combinada]:
    if estado.modo == "critico":
        return []

    combinadas: List[Combinada] = []
    verdes = sorted(
        [p for p in picks if p.semaforo == "🟢"],
        key=lambda p: p.edge, reverse=True,
    )
    buenos = sorted(
        [p for p in picks if p.semaforo in ("🟢", "🟡")],
        key=lambda p: p.edge, reverse=True,
    )

    # Express: 2 picks 🟢 — disponible en normal y defensa
    if len(verdes) >= 2:
        sel = _picks_independientes(verdes, 2)
        cuota = _cuota_combinada(sel)
        if cuota <= CUOTA_EXPRESS_MAX:
            unidades = 1.0 if estado.modo == "normal" else 0.5
            combinadas.append(Combinada(
                picks=sel,
                cuota_combinada=cuota,
                unidades=unidades,
                bookmaker_ref=_bookmaker_principal(sel),
                tipo="express",
            ))

    if estado.modo != "normal":
        return combinadas

    # Normal: 3 picks 🟢/🟡 — solo modo normal
    if len(buenos) >= 3:
        sel = _picks_independientes(buenos, 3)
        cuota = _cuota_combinada(sel)
        if cuota <= CUOTA_NORMAL_MAX:
            combinadas.append(Combinada(
                picks=sel,
                cuota_combinada=cuota,
                unidades=0.5,
                bookmaker_ref=_bookmaker_principal(sel),
                tipo="normal",
            ))

    # Acumulada: 4 picks 🟢/🟡 — solo modo normal
    if len(buenos) >= 4:
        sel = _picks_independientes(buenos, 4)
        cuota = _cuota_combinada(sel)
        if cuota <= CUOTA_ACUMULADA_MAX:
            combinadas.append(Combinada(
                picks=sel,
                cuota_combinada=cuota,
                unidades=0.25,
                bookmaker_ref=_bookmaker_principal(sel),
                tipo="acumulada",
            ))

    return combinadas
