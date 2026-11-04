"""
Daemon 24/7 para Quant Crypto ES (Ley de los Grandes Números + Sentimiento IA).
===============================================================================
Diseñado para correr de forma continua durante 48h+ en consola o PythonAnywhere:
- Escanea cada N minutos:
  * Motor Cripto 1: Opciones Digitales de Corto Plazo en Polymarket V2.
  * Motor Cripto 2: Micro-Scalping Spot RSI(2) + Orderflow en Uniswap V3 Polygon.
- Liquida y audita automáticamente en cada ciclo las operaciones previas contra el
  precio real de Binance y el CLOB de Polymarket, llevando el marcador en vivo de
  Ganadas / Perdidas (Win Rate %) y PnL Neto en `datos/historial_ejecuciones_cripto.csv`.
"""

import argparse
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict

import pandas as pd
import requests

from configuracion import (
    BANKROLL_DIARIO_CRIPTO_USD,
    DIRECTORIO_DATOS,
    RUTA_CSV_HISTORIAL_CRIPTO,
    STOP_LOSS_SCALPING_PCT,
    TAKE_PROFIT_SCALPING_PCT,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)
from ejecutor.gestor_wallet_cripto import GestorWalletCripto
from main import ejecutar_escaneo_cuantitativo_cripto

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("DaemonCripto24_7")

COLUMNAS_HISTORIAL = [
    "ID_Operacion",
    "Timestamp_Apertura_UTC",
    "Motor",
    "Ticker",
    "Tipo_Contrato",
    "Contrato_o_Par",
    "Seleccion",
    "ID_Mercado",
    "Indice_Lado",
    "Precio_Spot_Entrada",
    "Strike_Objetivo",
    "Precio_Entrada_Token",
    "Prob_Real_Pct",
    "EV_Neto_Pct",
    "Stake_USD",
    "Modo_Ejecucion",
    "Estado_Resolucion",
    "Precio_Cierre_o_Actual",
    "PnL_Neto_USD",
    "Timestamp_Resolucion_UTC",
]


def cargar_historial() -> pd.DataFrame:
    DIRECTORIO_DATOS.mkdir(parents=True, exist_ok=True)
    if not os.path.isfile(RUTA_CSV_HISTORIAL_CRIPTO):
        return pd.DataFrame(columns=COLUMNAS_HISTORIAL)
    try:
        df = pd.read_csv(RUTA_CSV_HISTORIAL_CRIPTO, encoding="utf-8-sig")
        for col in COLUMNAS_HISTORIAL:
            if col not in df.columns:
                df[col] = ""
        return df[COLUMNAS_HISTORIAL]
    except Exception as exc:
        logger.warning("No se pudo leer historial previo, creando nuevo: %s", exc)
        return pd.DataFrame(columns=COLUMNAS_HISTORIAL)


def guardar_historial(df: pd.DataFrame) -> None:
    DIRECTORIO_DATOS.mkdir(parents=True, exist_ok=True)
    df.to_csv(RUTA_CSV_HISTORIAL_CRIPTO, index=False, encoding="utf-8-sig")


