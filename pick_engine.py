"""
pick_engine.py
Reglas:
- UN solo pick por partido (el de mayor edge entre h2h y totals)
- Para totals: solo el lado con mayor edge (Over OR Under, no ambos)
- Mínimo 4 picks garantizados con fallback 🟡
"""
from typing import List, Optional
from models import PickOutput, EstadoBanca
from bankroll import calcular_unidades, cargar_estado
from data_fetcher import (
    obtener_cuotas, extraer_mejores_cuotas,
    prob_implicita_sin_margen, calcular_ev, calcular_edge,
    obtener_pitchers_probables_hoy, score_pitcher,
    verificar_load_management_nba, DEPORTES_CON_TOTALS,
)

CUOTA_MIN      = 1.30
CUOTA_MAX      = 3.50
EDGE_MIN       = 0.04
PROB_MIN       = 0.54
MIN_PICKS      = 4
MAX_PICKS      = 7
EXPOSICION_MAX = 8.0

def asignar_semaforo(edge: float) -> str:
    if edge >= 0.08:   return "🟢"
    elif edge >= 0.04: return "🟡"
    else:              return "🔴"

def ajustar_prob_mlb(prob, ps_home, ps_away, es_local):
    ajuste = (ps_home - ps_away) * 0.07
    return min(0.85, max(0.15, prob + ajuste if es_local else prob - ajuste))

def ajustar_prob_nba(prob, load_rival):
    return min(0.85, prob + 0.04) if load_rival else prob

def _make_pick(deporte, liga, equipo, tipo, cuota, prob, bk) -> Optional[PickOutput]:
    if not (CUOTA_MIN <= cuota <= CUOTA_MAX):
        return None
    edge = calcular_edge(prob, cuota)
    return PickOutput(
        deporte=deporte, liga=liga, equipo=equipo, tipo_apuesta=tipo,
        cuota=cuota, prob_modelo=round(prob, 4),
        valor_esperado=round(calcular_ev(prob, cuota), 4),
        edge=round(edge, 4),
        semaforo=asignar_semaforo(edge),
        unidades=0.0,
        bookmaker_ref=_normalizar_bookmaker(bk),
    )

def _mejor_pick_evento(evento, deporte, pitchers) -> Optional[PickOutput]:
    """
    Evalúa un evento y retorna UN SOLO pick — el de mayor edge.
    Para totals solo considera el mejor lado (Over OR Under).
    """
    mejores = extraer_mejores_cuotas(evento)
    h2h    = mejores["h2h"]
    totals = mejores["totals"]
    home   = evento.get("home_team", "")
    away   = evento.get("away_team", "")
    liga   = evento.get("_liga_nombre", _get_liga(deporte))
    candidatos: List[PickOutput] = []

    # ── h2h: evaluar local y visitante ──────────────────────────────────────
    cuota_h = h2h.get(home)
    cuota_a = h2h.get(away)
    cuota_d = h2h.get("Draw")

    if cuota_h and cuota_a:
        cuota_hv, bk_h = cuota_h
        cuota_av, bk_a = cuota_a
        cuota_dv = cuota_d[0] if cuota_d else None
        probs = prob_implicita_sin_margen(cuota_hv, cuota_av, cuota_dv)
        prob_home, prob_away = probs["local"], probs["visitante"]

        if deporte == "mlb":
            for gid, data in pitchers.items():
                if home in (data.get("home_team") or ""):
                    ps_h = score_pitcher(data.get("home"))
                    ps_a = score_pitcher(data.get("away"))
                    prob_home = ajustar_prob_mlb(prob_home, ps_h, ps_a, True)
                    prob_away = ajustar_prob_mlb(prob_away, ps_h, ps_a, False)
                    break
        elif deporte == "basquet":
            prob_home = ajustar_prob_nba(prob_home, verificar_load_management_nba(away))
            prob_away = ajustar_prob_nba(prob_away, verificar_load_management_nba(home))

        # Nombre correcto: equipo local es local, visitante es visitante
        p = _make_pick(deporte, liga, home, "Victoria Local",     cuota_hv, prob_home, bk_h)
        if p: candidatos.append(p)
        p = _make_pick(deporte, liga, away, "Victoria Visitante", cuota_av, prob_away, bk_a)
        if p: candidatos.append(p)

    # ── totals: solo el mejor lado por línea de puntos ──────────────────────
    if deporte in DEPORTES_CON_TOTALS:
        # Agrupar por punto (ej. 7.5) y elegir solo Over o Under, el de mayor edge
        puntos_vistos = set()
        for label, (cuota_t, bk_t) in totals.items():
            parts = label.split(" ", 1)
            if len(parts) != 2:
                continue
            direction, punto = parts
            if punto in puntos_vistos:
                continue  # ya procesamos este punto
            
            over_label  = f"Over {punto}"
            under_label = f"Under {punto}"
            cuota_over  = totals.get(over_label)
            cuota_under = totals.get(under_label)

            if not cuota_over or not cuota_under:
                continue

            cuota_ov, bk_ov = cuota_over
            cuota_uv, bk_uv = cuota_under
            probs_t = prob_implicita_sin_margen(cuota_ov, cuota_uv)
            prob_over  = probs_t["local"]
            prob_under = probs_t["visitante"]

            partido = f"{home} vs {away}"
            p_over  = _make_pick(deporte, liga, partido, f"Over {punto}",  cuota_ov, prob_over,  bk_ov)
            p_under = _make_pick(deporte, liga, partido, f"Under {punto}", cuota_uv, prob_under, bk_uv)

            # Solo agregar el mejor de los dos
            mejor_total = None
            if p_over and p_under:
                mejor_total = p_over if p_over.edge >= p_under.edge else p_under
            elif p_over:
                mejor_total = p_over
            elif p_under:
                mejor_total = p_under

            if mejor_total:
                candidatos.append(mejor_total)
            puntos_vistos.add(punto)

    if not candidatos:
        return None

    # Retornar solo el pick de mayor edge del evento
    return max(candidatos, key=lambda p: p.edge)


def generar_picks(deporte: str) -> List[PickOutput]:
    estado   = cargar_estado()
    eventos  = obtener_cuotas(deporte)
    pitchers = obtener_pitchers_probables_hoy() if deporte == "mlb" else {}

    candidatos = [_mejor_pick_evento(e, deporte, pitchers) for e in eventos]
    candidatos = [p for p in candidatos if p is not None]
    candidatos.sort(key=lambda p: p.edge, reverse=True)

    validos   = [p for p in candidatos if p.edge >= EDGE_MIN and p.prob_modelo >= PROB_MIN]
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


def _get_liga(deporte: str) -> str:
    return {"basquet": "NBA", "tenis": "ATP", "mlb": "MLB"}.get(deporte, deporte.upper())

def _normalizar_bookmaker(key: str) -> str:
    m = {
        "betsson":"Betsson","betano":"Betano","coolbet":"Coolbet","unibet":"Unibet",
        "betfair_ex_eu":"Betfair","williamhill":"William Hill","draftkings":"DraftKings",
        "fanduel":"FanDuel","gtbets":"GTbets","onexbet":"1xBet","pinnacle":"Pinnacle",
        "betrivers":"BetRivers","bovada":"Bovada","mybookieag":"MyBookie",
    }
    return m.get(key.lower(), key.capitalize())
