"""
pick_engine.py
Motor central de selección de picks.

Criterio principal: EV positivo + edge >= 4% + prob >= 54%
Fallback garantizado: si no llegan a 4 picks, completa con los mejores
disponibles del día aunque no pasen el umbral (marcados 🟡).

Mercados evaluados:
- h2h (todos los deportes)
- totals / Over-Under (futbol, basquet, mlb — NO tenis)

Filtros: cuota 1.30–3.50, máximo 7 picks, exposición máx 8 unidades.
"""
from typing import List, Tuple, Optional
from models import PickOutput, EstadoBanca
from bankroll import calcular_unidades, cargar_estado
from data_fetcher import (
    obtener_cuotas,
    extraer_mejores_cuotas,
    prob_implicita_sin_margen,
    calcular_ev,
    calcular_edge,
    obtener_pitchers_probables_hoy,
    score_pitcher,
    verificar_load_management_nba,
    DEPORTES_CON_TOTALS,
)

CUOTA_MIN = 1.30
CUOTA_MAX = 3.50
EDGE_MIN  = 0.04
PROB_MIN  = 0.54
MIN_PICKS_DIA    = 4
MAX_PICKS_DIA    = 7
EXPOSICION_MAX   = 8.0

# ─── SEMÁFORO ────────────────────────────────────────────────────────────────

def asignar_semaforo(edge: float) -> str:
    if edge >= 0.08:
        return "🟢"
    elif edge >= 0.04:
        return "🟡"
    else:
        return "🔴"   # solo en fallback

# ─── AJUSTES POR DEPORTE ─────────────────────────────────────────────────────

def ajustar_prob_mlb(prob_base: float, ps_home: float, ps_away: float, es_local: bool) -> float:
    diferencial = ps_home - ps_away
    ajuste = diferencial * 0.07
    return min(0.85, max(0.15, prob_base + ajuste if es_local else prob_base - ajuste))

def ajustar_prob_nba(prob_base: float, load_rival: bool) -> float:
    return min(0.85, prob_base + 0.04) if load_rival else prob_base

# ─── CANDIDATO INTERNO ───────────────────────────────────────────────────────

def _build_pick(
    deporte: str,
    equipo_label: str,
    tipo_apuesta: str,
    cuota: float,
    prob_modelo: float,
    bookmaker: str,
) -> Optional[PickOutput]:
    """Construye un PickOutput si la cuota está en rango. Sin filtro de edge."""
    if not (CUOTA_MIN <= cuota <= CUOTA_MAX):
        return None
    ev    = calcular_ev(prob_modelo, cuota)
    edge  = calcular_edge(prob_modelo, cuota)
    return PickOutput(
        deporte=deporte,
        liga=_get_liga(deporte),
        equipo=equipo_label,
        tipo_apuesta=tipo_apuesta,
        cuota=cuota,
        prob_modelo=round(prob_modelo, 4),
        valor_esperado=round(ev, 4),
        edge=round(edge, 4),
        semaforo=asignar_semaforo(edge),
        unidades=0.0,   # se asigna después
        bookmaker_ref=_normalizar_bookmaker(bookmaker),
    )

def _cumple_umbral(pick: PickOutput) -> bool:
    return pick.edge >= EDGE_MIN and pick.prob_modelo >= PROB_MIN

# ─── EVALUADOR DE UN EVENTO ──────────────────────────────────────────────────

