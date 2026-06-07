# LoyaltyBet Pick Engine v2.0

## Arquitectura

```
main.py          → FastAPI endpoints
models.py        → Pydantic models
pick_engine.py   → Motor EV + filtros + unidades
data_fetcher.py  → The Odds API + MLB Stats API + TheSportsDB
combinada.py     → Armado del parlay diario
telegram_bot.py  → Formato de mensajes + envío al canal
bankroll.py      → Estado banca (normal / defensa / crítico)
```

## Variables de entorno en Railway

| Variable | Descripción |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token de tu bot (BotFather) |
| `TELEGRAM_CHAT_ID` | `@TuCanal` o chat_id numérico |
| `ODDS_API_KEY` | Key de https://the-odds-api.com |
| `API_SPORTS_KEY` | Key de https://api-sports.io (opcional) |
| `BANKROLL_STATE_PATH` | Path para persistir estado (default: `/tmp/bankroll_state.json`) |

## Deploy en Railway

1. Subir los 7 archivos al repo GitHub
2. Conectar repo en Railway → New Project → Deploy from GitHub
3. Agregar variables de entorno en Railway → Variables
4. Verificar que corra: `GET /health`

## Uso diario

### Publicar picks de fútbol
```
GET /picks/futbol
```

### Preview sin publicar (para revisar antes)
```
GET /picks/futbol/preview
```

### Registrar resultado (actualiza bankroll)
```
POST /resultado
{ "gano": true }
```

### Resumen semanal (programar domingos)
```
POST /resumen/semanal
{
  "picks_totales": 35,
  "picks_ganados": 21,
  "unidades_resultado": 8.5,
  "racha": 3
}
```

### Reset manual de banca
```
POST /bankroll/reset
```

## Lógica de picks

- **Criterio único de entrada**: EV positivo + edge ≥ 4% + prob modelo ≥ 54%
- **Rango de cuotas**: 1.30 – 3.50
- **Máximo**: 7 picks por día, 8 unidades de exposición total
- **Combinada**: 3–4 mejores picks, solo en modo normal
- **No se publica EV ni probabilidades** al canal público

## Sistema de unidades

| Edge | Unidades |
|---|---|
| 4–7% | 1u |
| 7–11% | 2u |
| >11% | 3u |

Modo defensa (3 pérdidas consecutivas): máx 1u  
Modo crítico (5 pérdidas consecutivas): máx 0.5u  
Sin combinadas en modos defensa/crítico.
