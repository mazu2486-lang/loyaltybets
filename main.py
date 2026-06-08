from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from typing import Literal, Optional
from models import EstadoBanca
from pick_engine import generar_picks
from combinada import armar_combinada
from bankroll import cargar_estado, actualizar_resultado, reset_estado
from telegram_bot import enviar_picks_canal, enviar_resumen_semanal

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

@app.post("/resumen/semanal")
def publicar_resumen(
    picks_totales: int = Query(..., description="Número total de picks"),
    picks_ganados: int = Query(..., description="Número de picks ganados"),
    unidades_resultado: float = Query(..., description="Resultado en unidades"),
    racha: int = Query(..., description="Racha actual"),
):
    enviar_resumen_semanal(picks_totales, picks_ganados, unidades_resultado, racha)
    return {"publicado": True}
