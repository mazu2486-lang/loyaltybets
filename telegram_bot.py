"""
telegram_bot.py
Formato de mensajes para canal público LoyaltyBet.
Reglas de canal:
- Sin jerga técnica (no EV, no edge, no prob_modelo)
- Semáforo visible
- Máximo 7 picks + 1 combinada
- Resumen dominical
"""
import os
from telegram import Bot
from telegram.error import TelegramError
from models import PickOutput, Combinada, EstadoBanca
from typing import List, Optional

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")  # "@TuCanal" o chat_id numérico

_bot: Optional[Bot] = None

def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=TOKEN)
    return _bot

# ─── FORMATEO DE MENSAJES ─────────────────────────────────────────────────────

def _icono_deporte(deporte: str) -> str:
    iconos = {
        "futbol": "⚽",
        "basquet": "🏀",
        "mlb": "⚾",
        "tenis": "🎾",
    }
    return iconos.get(deporte, "🎯")

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
        f"📋 Selección: {equipos}\n"
        f"💰 Cuota combinada: *{combinada.cuota_combinada}*\n"
        f"📊 Unidades: *{combinada.unidades}u*\n"
        f"🏦 Bookmaker: {combinada.bookmaker_ref}\n"
        f"─────────────────────\n"
        f"⚠️ _Apuesta responsable. Combinadas son alto riesgo._"
    )

def formatear_resumen_semanal(
    picks_totales: int,
    picks_ganados: int,
    unidades_resultado: float,
    racha: int,
) -> str:
    roi = round((unidades_resultado / max(picks_totales, 1)) * 100, 1)
    emoji_resultado = "📈" if unidades_resultado >= 0 else "📉"
    return (
        f"📅 *RESUMEN SEMANAL — LoyaltyBet*\n"
        f"══════════════════════\n"
        f"✅ Picks ganados: {picks_ganados}/{picks_totales}\n"
        f"% Acierto: *{round(picks_ganados/max(picks_totales,1)*100,1)}%*\n"
        f"{emoji_resultado} Unidades: *{'+' if unidades_resultado >= 0 else ''}{unidades_resultado}u*\n"
        f"📊 ROI aprox: *{'+' if roi >= 0 else ''}{roi}%*\n"
        f"🔥 Racha actual: {racha} {'✅' if racha > 0 else '❌'}\n"
        f"══════════════════════\n"
        f"_Resultados reales. Sin trampa, sin filtros._"
    )

def formatear_header_diario(deporte: str, total_picks: int, estado: EstadoBanca) -> str:
    icono = _icono_deporte(deporte)
    return (
        f"{icono} *PICKS DEL DÍA — {_get_liga(deporte).upper()}*\n"
        f"══════════════════════\n"
        f"{_texto_modo(estado)}"
        f"📋 {total_picks} pick{'s' if total_picks != 1 else ''} seleccionado{'s' if total_picks != 1 else ''} hoy\n"
        f"══════════════════════\n"
    )

# ─── ENVÍO ───────────────────────────────────────────────────────────────────

def enviar_mensaje(texto: str, parse_mode: str = "Markdown") -> bool:
    try:
        get_bot().send_message(chat_id=CHAT_ID, text=texto, parse_mode=parse_mode)
        return True
    except TelegramError as e:
        print(f"[Telegram] Error al enviar: {e}")
        return False

def enviar_picks_canal(
    picks: List[PickOutput],
    combinada: Optional[Combinada],
    deporte: str,
    estado: EstadoBanca,
):
    """Flujo completo de publicación diaria en el canal."""
    if not picks:
        enviar_mensaje(
            f"🔍 Sin picks válidos hoy para {_get_liga(deporte)}.\n"
            f"_El sistema no encontró valor suficiente. Mañana seguimos._"
        )
        return

    # Header
    enviar_mensaje(formatear_header_diario(deporte, len(picks), estado))

    # Picks individuales
    for i, pick in enumerate(picks, 1):
        enviar_mensaje(formatear_pick(pick, i))

    # Combinada
    if combinada:
        enviar_mensaje(formatear_combinada(combinada))

    # Footer
    enviar_mensaje(
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ *Apuesta con responsabilidad.*\n"
        "_Juega solo lo que puedas perder._\n"
        "🔞 Solo mayores de 18 años.\n"
        "━━━━━━━━━━━━━━━━━━━━━━"
    )

def enviar_resumen_semanal(picks_totales, picks_ganados, unidades, racha):
    texto = formatear_resumen_semanal(picks_totales, picks_ganados, unidades, racha)
    enviar_mensaje(texto)

# ─── Helper ──────────────────────────────────────────────────────────────────

def _get_liga(deporte: str) -> str:
    ligas = {"futbol": "Premier League", "basquet": "NBA", "tenis": "ATP", "mlb": "MLB"}
    return ligas.get(deporte, deporte.upper())
