from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from typing import Literal
from models import EstadoBanca
from pick_engine import generar_picks, generar_picks_diarios
from combinada import armar_combinadas
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
    combinadas = armar_combinadas(picks, estado)
    enviar_picks_canal(picks, combinadas, deporte, estado)
    return {
        "publicado": True,
        "picks_generados": len(picks),
        "combinadas": [c.dict() for c in combinadas],
        "modo_banca": estado.modo,
    }


@app.get("/picks/diarios")
def publicar_picks_diarios(forzar: bool = False):
    if not forzar and ya_se_enviaron_hoy():
        return {"publicado": False, "razon": "Ya se enviaron los picks de hoy"}

    estado = cargar_estado()
    picks = generar_picks_diarios()
    combinadas = armar_combinadas(picks, estado)
    enviar_picks_diarios_canal(picks, combinadas, estado)
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
    enviar_picks_diarios_canal(picks, combinadas, estado)
    marcar_enviados()
    return {
        "accion": "enviado",
        "picks_generados": len(picks),
        "combinadas": [c.dict() for c in combinadas],
        "modo_banca": estado.modo,
    }


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
