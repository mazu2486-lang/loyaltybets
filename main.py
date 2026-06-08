"""
main.py
FastAPI app — LoyaltyBet pick engine
Endpoints:
  GET  /picks/{deporte}            → genera y publica picks en Telegram
  GET  /picks/{deporte}/preview    → genera picks SIN publicar (para revisión)
  POST /resultado                  → registra resultado para actualizar bankroll
  POST /bankroll/reset             → reset manual de estado de banca
  GET  /resumen/semanal            → publica resumen semanal (llamar los domingos)
  GET  /health                     → health check
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Literal, List, Optional

from models import PickOutput, Combinada, EstadoBanca
from pick_engine import generar_picks
from combinada import armar_combinada
from bankroll import cargar_estado, actualizar_resultado, reset_estado
from telegram_bot import enviar_picks_canal, enviar_resumen_semanal

app = FastAPI(title="LoyaltyBet Pick Engine", version="2.0.0")

Deporte = Literal["futbol", "basquet", "mlb", "tenis"]

# ─── MODELOS REQUEST ─────────────────────────────────────────────────────────

class ResultadoRequest(BaseModel):
    gano: bool

class ResumenRequest(BaseModel):
    picks_totales: int
    picks_ganados: int
    unidades_resultado: float  # positivo = ganancia, negativo = pérdida
    racha: int                 # positivo = racha ganadora, negativo = perdedora

# ─── ENDPOINTS ───────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    estado = cargar_estado()
    return {"status": "ok", "bankroll_mode": estado.modo}

@app.get("/picks/{deporte}/preview", response_model=List[PickOutput])
def preview_picks(deporte: Deporte):
    """
    Genera picks sin publicar. Útil para revisar antes de publicar.
    """
    picks = generar_picks(deporte)
    return picks

@app.get("/picks/{deporte}", response_model=dict)
def publicar_picks(deporte: Deporte):
    """
    Genera picks y los publica en el canal de Telegram.
    Llamar una vez al día por deporte (preferiblemente via cron/scheduler).
    """
    estado = cargar_estado()
    picks = generar_picks(deporte)
    combinada = armar_combinada(picks, estado)
    enviar_picks_canal(picks, combinada, deporte, estado)

    return {
        "publicado": True,
        "picks_generados": len(picks),
        "combinada": combinada.model_dump() if combinada else None,
        "modo_banca": estado.modo,
    }

@app.post("/resultado", response_model=EstadoBanca)
def registrar_resultado(body: ResultadoRequest):
    """
    Registrar resultado de un pick para actualizar el estado de banca.
    Llamar después de conocer el resultado de cada pick.
    """
    nuevo_estado = actualizar_resultado(body.gano)
    return nuevo_estado

@app.post("/bankroll/reset", response_model=EstadoBanca)
def reset_bankroll():
    """Reset manual del estado de banca a modo normal."""
    return reset_estado()

@app.post("/resumen/semanal")
def publicar_resumen(body: ResumenRequest):
    """
    Publica el resumen semanal en el canal.
    Programar para los domingos.
    """
    enviar_resumen_semanal(
        picks_totales=body.picks_totales,
        picks_ganados=body.picks_ganados,
        unidades=body.unidades_resultado,
        racha=body.racha,
    )
    return {"publicado": True}
