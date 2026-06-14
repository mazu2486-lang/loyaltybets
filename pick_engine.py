from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from models import PickOutput, EstadoBanca
from bankroll import calcular_unidades, cargar_estado
from data_fetcher import (
    obtener_cuotas, extraer_mejores_cuotas,
    prob_implicita_sin_margen, calcular_ev, calcular_edge,
    DEPORTES_CON_TOTALS, SPORTS_ODDSAPI, obtener_fecha_utc_real,
)
from predictor import predecir, predecir_total

CUOTA_MIN = 1.30
CUOTA_MAX = 3.50
MLB_TOTAL_MAX = 9.5  # ignore MLB totals above this line (too volatile)
EDGE_MIN = 0.04
PROB_MIN = 0.54
PICKS_DIARIOS = 7
MIN_PICKS = 4
MAX_PICKS = 7
EXPOSICION_MAX = 14.0

# Football markets are more efficient — require higher edge threshold
EDGE_MIN_POR_DEPORTE = {
    "futbol": 0.06, "mundial": 0.06, "champions": 0.06,
    "basquet": 0.05, "mlb": 0.07,
}
PROB_MIN_POR_DEPORTE = {
    "futbol": 0.57, "mundial": 0.57, "champions": 0.57,
    "basquet": 0.55, "mlb": 0.58,
}

def asignar_semaforo(edge: float) -> str:
    if edge >= 0.08:
        return "🟢"
    elif edge >= 0.04:
        return "🟡"
    else:
        return "🔴"

def _make_pick(deporte, liga, equipo, tipo, cuota, prob, bk) -> Optional[PickOutput]:
    if not (CUOTA_MIN <= cuota <= CUOTA_MAX):
        return None
    edge = calcular_edge(prob, cuota)
    return PickOutput(
        deporte=deporte,
        liga=liga,
        equipo=equipo,
        tipo_apuesta=tipo,
        cuota=cuota,
        prob_modelo=round(prob, 4),
        valor_esperado=round(calcular_ev(prob, cuota), 4),
        edge=round(edge, 4),
        semaforo=asignar_semaforo(edge),
        unidades=0.0,
        bookmaker_ref=bk.capitalize(),
    )

def _mejores_picks_evento(evento, deporte) -> List[PickOutput]:
    """Returns best H2H pick + best total pick separately so both compete globally."""
    mejores = extraer_mejores_cuotas(evento)
    h2h = mejores["h2h"]
    totals = mejores["totals"]
    home = evento.get("home_team", "")
    away = evento.get("away_team", "")
    liga = evento.get("_liga_nombre", deporte.upper())
    partido = f"{home} vs {away}"
    h2h_candidatos: List[PickOutput] = []
    total_candidatos: List[PickOutput] = []

    cuota_h = h2h.get(home)
    cuota_a = h2h.get(away)
    cuota_d = h2h.get("Draw")

    if cuota_h and cuota_a:
        cuota_hv, bk_h = cuota_h
        cuota_av, bk_a = cuota_a
        cuota_dv = cuota_d[0] if cuota_d else None

        pred = predecir(home, away, deporte)
        if pred:
            prob_home = pred["home"]
            prob_away = pred["away"]
            prob_draw = pred.get("draw", 0)
        else:
            probs = prob_implicita_sin_margen(cuota_hv, cuota_av, cuota_dv)
            prob_home, prob_away = probs["local"], probs["visitante"]
            prob_draw = 0

        draw_limit = 0.30 if deporte in ("futbol", "mundial", "champions") else 0
        if prob_draw <= draw_limit:
            p = _make_pick(deporte, liga, partido, f"Gana {home}", cuota_hv, prob_home, bk_h)
            if p:
                h2h_candidatos.append(p)
            p = _make_pick(deporte, liga, partido, f"Gana {away}", cuota_av, prob_away, bk_a)
            if p:
                h2h_candidatos.append(p)

    if deporte in DEPORTES_CON_TOTALS:
        puntos_vistos = set()
        for label, (cuota_t, bk_t) in totals.items():
            parts = label.split(" ", 1)
            if len(parts) != 2:
                continue
            direction, punto = parts
            if punto in puntos_vistos:
                continue
            over_label = f"Over {punto}"
            under_label = f"Under {punto}"
            cuota_over = totals.get(over_label)
            cuota_under = totals.get(under_label)
            if not cuota_over or not cuota_under:
                continue
            # Skip MLB totals above the volatile threshold
            try:
                if deporte == "mlb" and float(punto) > MLB_TOTAL_MAX:
                    puntos_vistos.add(punto)
                    continue
            except (ValueError, TypeError):
                pass
            cuota_ov, bk_ov = cuota_over
            cuota_uv, bk_uv = cuota_under
            try:
                pred_t = predecir_total(home, away, deporte, float(punto))
            except (ValueError, TypeError):
                pred_t = None
            if pred_t:
                prob_over, prob_under = pred_t["over"], pred_t["under"]
            else:
                probs_t = prob_implicita_sin_margen(cuota_ov, cuota_uv)
                prob_over, prob_under = probs_t["local"], probs_t["visitante"]

            p_over = _make_pick(deporte, liga, partido, f"Over {punto}", cuota_ov, prob_over, bk_ov)
            p_under = _make_pick(deporte, liga, partido, f"Under {punto}", cuota_uv, prob_under, bk_uv)
            if p_over:
                total_candidatos.append(p_over)
            if p_under:
                total_candidatos.append(p_under)
            puntos_vistos.add(punto)

    result = []
    if h2h_candidatos:
        result.append(max(h2h_candidatos, key=lambda p: p.edge))
    if total_candidatos:
        result.append(max(total_candidatos, key=lambda p: p.edge))
    return result

