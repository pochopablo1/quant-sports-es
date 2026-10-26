"""
Orquestador Continuo 24/7 (Daemon de Rotación Diaria de $200 USD en Micro-Apuestas de $2.50 a $6.00 USD).
Ejecuta periódicamente los 3 Motores:
  1. MOTOR_1_VALUE_FAVORITO (Cuota <= 2.10, EV >= 4.0%)
  2. MOTOR_2_SUREBET (ROI Neto >= 1.0%)
  3. MOTOR_3_TRADING_PRE_PARTIDO (Scalping CLOB comprando Ask y posteando orden Maker de salida)

Características de seguridad y ahorro de tokens:
- Por defecto NO gasta tokens de The-Odds-API en cada barrido corto (usa la caché local de Pinnacle y
  cruza en vivo los exchanges gratuitos: Polymarket, Kalshi, SX Bet, Limitless, Futuur, Azuro V3).
- Evita duplicar la misma apuesta en el mismo día verificando `datos/historial_ejecuciones.csv`.
- Controla el presupuesto diario (`--meta-diaria 200.0`) y detiene nuevas entradas cuando se alcanza la rotación objetivo.
"""
import argparse
from datetime import datetime, timezone
import logging
import sys
import time
import pandas as pd

from main import ejecutar_pipeline
from ejecutor.bot_web3 import ejecutar_barrido_oportunidades, RUTA_HISTORIAL_EJECUCIONES
from ver_estado_hoy import generar_texto_resumen_telegram_hoy
from alertas.telegram_bot import enviar_mensaje_telegram

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("Daemon24_7")


def calcular_capital_rotado_hoy() -> float:
    """Suma el Stake_USD de las órdenes aprobadas en el día UTC actual."""
    if not RUTA_HISTORIAL_EJECUCIONES.exists():
        return 0.0
    try:
        df = pd.read_csv(RUTA_HISTORIAL_EJECUCIONES)
        if df.empty or "Timestamp_UTC" not in df.columns:
            return 0.0
        hoy_prefijo = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        df_hoy = df[
            df["Timestamp_UTC"].astype(str).str.startswith(hoy_prefijo)
            & df["Estado_Orden"].astype(str).str.contains("OK|EJECUTAD|ACTIVO", na=False)
        ]
        return round(float(df_hoy["Stake_USD"].sum()), 2)
    except Exception:
        return 0.0


def iniciar_daemon(
    intervalo_minutos: float = 5.0,
    meta_diaria_usd: float = 200.0,
    max_ciclos: int = 0,
    solo_local: bool = False,
    intervalo_telegram_horas: float = 2.0,
) -> None:
    """Ejecuta el ciclo continuo de escaneo, verificación de orderbook y reporte a Telegram cada 2 horas."""
    ciclo = 0
    ultimo_envio_telegram_ts = 0.0
    intervalo_telegram_seg = max(60.0, intervalo_telegram_horas * 3600.0)

    while True:
        ciclo += 1
        capital_hoy = calcular_capital_rotado_hoy()
        logger.info(
            "=== CICLO #%d | Capital rotado hoy: $%.2f / $%.2f USD ===",
            ciclo,
            capital_hoy,
            meta_diaria_usd,
        )

        if capital_hoy >= meta_diaria_usd:
            logger.info(
                "Meta diaria de $%.2f USD alcanzada ($%.2f USD rotados hoy). Esperando próximo ciclo...",
                meta_diaria_usd,
                capital_hoy,
            )
        else:
            ejecutar_pipeline(
                enviar_telegram=False,
                usar_odds_api_vivo=False,
                usar_cache_local=solo_local,
            )
            resultados = ejecutar_barrido_oportunidades(
                ev_minimo_pct=1.0,
                modo_simulacion=True,
                max_ordenes=25,
            )
            aprobadas = [
                r for r in resultados if any(k in r["Estado_Orden"] for k in ("OK", "EJECUTAD", "ACTIVO"))
            ]
            logger.info(
                "Ciclo #%d completado: %d micro-apuestas nuevas aprobadas en vivo ($2.50-$6.00 USD c/u).",
                ciclo,
                len(aprobadas),
            )

        # Verificar si corresponde enviar el reporte de resumen cada 2 horas a Telegram
        ahora_ts = time.time()
        if (ahora_ts - ultimo_envio_telegram_ts) >= intervalo_telegram_seg:
            resumen_tg = generar_texto_resumen_telegram_hoy()
            ok_tg = enviar_mensaje_telegram(resumen_tg)
            if ok_tg:
                ultimo_envio_telegram_ts = ahora_ts
                logger.info("Resumen de 2 horas enviado con éxito a Telegram.")
            else:
                logger.warning("No se pudo enviar el resumen de 2 horas a Telegram.")

        if max_ciclos > 0 and ciclo >= max_ciclos:
            logger.info("Alcanzado límite de %d ciclos solicitados. Finalizando daemon.", max_ciclos)
            break

        segundos_espera = max(10, int(intervalo_minutos * 60))
        logger.info("Durmiendo %d segundos hasta el próximo barrido...", segundos_espera)
        time.sleep(segundos_espera)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Daemon 24/7 de Micro-Apuestas Cuantitativas ($2.50 a $6.00 USD)")
    parser.add_argument("--intervalo-minutos", type=float, default=5.0, help="Minutos entre cada barrido en vivo")
    parser.add_argument("--meta-diaria", type=float, default=200.0, help="Presupuesto diario a rotar en USD")
    parser.add_argument("--max-ciclos", type=int, default=1, help="Cantidad de ciclos a ejecutar (0 = infinito 24/7)")
    parser.add_argument("--solo-local", action="store_true", help="Usar cache local sin llamar APIs externas")
    parser.add_argument("--horas-telegram", type=float, default=2.0, help="Intervalo en horas para reporte en Telegram")
    args = parser.parse_args()

    iniciar_daemon(
        intervalo_minutos=args.intervalo_minutos,
        meta_diaria_usd=args.meta_diaria,
        max_ciclos=args.max_ciclos,
        solo_local=args.solo_local,
        intervalo_telegram_horas=args.horas_telegram,
    )
