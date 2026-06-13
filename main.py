from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from typing import Literal
from models import EstadoBanca
from pick_engine import generar_picks, generar_picks_diarios
from combinada import armar_combinadas
from bankroll import cargar_estado, actualizar_resultado, reset_estado
from telegram_bot import enviar_picks_canal, enviar_picks_diarios_canal, enviar_resumen_semanal
from daily_tracker import ya_se_enviaron_hoy, marcar_enviados, resetear
from picks_tracker import guardar_picks_dia, get_stats
from results_checker import verificar_picks_fecha
from data_fetcher import obtener_fecha_utc_real

app = FastAPI(title="LoyaltyBet Pick Engine", version="3.0.0")

Deporte = Literal["futbol", "mundial", "champions", "basquet", "mlb", "tenis"]


@app.get("/health")
def health():
    estado = cargar_estado()
    return {"status": "ok", "bankroll_mode": estado.modo, "stats": get_stats()}


# ── Picks per sport (manual) ──────────────────────────────────────────────────

@app.get("/picks/{deporte}/preview")
def preview_picks(deporte: Deporte):
    picks = generar_picks(deporte)
    return JSONResponse([p.dict() for p in picks])


@app.get("/picks/{deporte}/publicar")
def publicar_picks(deporte: Deporte):
    estado = cargar_estado()
    picks = generar_picks(deporte)
    combinadas = armar_combinadas(picks, estado)
    enviar_picks_canal(picks, combinadas, deporte, estado)
    return {
        "publicado": True,
        "picks_generados": len(picks),
        "combinadas": [c.dict() for c in combinadas],
        "modo_banca": estado.modo,
    }


# ── Daily picks (main flow) ───────────────────────────────────────────────────

@app.get("/picks/diarios")
def publicar_picks_diarios(forzar: bool = False):
    if not forzar and ya_se_enviaron_hoy():
        return {"publicado": False, "razon": "Ya se enviaron los picks de hoy"}

    estado = cargar_estado()
    picks = generar_picks_diarios()
    combinadas = armar_combinadas(picks, estado)
    stats = get_stats()
    enviar_picks_diarios_canal(picks, combinadas, estado, stats=stats)

    try:
        fecha = obtener_fecha_utc_real().isoformat()
        guardar_picks_dia(picks, fecha)
    except Exception as e:
        print(f"[main] Error guardando picks: {e}")

    marcar_enviados()
    return {
        "publicado": True,
        "picks_generados": len(picks),
        "combinadas": [c.dict() for c in combinadas],
        "modo_banca": estado.modo,
    }


@app.get("/cron/diario")
def cron_diario():
    if ya_se_enviaron_hoy():
        return {"accion": "omitida", "razon": "Ya enviados hoy"}

    estado = cargar_estado()
    picks = generar_picks_diarios()
    combinadas = armar_combinadas(picks, estado)
    stats = get_stats()
    enviar_picks_diarios_canal(picks, combinadas, estado, stats=stats)

    try:
        fecha = obtener_fecha_utc_real().isoformat()
        guardar_picks_dia(picks, fecha)
    except Exception as e:
        print(f"[main] Error guardando picks: {e}")

    marcar_enviados()
    return {
        "accion": "enviado",
        "picks_generados": len(picks),
        "modo_banca": estado.modo,
    }


# ── Results & stats ───────────────────────────────────────────────────────────

@app.get("/cron/semanal")
def cron_semanal():
    """Publica el resumen semanal automáticamente (llamar cada lunes)."""
    s = get_stats()
    if s["total"] == 0:
        return {"publicado": False, "razon": "Sin picks registrados aún"}
    enviar_resumen_semanal(s["total"], s["ganados"], s["unidades"], s["racha"])
    return {"publicado": True, "stats": s}


@app.get("/resultados/verificar")
def verificar_resultados(fecha: str = None):
    """Checks API-Sports for results of pending picks. Defaults to yesterday."""
    if not fecha:
        from datetime import date, timedelta
        try:
            hoy = obtener_fecha_utc_real()
        except Exception:
            hoy = date.today()
        fecha = (hoy - timedelta(days=1)).isoformat()
    return verificar_picks_fecha(fecha)


@app.get("/stats")
def estadisticas():
    return get_stats()


# ── Bankroll & admin ──────────────────────────────────────────────────────────

@app.post("/resultado")
def registrar_resultado(gano: bool):
    return actualizar_resultado(gano).dict()


@app.post("/bankroll/reset")
def reset_bankroll():
    return reset_estado().dict()


@app.post("/daily/reset")
def reset_daily():
    resetear()
    return {"reseteado": True}


@app.post("/resumen/semanal")
def publicar_resumen(
    picks_totales: int = Query(...),
    picks_ganados: int = Query(...),
    unidades_resultado: float = Query(...),
    racha: int = Query(...),
):
    enviar_resumen_semanal(picks_totales, picks_ganados, unidades_resultado, racha)
    return {"publicado": True}