def _evaluar_evento(
    evento: dict,
    deporte: str,
    pitchers_hoy: dict,
) -> List[PickOutput]:
    """
    Evalúa h2h + totals de un evento y devuelve todos los candidatos
    (sin filtrar por umbral todavía — eso lo hace el generador principal).
    """
    mejores = extraer_mejores_cuotas(evento)
    h2h    = mejores["h2h"]
    totals = mejores["totals"]

    home = evento.get("home_team", "")
    away = evento.get("away_team", "")
    candidatos: List[PickOutput] = []

    # ── Probabilidades h2h ──────────────────────────────────────────────────
    cuota_h = h2h.get(home)
    cuota_a = h2h.get(away)
    cuota_d = h2h.get("Draw")

    if cuota_h and cuota_a:
        cuota_hv, bk_h = cuota_h
        cuota_av, bk_a = cuota_a
        cuota_dv = cuota_d[0] if cuota_d else None

        probs = prob_implicita_sin_margen(cuota_hv, cuota_av, cuota_dv)
        prob_home = probs["local"]
        prob_away = probs["visitante"]

        # Ajustes por deporte
        if deporte == "mlb":
            for gid, data in pitchers_hoy.items():
                if home in (data.get("home_team") or ""):
                    ps_h = score_pitcher(data.get("home"))
                    ps_a = score_pitcher(data.get("away"))
                    prob_home = ajustar_prob_mlb(prob_home, ps_h, ps_a, True)
                    prob_away = ajustar_prob_mlb(prob_away, ps_h, ps_a, False)
                    break
        elif deporte == "basquet":
            prob_home = ajustar_prob_nba(prob_home, verificar_load_management_nba(away))
            prob_away = ajustar_prob_nba(prob_away, verificar_load_management_nba(home))

        p = _build_pick(deporte, home, "Victoria Local", cuota_hv, prob_home, bk_h)
        if p: candidatos.append(p)

        p = _build_pick(deporte, away, "Victoria Visitante", cuota_av, prob_away, bk_a)
        if p: candidatos.append(p)

    # ── Totals (Over/Under) — solo deportes habilitados ─────────────────────
    if deporte in DEPORTES_CON_TOTALS:
        for label, (cuota_t, bk_t) in totals.items():
            # prob implícita del total (mercado binario: Over vs Under complementario)
            # buscamos el par complementario
            direction, punto = label.split(" ", 1)
            opuesto = f"{'Under' if direction == 'Over' else 'Over'} {punto}"
            cuota_op_data = totals.get(opuesto)

            if cuota_op_data:
                cuota_op, _ = cuota_op_data
                probs_t = prob_implicita_sin_margen(cuota_t, cuota_op)
                prob_t  = probs_t["local"]   # prob del outcome evaluado
            else:
                # Si no hay el par, usar prob implícita cruda (menos preciso)
                prob_t = 1 / cuota_t

            equipo_label = f"{home} vs {away}"
            p = _build_pick(deporte, equipo_label, label, cuota_t, prob_t, bk_t)
            if p: candidatos.append(p)

    return candidatos

# ─── GENERADOR PRINCIPAL ─────────────────────────────────────────────────────

def generar_picks(deporte: str) -> List[PickOutput]:
    estado     = cargar_estado()
    eventos    = obtener_cuotas(deporte)
    pitchers   = obtener_pitchers_probables_hoy() if deporte == "mlb" else {}

    todos_candidatos: List[PickOutput] = []
    for evento in eventos:
        todos_candidatos.extend(_evaluar_evento(evento, deporte, pitchers))

    # Ordenar por edge desc
    todos_candidatos.sort(key=lambda p: p.edge, reverse=True)

    # ── Selección principal: picks que cumplen umbral ──
    picks_validos  = [p for p in todos_candidatos if _cumple_umbral(p)]
    picks_fallback = [p for p in todos_candidatos if not _cumple_umbral(p)]

    seleccionados: List[PickOutput] = []
    exposicion = 0.0

    for pick in picks_validos:
        if len(seleccionados) >= MAX_PICKS_DIA or exposicion >= EXPOSICION_MAX:
            break
        u = calcular_unidades(pick.edge, estado)
        if u > 0 and (exposicion + u) <= EXPOSICION_MAX:
            pick.unidades = u
            seleccionados.append(pick)
            exposicion += u

    # ── Fallback: completar hasta MIN_PICKS_DIA si faltan ──
    if len(seleccionados) < MIN_PICKS_DIA:
        for pick in picks_fallback:
            if len(seleccionados) >= MIN_PICKS_DIA:
                break
            if exposicion >= EXPOSICION_MAX:
                break
            # En fallback: 0.5 unidades fijas, semáforo forzado a 🟡
            pick.unidades  = 0.5
            pick.semaforo  = "🟡"
            seleccionados.append(pick)
            exposicion += 0.5

    return seleccionados

# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_liga(deporte: str) -> str:
    return {"futbol": "Premier League", "basquet": "NBA", "tenis": "ATP", "mlb": "MLB"}.get(deporte, deporte.upper())

def _normalizar_bookmaker(key: str) -> str:
    m = {"betsson":"Betsson","betano":"Betano","coolbet":"Coolbet",
         "unibet":"Unibet","betfair_ex_eu":"Betfair","1xbet":"1xBet","pinnacle":"Pinnacle"}
    return m.get(key.lower(), key.capitalize())
