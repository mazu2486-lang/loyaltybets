import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_URL = os.getenv("API_URL")

def parse_equipos(equipo_str: str):
    if " vs " in equipo_str:
        return equipo_str.split(" vs ")
    return (equipo_str, "")

def formatear_pick(pick, numero):
    equipo_local, equipo_visitante = parse_equipos(pick.get("equipo",""))
    tipo = pick.get("tipo_apuesta","")
    if "Under" in tipo or "Over" in tipo:
        pick_linea = f"Total: {tipo}"
    else:
        pick_linea = f"Ganador: {tipo}"
    return (
        f"{pick.get('semaforo','')} PICK #{numero}\n"
        f"⚽ {equipo_local} vs {equipo_visitante}\n"
        f"📌 {pick_linea}\n"
        f"💰 Cuota: {pick.get('cuota')}\n"
        f"📊 Unidades: {pick.get('unidades')}u\n"
    )

async def hoy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    deporte = "futbol"
    url = f"{API_URL}/picks/{deporte}/preview"
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        picks = resp.json()
        if not picks:
            await update.message.reply_text("No hay picks para hoy.")
            return
        mensajes = [formatear_pick(p, i+1) for i, p in enumerate(picks)]
        texto_completo = "\n\n".join(mensajes)
        await update.message.reply_text(texto_completo)
    except Exception as e:
        await update.message.reply_text(f"Error al obtener picks: {e}")

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("hoy", hoy))
    print("Bot corriendo...")
    app.run_polling()
