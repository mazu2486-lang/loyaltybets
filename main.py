from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from typing import Literal, Optional
from models import EstadoBanca
from pick_engine import generar_picks, generar_picks_diarios
from combinada import armar_combinada
from bankroll import cargar_estado, actualizar_resultado, reset_estado
from telegram_bot import enviar_picks_canal, enviar_picks_diarios_canal, enviar_resumen_semanal
from daily_tracker import ya_se_enviaron_hoy, marcar_enviados, resetear

app = FastAPI(title="LoyaltyBet Pick Engine", version="2.0.0")

Deporte = Literal["futbol", "basquet", "mlb", "tenis"]

@app.get("/health")
def health():
    estado = cargar_estado()
    return {"status": "ok", "bankroll_mode": estado.modo}

@app.get("/picks/{deporte}/preview")
def preview_picks(deporte: Deporte):
    picks = generar_picks(deporte)
    return JSONResponse([p.dict() for p in picks])

@app.get("/picks/{deporte}/publicar")
def publicar_picks(deporte: Deporte):
    estado = cargar_estado()
    picks = generar_picks(deporte)
    combinada = armar_combinada(picks, estado)
    enviar_picks_canal(picks, combinada, deporte, estado)
    return {
        "publicado": True,
        "picks_generados": len(picks),
        "combinada": combinada.dict() if combinada else None,
        "modo_banca": estado.modo,
    }

@app.post("/resultado")
def registrar_resultado(gano: bool):
    nuevo_estado = actualizar_resultado(gano)
    return nuevo_estado.dict()

@app.post("/bankroll/reset")
def reset_bankroll():
    return reset_estado().dict()


@app.get("/picks/diarios")
def publicar_picks_diarios(forzar: bool = False):
    """Genera y publica los 4 mejores picks del día cruzando todos los deportes."""
    if not forzar and ya_se_enviaron_hoy():
        return {"publicado": False, "razon": "Ya se enviaron los picks de hoy"}

    estado = cargar_estado()
    picks = generar_picks_diarios()
    combinada = armar_combinada(picks, estado)
    enviar_picks_diarios_canal(picks, combinada, estado)
    marcar_enviados()
    return {
        "publicado": True,
        "picks_generados": len(picks),
        "combinada": combinada.dict() if combinada else None,
        "modo_banca": estado.modo,
    }


@app.get("/cron/diario")
def cron_diario():
    """Endpoint para cron externo — envía los picks del día si aún no se enviaron."""
    if ya_se_enviaron_hoy():
        return {"accion": "omitida", "razon": "Ya enviados hoy"}

    estado = cargar_estado()
    picks = generar_picks_diarios()
    combinada = armar_combinada(picks, estado)
    enviar_picks_diarios_canal(picks, combinada, estado)
    marcar_enviados()
    return {
        "accion": "enviado",
        "picks_generados": len(picks),
        "modo_banca": estado.modo,
    }


@app.post("/daily/reset")
def reset_daily():
    """Resetea el estado diario para permitir un nuevo envío manual."""
    resetear()
    return {"reseteado": True}

@app.post("/resumen/semanal")
def publicar_resumen(
    picks_totales: int = Query(..., description="Número total de picks"),
    picks_ganados: int = Query(..., description="Número de picks ganados"),
    unidades_resultado: float = Query(..., description="Resultado en unidades"),
    racha: int = Query(..., description="Racha actual"),
):
    enviar_resumen_semanal(picks_totales, picks_ganados, unidades_resultado, racha)
    return {"publicado": True}