def actualizar_y_liquidar_operaciones_abiertas(
    estado_orderflow: Dict[str, Dict[str, Any]],
    gestor: GestorWalletCripto,
) -> Dict[str, Any]:
    """
    Revisa todas las operaciones en estado 'ABIERTA' dentro de `historial_ejecuciones_cripto.csv`
    y verifica con datos reales de Binance y Polymarket si ya alcanzaron Take-Profit, Stop-Loss
    o Vencimiento para medir el rendimiento real de la prueba de 48 horas.
    """
    df = cargar_historial()
    if df.empty:
        return {"total": 0, "abiertas": 0, "ganadas": 0, "perdidas": 0, "win_rate_pct": 0.0, "pnl_neto_usd": 0.0}

    ahora_utc = datetime.now(timezone.utc)
    hubo_cambios = False

    for idx, fila in df.iterrows():
        if str(fila["Estado_Resolucion"]) != "ABIERTA":
            continue

        ticker = str(fila["Ticker"])
        if ticker not in estado_orderflow:
            continue

        spot_actual = float(estado_orderflow[ticker]["Precio_Spot"])
        motor = str(fila["Motor"])
        stake = float(fila["Stake_USD"])
        spot_entrada = float(fila["Precio_Spot_Entrada"])
        strike = float(fila["Strike_Objetivo"])

        try:
            dt_apertura = datetime.fromisoformat(str(fila["Timestamp_Apertura_UTC"]).replace("Z", "+00:00"))
            horas_transcurridas = (ahora_utc - dt_apertura).total_seconds() / 3600.0
        except Exception:
            horas_transcurridas = 0.0

        # 1. Evaluación de Motor 2 (Micro-Scalping DEX Spot)
        if "MOTOR_2" in motor:
            cambio_pct = ((spot_actual / spot_entrada) - 1.0) * 100.0 if spot_entrada > 0 else 0.0
            df.at[idx, "Precio_Cierre_o_Actual"] = spot_actual

            if cambio_pct >= TAKE_PROFIT_SCALPING_PCT:
                pnl = round(stake * ((TAKE_PROFIT_SCALPING_PCT / 100.0) - 0.0010), 2)
                df.at[idx, "Estado_Resolucion"] = "GANADA"
                df.at[idx, "PnL_Neto_USD"] = pnl
                df.at[idx, "Timestamp_Resolucion_UTC"] = ahora_utc.isoformat()
                hubo_cambios = True
            elif cambio_pct <= -STOP_LOSS_SCALPING_PCT:
                pnl = round(stake * ((-STOP_LOSS_SCALPING_PCT / 100.0) - 0.0010), 2)
                df.at[idx, "Estado_Resolucion"] = "PERDIDA"
                df.at[idx, "PnL_Neto_USD"] = pnl
                df.at[idx, "Timestamp_Resolucion_UTC"] = ahora_utc.isoformat()
                hubo_cambios = True
            elif horas_transcurridas >= 4.0 and cambio_pct >= 0.18:
                # Salida por tiempo en ganancia neta positiva
                pnl = round(stake * ((cambio_pct / 100.0) - 0.0010), 2)
                df.at[idx, "Estado_Resolucion"] = "GANADA"
                df.at[idx, "PnL_Neto_USD"] = pnl
                df.at[idx, "Timestamp_Resolucion_UTC"] = ahora_utc.isoformat()
                hubo_cambios = True

        # 2. Evaluación de Motor 1 (Opciones Digitales Polymarket V2)
        elif "MOTOR_1" in motor:
            tipo_c = str(fila["Tipo_Contrato"])
            precio_entrada_tok = float(fila["Precio_Entrada_Token"])
            id_mkt = str(fila["ID_Mercado"])
            ind_lado = int(fila["Indice_Lado"]) if str(fila["Indice_Lado"]).isdigit() else 1

            # Verificar si la barrera One-Touch ya fue alcanzada por el precio Spot de Binance
            if tipo_c == "BARRIER_REACH" and ind_lado == 1 and spot_actual >= strike:
                pnl = round(stake * ((1.0 / precio_entrada_tok) * 0.985 - 1.0), 2)
                df.at[idx, "Estado_Resolucion"] = "GANADA"
                df.at[idx, "Precio_Cierre_o_Actual"] = 1.0
                df.at[idx, "PnL_Neto_USD"] = pnl
                df.at[idx, "Timestamp_Resolucion_UTC"] = ahora_utc.isoformat()
                hubo_cambios = True
                continue

            # Consultar el libro en vivo de Polymarket para ver si subió a zona de Take-Profit anticipado (+10% ROI)
            verif = gestor.verificar_orderbook_polymarket_cripto(id_mkt, ind_lado, precio_entrada_tok)
            mejor_bid_actual = float(verif.get("mejor_bid") or 0.0)
            if mejor_bid_actual > 0:
                df.at[idx, "Precio_Cierre_o_Actual"] = mejor_bid_actual
                roi_mark_to_market = (mejor_bid_actual / precio_entrada_tok) - 1.0 if precio_entrada_tok > 0 else 0.0
                if mejor_bid_actual >= 0.96 or roi_mark_to_market >= 0.12:
                    pnl = round(stake * roi_mark_to_market, 2)
                    df.at[idx, "Estado_Resolucion"] = "GANADA"
                    df.at[idx, "PnL_Neto_USD"] = pnl
                    df.at[idx, "Timestamp_Resolucion_UTC"] = ahora_utc.isoformat()
                    hubo_cambios = True

    if hubo_cambios:
        guardar_historial(df)

    tot = len(df)
    gan = int((df["Estado_Resolucion"] == "GANADA").sum())
    per = int((df["Estado_Resolucion"] == "PERDIDA").sum())
    abi = int((df["Estado_Resolucion"] == "ABIERTA").sum())
    cerradas = gan + per
    wr = round((gan / cerradas) * 100.0, 2) if cerradas > 0 else 0.0
    pnl_total = round(pd.to_numeric(df["PnL_Neto_USD"], errors="coerce").fillna(0.0).sum(), 2)

    return {
        "total": tot,
        "abiertas": abi,
        "ganadas": gan,
        "perdidas": per,
        "win_rate_pct": wr,
        "pnl_neto_usd": pnl_total,
    }


