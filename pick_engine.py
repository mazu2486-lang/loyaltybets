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
CUOTA_MAX = 4.00
MLB_TOTAL_MAX = 10.5  # skip MLB totals above this line
# When using the FIFA ranking fallback, reject total picks where the market strongly
# disagrees (cuota > 2.10 means market implies < 48% chance — too far from our model)
CUOTA_TOTAL_MUNDIAL_MAX = 2.10
EDGE_MIN = 0.04
PROB_MIN = 0.54
PICKS_DIARIOS = 5
MIN_PICKS = 3
MAX_PICKS = 5
EXPOSICION_MAX = 14.0

# MLB totals disabled → H2H-only, Log5 is well-calibrated → lower bar than before
EDGE_MIN_POR_DEPORTE = {
    "mundial": 0.04, "mlb": 0.055,
}
PROB_MIN_POR_DEPORTE = {
    "mundial": 0.54, "mlb": 0.54,
}

def asignar_semaforo(edge: float) -> str:
    if edge >= 0.06:
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
            usar_h2h = True
        elif deporte == "mlb":
            usar_h2h = False  # MLB: sin fallback circular — estadísticas reales o nada
        else:
            # Fútbol: mercado 3 vías no puede generar edge verde falso
            probs = prob_implicita_sin_margen(cuota_hv, cuota_av, cuota_dv)
            prob_home, prob_away = probs["local"], probs["visitante"]
            prob_draw = 0
            usar_h2h = True

        if usar_h2h:
            # MLB home underdog: historically ~54% win rate vs ~43-48% implied by odds
            # Boost is strongest in the +105-+140 range (cuota 2.05-2.40)
            if deporte == "mlb" and cuota_hv > 2.00:
                if cuota_hv <= 2.40:   # +105 to +140: sharpest edge zone
                    prob_home = min(prob_home * 1.05, 0.95)
                elif cuota_hv <= 2.80:  # +140 to +180: moderate edge
                    prob_home = min(prob_home * 1.03, 0.95)
                # Beyond +180 talent gap outweighs home field advantage

            draw_limit = 0.30 if deporte == "mundial" else 0
            if prob_draw <= draw_limit:
                p = _make_pick(deporte, liga, partido, f"Gana {home}", cuota_hv, prob_home, bk_h)
                if p:
                    h2h_candidatos.append(p)
                p = _make_pick(deporte, liga, partido, f"Gana {away}", cuota_av, prob_away, bk_a)
                if p:
                    h2h_candidatos.append(p)

            # Draw pick — only for football; edge filter handles quality
            if cuota_d and deporte == "mundial" and prob_draw > 0:
                cuota_dv, bk_d = cuota_d
                p = _make_pick(deporte, liga, partido, "Empate", cuota_dv, prob_draw, bk_d)
                if p:
                    h2h_candidatos.append(p)

    # Mundial totals off: FIFA ranking model too weak to beat efficient market.
    # MLB totals on: ERA-corrected model competes when pitcher data is available.
    if deporte in DEPORTES_CON_TOTALS and deporte != "mundial":
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
            if not pred_t:
                puntos_vistos.add(punto)
                continue
            # MLB: only generate total picks when we have actual pitcher ERA data
            if deporte == "mlb" and not pred_t.get("has_pitcher_data", False):
                puntos_vistos.add(punto)
                continue
            prob_over, prob_under = pred_t["over"], pred_t["under"]

            p_over = _make_pick(deporte, liga, partido, f"Over {punto}", cuota_ov, prob_over, bk_ov)
            p_under = _make_pick(deporte, liga, partido, f"Under {punto}", cuota_uv, prob_under, bk_uv)
            # MLB totals: reject if market strongly disagrees (cuota > 2.20 = < 45% implied)
            if deporte == "mlb":
                if p_under and cuota_uv > 2.20:
                    p_under = None
                if p_over and cuota_ov > 2.20:
                    p_over = None
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

    # Deduplicate: max 1 H2H + max 1 Total per game — both types compete independently
    vistos: set = set()
    candidatos_unicos: List[PickOutput] = []
    for p in todos_candidatos:
        partido = p.equipo if " vs " in p.equipo else p.equipo
        es_total = "Over" in p.tipo_apuesta or "Under" in p.tipo_apuesta
        clave = (partido, "total" if es_total else "h2h")
        if clave not in vistos:
            vistos.add(clave)
            candidatos_unicos.append(p)
    todos_candidatos = candidatos_unicos

    def _edge_valido(p: PickOutput) -> bool:
        es_total = "Over" in p.tipo_apuesta or "Under" in p.tipo_apuesta
        # MLB totals: require strong edge since model only runs when pitcher data is available
        if es_total and p.deporte == "mlb":
            return p.edge >= 0.08
        return p.edge >= EDGE_MIN_POR_DEPORTE.get(p.deporte, EDGE_MIN)

    validos = [
        p for p in todos_candidatos
        if _edge_valido(p)
        and p.prob_modelo >= PROB_MIN_POR_DEPORTE.get(p.deporte, PROB_MIN)
    ]
    fallbacks = [p for p in todos_candidatos if p not in validos]

    seleccionados: List[PickOutput] = []
    partidos_usados: set = set()
    exposicion = 0.0

    for pick in validos:
        if len(seleccionados) >= PICKS_DIARIOS or exposicion >= EXPOSICION_MAX:
            break
        partido = pick.equipo
        if partido in partidos_usados:
            continue  # max 1 pick por partido
        u = calcular_unidades(pick.edge, estado)
        if u > 0 and (exposicion + u) <= EXPOSICION_MAX:
            pick.unidades = u
            seleccionados.append(pick)
            partidos_usados.add(partido)
            exposicion += u

    # Guarantee at least 1 Mundial pick when valid Mundial picks exist
    tiene_mundial = any(p.deporte == "mundial" for p in seleccionados)
    if not tiene_mundial:
        mejores_mundial = [p for p in validos if p.deporte == "mundial" and p.equipo not in partidos_usados]
        if not mejores_mundial:
            mejores_mundial = [p for p in fallbacks if p.deporte == "mundial" and p.equipo not in partidos_usados]
        if mejores_mundial:
            mejor_mundial = mejores_mundial[0]
            if len(seleccionados) >= PICKS_DIARIOS:
                mlb_picks = [p for p in seleccionados if p.deporte == "mlb"]
                if mlb_picks:
                    peor_mlb = min(mlb_picks, key=lambda p: p.edge)
                    seleccionados.remove(peor_mlb)
                    partidos_usados.discard(peor_mlb.equipo)
                    exposicion -= peor_mlb.unidades
            if len(seleccionados) < PICKS_DIARIOS:
                u = calcular_unidades(mejor_mundial.edge, estado)
                mejor_mundial.unidades = u if u > 0 else 0.5
                if mejor_mundial.edge < EDGE_MIN_POR_DEPORTE.get("mundial", EDGE_MIN):
                    mejor_mundial.semaforo = "🟡"
                seleccionados.append(mejor_mundial)
                partidos_usados.add(mejor_mundial.equipo)
                exposicion += mejor_mundial.unidades

    # Fill remaining slots with fallbacks (1 per game)
    for pick in fallbacks:
        if len(seleccionados) >= PICKS_DIARIOS:
            break
        if pick in seleccionados or pick.equipo in partidos_usados:
            continue
        pick.unidades = 0.5
        pick.semaforo = "🟡"
        seleccionados.append(pick)
        partidos_usados.add(pick.equipo)

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
