import os
import asyncio
from telegram import Bot
from telegram.error import TelegramError
from models import PickOutput, Combinada, EstadoBanca
from typing import List

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

_ICONO_DEPORTE = {"futbol": "⚽", "basquet": "🏀", "mlb": "⚾", "tenis": "🎾"}
_LIGA_NOMBRE   = {"futbol": "Premier League", "basquet": "NBA", "tenis": "ATP", "mlb": "MLB"}
_TIPO_LABEL    = {"express": "⚡ EXPRESS", "normal": "🔥 COMBINADA", "acumulada": "🎰 ACUMULADA"}

def _icono(deporte: str) -> str:
    return _ICONO_DEPORTE.get(deporte, "🎯")

def _liga(deporte: str) -> str:
    return _LIGA_NOMBRE.get(deporte, deporte.upper())

def _modo_aviso(estado: EstadoBanca) -> str:
    if estado.modo == "defensa":
        return "⚠️ _Modo Defensa — stakes reducidos_\n"
    if estado.modo == "critico":
        return "🛑 _Modo Crítico — stakes mínimos_\n"
    return ""


# ── Pick & combinada formatters ───────────────────────────────────────────────

def formatear_pick(pick: PickOutput, numero: int) -> str:
    icono = _icono(pick.deporte)
    if " vs " in pick.equipo:
        local, visitante = pick.equipo.split(" vs ", 1)
    else:
        local, visitante = pick.equipo, ""

    if "Over" in pick.tipo_apuesta or "Under" in pick.tipo_apuesta:
        apuesta = f"Total {pick.tipo_apuesta}"
    else:
        apuesta = f"Victoria {pick.tipo_apuesta}"

    ev_txt = f"+{pick.valor_esperado:.1%}" if pick.valor_esperado >= 0 else f"{pick.valor_esperado:.1%}"

    return (
        f"{pick.semaforo} *PICK #{numero}* — {pick.liga}\n"
        f"{icono} *{local}*{f' vs {visitante}' if visitante else ''}\n"
        f"📌 {apuesta}\n"
        f"💰 Cuota: *{pick.cuota}* · EV: _{ev_txt}_\n"
        f"📊 Stake: *{pick.unidades}u*\n"
    )


def formatear_combinada(combinada: Combinada) -> str:
    label = _TIPO_LABEL.get(combinada.tipo, "🔥 COMBINADA")
    lineas = [f"  • {p.equipo} @ {p.cuota}" for p in combinada.picks]
    return (
        f"*{label} DEL DÍA*\n"
        f"─────────────────────\n"
        + "\n".join(lineas) + "\n"
        f"─────────────────────\n"
        f"💰 Cuota combinada: *{combinada.cuota_combinada}*\n"
        f"📊 Stake: *{combinada.unidades}u*\n"
        f"_⚠️ Alto riesgo — apuesta responsable_"
    )


def _pie_aviso() -> str:
    return (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ *Apuesta con responsabilidad.*\n"
        "_Solo lo que puedas perder. +18._\n"
        "━━━━━━━━━━━━━━━━━━━━━━"
    )


# ── Channel sending functions ─────────────────────────────────────────────────

def enviar_picks_diarios_canal(
    picks: List[PickOutput],
    combinadas: List[Combinada],
    estado: EstadoBanca,
    stats: dict = None,
):
    if not picks:
        enviar_mensaje(
            "🔍 *Sin picks válidos hoy.*\n"
            "_El sistema no encontró valor suficiente. Mañana seguimos._"
        )
        return

    sem = {}
    for p in picks:
        sem[p.semaforo] = sem.get(p.semaforo, 0) + 1
    sem_txt = "  ".join(f"{k}×{v}" for k, v in sem.items() if v > 0)

    stats_linea = ""
    if stats and stats.get("total", 0) > 0:
        signo = "+" if stats["unidades"] >= 0 else ""
        stats_linea = (
            f"📈 _Histórico: {stats['win_pct']}% acierto · "
            f"{signo}{stats['unidades']}u · {stats['total']} picks_\n"
        )

    enviar_mensaje(
        f"🏆 *LOYALTYBETS — PICKS DEL DÍA*\n"
        f"══════════════════════════\n"
        f"{_modo_aviso(estado)}"
        f"{stats_linea}"
        f"📋 *{len(picks)} picks* seleccionados hoy\n"
        f"Confianza: {sem_txt}\n"
        f"══════════════════════════"
    )

    for i, pick in enumerate(picks, 1):
        enviar_mensaje(formatear_pick(pick, i))

    for combinada in combinadas:
        enviar_mensaje(formatear_combinada(combinada))

    enviar_mensaje(_pie_aviso())


def enviar_picks_canal(
    picks: List[PickOutput],
    combinadas: List[Combinada],
    deporte: str,
    estado: EstadoBanca,
):
    if not picks:
        enviar_mensaje(
            f"🔍 Sin picks hoy para {_liga(deporte)}.\n"
            f"_Sin valor suficiente. Mañana seguimos._"
        )
        return

    enviar_mensaje(
        f"{_icono(deporte)} *PICKS — {_liga(deporte).upper()}*\n"
        f"══════════════════════\n"
        f"{_modo_aviso(estado)}"
        f"📋 *{len(picks)} picks* seleccionados\n"
        f"══════════════════════"
    )

    for i, pick in enumerate(picks, 1):
        enviar_mensaje(formatear_pick(pick, i))

    for combinada in combinadas:
        enviar_mensaje(formatear_combinada(combinada))

    enviar_mensaje(_pie_aviso())


# ── Weekly summary ────────────────────────────────────────────────────────────

def formatear_resumen_semanal(picks_totales, picks_ganados, unidades_resultado, racha) -> str:
    roi = round(unidades_resultado / max(picks_totales, 1) * 100, 1)
    emoji = "📈" if unidades_resultado >= 0 else "📉"
    racha_txt = f"🔥 {racha} ganados" if racha > 0 else f"❄️ {abs(racha)} perdidos"
    signo = "+" if unidades_resultado >= 0 else ""
    return (
        f"📅 *RESUMEN SEMANAL — LOYALTYBETS*\n"
        f"══════════════════════════\n"
        f"✅ *{picks_ganados}/{picks_totales}* picks ganados\n"
        f"🎯 Acierto: *{round(picks_ganados/max(picks_totales,1)*100,1)}%*\n"
        f"{emoji} Unidades: *{signo}{unidades_resultado}u*\n"
        f"📊 ROI: *{signo}{roi}%*\n"
        f"Racha: {racha_txt}\n"
        f"══════════════════════════\n"
        f"_Resultados reales. Sin filtros._"
    )


def enviar_resumen_semanal(picks_totales, picks_ganados, unidades, racha):
    enviar_mensaje(formatear_resumen_semanal(picks_totales, picks_ganados, unidades, racha))


# ── Async core ────────────────────────────────────────────────────────────────

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