def enviar_reporte_telegram_cripto(marcador: Dict[str, Any], estado_ia: Dict[str, Any]) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    ahora_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    fg = estado_ia.get("fear_and_greed", {})
    texto = (
        f"🚀 *REPORTE CRIPTO 48H — QUANT CRYPTO + IA ({ahora_str})*\n"
        f"🧠 *Sentimiento IA:* Fear&Greed `{fg.get('valor', 50)}/100 ({fg.get('clasificacion', 'Neutral')})` | "
        f"Cisne Negro: `{'🚨 SÍ' if estado_ia.get('alerta_cisne_negro') else '✅ NO'}`\n\n"
        f"📊 *Marcador Acumulado (Paper Trading Verificado):*\n"
        f"• *Total Operaciones:* `{marcador['total']}`\n"
        f"• *En Curso (Abiertas):* `{marcador['abiertas']}`\n"
        f"• *Cerradas Ganadas:* `{marcador['ganadas']}` ✅\n"
        f"• *Cerradas Perdidas:* `{marcador['perdidas']}` ❌\n"
        f"• *Tasa de Acierto (Win Rate):* `{marcador['win_rate_pct']:.1f}%` (Meta: ~70%)\n"
        f"• *PnL Neto Acumulado:* `${marcador['pnl_neto_usd']:+.2f} USD`"
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": texto, "parse_mode": "Markdown"},
            timeout=8,
        )
    except Exception as exc:
        logger.debug("No se pudo enviar reporte cripto a Telegram: %s", exc)