def generar_picks_diarios() -> List[PickOutput]:
    """Selecciona los 4 mejores picks del día cruzando todos los deportes disponibles."""
    estado = cargar_estado()
    hoy_utc = obtener_fecha_utc_real()  # una sola llamada para todos los deportes
    todos_candidatos: List[PickOutput] = []

    def _fetch_deporte(deporte: str) -> List[PickOutput]:
        eventos = obtener_cuotas(deporte, hoy_utc=hoy_utc)
        return [p for e in eventos for p in _mejores_picks_evento(e, deporte)]

    with ThreadPoolExecutor(max_workers=len(SPORTS_ODDSAPI)) as pool:
        futures = {pool.submit(_fetch_deporte, d): d for d in SPORTS_ODDSAPI}
        for future in as_completed(futures):
            try:
                todos_candidatos.extend(future.result())
            except Exception as exc:
                print(f"[picks_diarios] error en {futures[future]}: {exc}")

    todos_candidatos.sort(key=lambda p: p.edge, reverse=True)

    # Deduplicate: max one pick per game (equipo field = "Home vs Away")
    partidos_vistos: set = set()
    candidatos_unicos: List[PickOutput] = []
    for p in todos_candidatos:
        partido = p.equipo if " vs " in p.equipo else p.equipo
        if partido not in partidos_vistos:
            partidos_vistos.add(partido)
            candidatos_unicos.append(p)
    todos_candidatos = candidatos_unicos

    validos = [
        p for p in todos_candidatos
        if p.edge >= EDGE_MIN_POR_DEPORTE.get(p.deporte, EDGE_MIN)
        and p.prob_modelo >= PROB_MIN_POR_DEPORTE.get(p.deporte, PROB_MIN)
    ]
    fallbacks = [p for p in todos_candidatos if p not in validos]

    seleccionados: List[PickOutput] = []
    exposicion = 0.0

    for pick in validos:
        if len(seleccionados) >= PICKS_DIARIOS or exposicion >= EXPOSICION_MAX:
            break
        u = calcular_unidades(pick.edge, estado)
        if u > 0 and (exposicion + u) <= EXPOSICION_MAX:
            pick.unidades = u
            seleccionados.append(pick)
            exposicion += u

    for pick in fallbacks:
        if len(seleccionados) >= PICKS_DIARIOS:
            break
        pick.unidades = 0.5
        pick.semaforo = "🟡"
        seleccionados.append(pick)

    return seleccionados


def generar_picks(deporte: str) -> List[PickOutput]:
    estado = cargar_estado()
    eventos = obtener_cuotas(deporte)

    candidatos = [p for e in eventos for p in _mejores_picks_evento(e, deporte)]
    candidatos.sort(key=lambda p: p.edge, reverse=True)

    validos = [p for p in candidatos if p.edge >= EDGE_MIN and p.prob_modelo >= PROB_MIN]
    fallbacks = [p for p in candidatos if p not in validos]

    seleccionados: List[PickOutput] = []
    exposicion = 0.0

    for pick in validos:
        if len(seleccionados) >= MAX_PICKS or exposicion >= EXPOSICION_MAX:
            break
        u = calcular_unidades(pick.edge, estado)
        if u > 0 and (exposicion + u) <= EXPOSICION_MAX:
            pick.unidades = u
            seleccionados.append(pick)
            exposicion += u

    for pick in fallbacks:
        if len(seleccionados) >= MIN_PICKS:
            break
        pick.unidades = 0.5
        pick.semaforo = "🟡"
        seleccionados.append(pick)

    return seleccionados
