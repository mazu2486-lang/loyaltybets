import os
import asyncio
from telegram import Bot
from telegram.error import TelegramError
from models import PickOutput, Combinada, EstadoBanca
from typing import List, Optional

TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def _icono_deporte(deporte: str) -> str:
    return {"futbol":"⚽","basquet":"🏀","mlb":"⚾","tenis":"🎾"}.get(deporte, "🎯")

def _get_liga(deporte: str) -> str:
    return {"futbol":"Premier League","basquet":"NBA","tenis":"ATP","mlb":"MLB"}.get(deporte, deporte.upper())

def _texto_modo(estado: EstadoBanca) -> str:
    if estado.modo == "defensa":
        return "⚠️ _Modo Defensa activo — stakes reducidos_\n\n"
    elif estado.modo == "critico":
        return "🛑 _Modo Crítico — stakes mínimos_\n\n"
    return ""

def formatear_pick(pick: PickOutput, numero: int) -> str:
    icono = _icono_deporte(pick.deporte)
    return (
        f"{pick.semaforo} *PICK #{numero} — {pick.liga}*\n"
        f"{icono} {pick.equipo}\n"
        f"📌 {pick.tipo_apuesta}\n"
        f"💰 Cuota: *{pick.cuota}*\n"
        f"📊 Unidades: *{pick.unidades}u*\n"
        f"🏦 Bookmaker: {pick.bookmaker_ref}\n"
    )

def formatear_combinada(combinada: Combinada) -> str:
    equipos = " + ".join(p.equipo for p in combinada.picks)
    return (
        f"🔥 *COMBINADA DEL DÍA*\n"
        f"─────────────────────\n"
        f"📋 {equipos}\n"
        f"💰 Cuota combinada: *{combinada.cuota_combinada}*\n"
        f"📊 Unidades: *{combinada.unidades}u*\n"
        f"🏦 Bookmaker: {combinada.bookmaker_ref}\n"
        f"─────────────────────\n"
        f"⚠️ _Apuesta responsable. Combinadas son alto riesgo._"
    )

def formatear_resumen_semanal(picks_totales, picks_ganados, unidades_resultado, racha) -> str:
    roi = round((unidades_resultado / max(picks_totales, 1)) * 100, 1)
    emoji = "📈" if unidades_resultado >= 0 else "📉"
    return (
        f"📅 *RESUMEN SEMANAL — LoyaltyBet*\n"
        f"══════════════════════\n"
        f"✅ Picks ganados: {picks_ganados}/{picks_totales}\n"
        f"% Acierto: *{round(picks_ganados/max(picks_totales,1)*100,1)}%*\n"
        f"{emoji} Unidades: *{'+' if unidades_resultado >= 0 else ''}{unidades_resultado}u*\n"
        f"📊 ROI aprox: *{'+' if roi >= 0 else ''}{roi}%*\n"
        f"🔥 Racha actual: {racha} {'✅' if racha > 0 else '❌'}\n"
        f"══════════════════════\n"
        f"_Resultados reales. Sin trampa, sin filtros._"
    )

async def _enviar_async(texto: str):
    bot = Bot(token=TOKEN)
    async with bot:
        await bot.send_message(chat_id=CHAT_ID, text=texto, parse_mode="Markdown")

def enviar_mensaje(texto: str) -> bool:
    try:
        asyncio.run(_enviar_async(texto))
        return True
    except TelegramError as e:
        print(f"[Telegram] Error: {e}")
        return False
    except Exception as e:
        print(f"[Telegram] Error inesperado: {e}")
        return False

def enviar_picks_canal(
    picks: List[PickOutput],
    combinada: Optional[Combinada],
    deporte: str,
    estado: EstadoBanca,
):
    if not picks:
        enviar_mensaje(
            f"🔍 Sin picks válidos hoy para {_get_liga(deporte)}.\n"
            f"_El sistema no encontró valor suficiente. Mañana seguimos._"
        )
        return

    icono = _icono_deporte(deporte)
    enviar_mensaje(
        f"{icono} *PICKS DEL DÍA — {_get_liga(deporte).upper()}*\n"
        f"══════════════════════\n"
        f"{_texto_modo(estado)}"
        f"📋 {len(picks)} pick{'s' if len(picks) != 1 else ''} seleccionado{'s' if len(picks) != 1 else ''} hoy\n"
        f"══════════════════════"
    )

    for i, pick in enumerate(picks, 1):
        enviar_mensaje(formatear_pick(pick, i))

    if combinada:
        enviar_mensaje(formatear_combinada(combinada))

    enviar_mensaje(
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ *Apuesta con responsabilidad.*\n"
        "_Juega solo lo que puedas perder._\n"
        "🔞 Solo mayores de 18 años.\n"
        "━━━━━━━━━━━━━━━━━━━━━━"
    )

def enviar_resumen_semanal(picks_totales, picks_ganados, unidades, racha):
    enviar_mensaje(formatear_resumen_semanal(picks_totales, picks_ganados, unidades, racha))