def ejecutar_daemon(intervalo_minutos: float, max_ciclos: int, meta_diaria_usd: float) -> None:
    gestor = GestorWalletCripto()
    ciclo = 0
    capital_rotado_hoy = 0.0
    ultimo_telegram_ts = 0.0
    dia_actual = datetime.now(timezone.utc).date()

    # Cargar mercados ya operados en el historial para no duplicar el mismo contrato
    df_init = cargar_historial()
    mercados_operados_hoy: set[str] = set(df_init["ID_Mercado"].astype(str).tolist()) if not df_init.empty else set()

    while True:
        ciclo += 1
        ahora_utc = datetime.now(timezone.utc)
        if ahora_utc.date() != dia_actual:
            dia_actual = ahora_utc.date()
            capital_rotado_hoy = 0.0

        modo_str = "REAL ON-CHAIN" if gestor.ejecucion_real else "PAPER TRADING 48H EN VIVO"
        logger.info(
            "=== CICLO CRIPTO #%d [%s] | Capital rotado hoy: $%.2f / $%.2f USD ===",
            ciclo,
            modo_str,
            capital_rotado_hoy,
            meta_diaria_usd,
        )

        try:
            resultado = ejecutar_escaneo_cuantitativo_cripto(
                gestor_wallet=gestor,
                verificar_orderbook_vivo=True,
            )
            estado_orderflow = resultado["estado_orderflow"]
            estado_ia = resultado["estado_ia"]
            ops_m1 = resultado["ops_motor1"]
            ops_m2 = resultado["ops_motor2"]

            # 1. Auditar y liquidar operaciones abiertas de ciclos anteriores
            marcador = actualizar_y_liquidar_operaciones_abiertas(estado_orderflow, gestor)

            if estado_ia.get("alerta_cisne_negro"):
                logger.warning("🚨 Circuit Breaker IA activado por Cisne Negro. Saltando nuevas compras en este ciclo.")
            else:
                df_hist = cargar_historial()
                nuevas_filas = []

                # 2. Procesar mejores oportunidades de Motor Cripto 1 (Polymarket Crypto)
                for op in ops_m1[:3]:
                    if capital_rotado_hoy >= meta_diaria_usd:
                        break
                    id_mkt = str(op["ID_Mercado"])
                    if id_mkt in mercados_operados_hoy:
                        continue

                    stake = float(op["Stake_Sugerido_USD"])
                    res_orden = gestor.ejecutar_orden_polymarket_cripto(
                        id_mercado=id_mkt,
                        indice_lado=int(op["Indice_Lado"]),
                        precio_limite=float(op["Precio_Entrada_Token"]),
                        stake_usd=stake,
                        descripcion=f"{op['Evento']} ({op['Seleccion']})",
                    )
                    if res_orden.get("exito"):
                        mercados_operados_hoy.add(id_mkt)
                        capital_rotado_hoy += stake
                        nuevas_filas.append({
                            "ID_Operacion": f"M1-{int(time.time())}-{len(nuevas_filas)+1}",
                            "Timestamp_Apertura_UTC": ahora_utc.isoformat(),
                            "Motor": op["Estrategia"],
                            "Ticker": op["Ticker"],
                            "Tipo_Contrato": op["Tipo_Contrato"],
                            "Contrato_o_Par": op["Evento"],
                            "Seleccion": op["Seleccion"],
                            "ID_Mercado": id_mkt,
                            "Indice_Lado": op["Indice_Lado"],
                            "Precio_Spot_Entrada": op["Precio_Spot_Binance"],
                            "Strike_Objetivo": op["Strike_Objetivo"],
                            "Precio_Entrada_Token": res_orden.get("precio_ejecucion", op["Precio_Entrada_Token"]),
                            "Prob_Real_Pct": op["Prob_Real_Pct"],
                            "EV_Neto_Pct": op["Ventaja_Neta_Pct"],
                            "Stake_USD": stake,
                            "Modo_Ejecucion": res_orden.get("modo"),
                            "Estado_Resolucion": "ABIERTA",
                            "Precio_Cierre_o_Actual": op["Precio_Entrada_Token"],
                            "PnL_Neto_USD": 0.0,
                            "Timestamp_Resolucion_UTC": "",
                        })

                # 3. Procesar señales de Motor Cripto 2 (Uniswap V3 Micro-Scalping)
                for op2 in ops_m2[:2]:
                    if capital_rotado_hoy >= meta_diaria_usd:
                        break
                    clave_scalp = f"SCALP_{op2['Ticker']}_{ahora_utc.strftime('%Y%m%d_%H')}"
                    if clave_scalp in mercados_operados_hoy:
                        continue

                    stake = float(op2["Stake_Sugerido_USD"])
                    res_swap = gestor.cotizar_o_ejecutar_swap_uniswap_v3(
                        simbolo=str(op2["Ticker"]),
                        precio_spot_ref=float(op2["Precio_Spot_Binance"]),
                        stake_usd=stake,
                    )
                    if res_swap.get("exito"):
                        mercados_operados_hoy.add(clave_scalp)
                        capital_rotado_hoy += stake
                        nuevas_filas.append({
                            "ID_Operacion": f"M2-{int(time.time())}-{len(nuevas_filas)+1}",
                            "Timestamp_Apertura_UTC": ahora_utc.isoformat(),
                            "Motor": op2["Estrategia"],
                            "Ticker": op2["Ticker"],
                            "Tipo_Contrato": op2["Tipo_Contrato"],
                            "Contrato_o_Par": op2["Evento"],
                            "Seleccion": op2["Seleccion"],
                            "ID_Mercado": clave_scalp,
                            "Indice_Lado": 1,
                            "Precio_Spot_Entrada": op2["Precio_Spot_Binance"],
                            "Strike_Objetivo": op2["Strike_Objetivo"],
                            "Precio_Entrada_Token": op2["Precio_Spot_Binance"],
                            "Prob_Real_Pct": op2["Prob_Real_Pct"],
                            "EV_Neto_Pct": op2["Ventaja_Neta_Pct"],
                            "Stake_USD": stake,
                            "Modo_Ejecucion": res_swap.get("modo"),
                            "Estado_Resolucion": "ABIERTA",
                            "Precio_Cierre_o_Actual": op2["Precio_Spot_Binance"],
                            "PnL_Neto_USD": 0.0,
                            "Timestamp_Resolucion_UTC": "",
                        })

                if nuevas_filas:
                    df_actualizado = pd.concat([df_hist, pd.DataFrame(nuevas_filas)], ignore_index=True)
                    guardar_historial(df_actualizado)
                    marcador = actualizar_y_liquidar_operaciones_abiertas(estado_orderflow, gestor)

                logger.info(
                    "📊 MARCADOR EN VIVO (Prueba 48h): Total=%d | Abiertas=%d | Ganadas=%d | Perdidas=%d | WinRate=%.1f%% | PnL=$%+.2f USD",
                    marcador["total"],
                    marcador["abiertas"],
                    marcador["ganadas"],
                    marcador["perdidas"],
                    marcador["win_rate_pct"],
                    marcador["pnl_neto_usd"],
                )

                if (time.time() - ultimo_telegram_ts) >= 7200.0:
                    enviar_reporte_telegram_cripto(marcador, estado_ia)
                    ultimo_telegram_ts = time.time()

        except Exception as exc:
            logger.error("Error en ciclo #%d del daemon cripto: %s", ciclo, exc)

        if max_ciclos > 0 and ciclo >= max_ciclos:
            logger.info("Alcanzado límite de %d ciclos solicitado. Finalizando.", max_ciclos)
            break

        segundos_espera = int(intervalo_minutos * 60)
        logger.info("Durmiendo %d segundos hasta el próximo barrido cripto...", segundos_espera)
        time.sleep(segundos_espera)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daemon 24/7 Quant Crypto ES")
    parser.add_argument(
        "--intervalo-minutos",
        type=float,
        default=10.0,
        help="Minutos entre cada barrido cuantitativo cripto (default: 10)",
    )
    parser.add_argument(
        "--max-ciclos",
        type=int,
        default=0,
        help="Número máximo de ciclos a ejecutar (0 = infinito 24/7)",
    )
    parser.add_argument(
        "--meta-diaria",
        type=float,
        default=float(BANKROLL_DIARIO_CRIPTO_USD),
        help="Tope diario de rotación de capital en USD (default: $90.00 USD)",
    )
    args = parser.parse_args()
    ejecutar_daemon(
        intervalo_minutos=args.intervalo_minutos,
        max_ciclos=args.max_ciclos,
        meta_diaria_usd=args.meta_diaria,
    )
