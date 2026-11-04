"""
Orquestador Principal — Quant Crypto ES (Ley de los Grandes Números + IA Sentimiento).
======================================================================================
Ejecuta un ciclo completo de análisis cuantitativo y de sentimiento IA en tiempo real:
1. Extrae Orderflow institucional de Binance Spot + Perpetuos (BTC, ETH, SOL, XRP, POL).
2. Evalúa el Sentimiento IA y Riesgo de Cisne Negro (Fear & Greed + titulares en vivo + NLP/LLM).
3. Extrae contratos de opciones digitales de corto plazo en Polymarket Crypto.
4. Ejecuta Motor Cripto 1 (Black-Scholes Digital + Principio de Reflexión Browniana, P_real >= 66%).
5. Ejecuta Motor Cripto 2 (Micro-Scalping de Reversión RSI(2) + Orderflow en Uniswap V3 Polygon).
6. Verifica liquidez en el libro de órdenes real de Polymarket y exporta CSVs en `datos/`.
"""

import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict

import pandas as pd

from configuracion import (
    DIRECTORIO_DATOS,
    RUTA_CSV_OPORTUNIDADES_CRIPTO,
    RUTA_CSV_RADAR_CRIPTO,
)
from ejecutor.gestor_wallet_cripto import GestorWalletCripto
from estrategias.motor_cripto import detectar_oportunidades_cripto
from oraculos.binance_orderflow import extraer_estado_orderflow_completo
from oraculos.polymarket_crypto import extraer_mercados_polymarket_cripto
from oraculos.sentimiento_ia import analizar_sentimiento_ia_completo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("QuantCryptoMain")


def ejecutar_escaneo_cuantitativo_cripto(
    gestor_wallet: GestorWalletCripto | None = None,
    verificar_orderbook_vivo: bool = True,
) -> Dict[str, Any]:
    """
    Ejecuta el pipeline completo de Quant Crypto ES y devuelve todas las métricas
    y oportunidades detectadas.
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    DIRECTORIO_DATOS.mkdir(parents=True, exist_ok=True)
    gestor = gestor_wallet or GestorWalletCripto()

    logger.info("1/4 Extrayendo Orderflow en vivo de Binance Spot + Futuros Perpetuos...")
    estado_orderflow = extraer_estado_orderflow_completo()

    logger.info("2/4 Evaluando Sentimiento IA + Detector de Cisne Negro (Fear & Greed + Noticias)...")
    estado_ia = analizar_sentimiento_ia_completo()

    logger.info("3/4 Extrayendo mercados de opciones digitales cripto en Polymarket...")
    mercados_poly = extraer_mercados_polymarket_cripto()

    logger.info("4/4 Ejecutando Motores Cuantitativos (Motor 1: Black-Scholes Digital | Motor 2: Micro-Scalp DEX)...")
    resultado_motores = detectar_oportunidades_cripto(
        estado_orderflow=estado_orderflow,
        estado_ia=estado_ia,
        mercados_poly_cripto=mercados_poly,
    )

    ops_m1 = resultado_motores["motor_1_polymarket_digital"]
    ops_m2 = resultado_motores["motor_2_scalping_dex"]
    todas_ops = resultado_motores["todas_accionables"]

    # Verificar el Orderbook real de las mejores oportunidades del Motor 1 en el CLOB de Polymarket
    if verificar_orderbook_vivo and ops_m1:
        for op in ops_m1[:10]:
            verif = gestor.verificar_orderbook_polymarket_cripto(
                id_mercado=str(op["ID_Mercado"]),
                indice_lado=int(op["Indice_Lado"]),
                precio_objetivo=float(op["Precio_Entrada_Token"]),
            )
            op["Liquidez_CLOB_Vivo_USD"] = verif.get("liquidez_usd", op["Liquidez_USD"])
            op["Mejor_Ask_CLOB_Vivo"] = verif.get("mejor_ask", op["Precio_Entrada_Token"])

    # Exportar radar y oportunidades a CSV
    if estado_orderflow:
        filas_radar = []
        for tk, info in estado_orderflow.items():
            ia_tk = estado_ia.get("activos", {}).get(tk, {})
            fila_comb = {**info, **ia_tk}
            filas_radar.append(fila_comb)
        pd.DataFrame(filas_radar).to_csv(RUTA_CSV_RADAR_CRIPTO, index=False, encoding="utf-8-sig")

    if todas_ops:
        pd.DataFrame(todas_ops).to_csv(RUTA_CSV_OPORTUNIDADES_CRIPTO, index=False, encoding="utf-8-sig")

    resumen_wallet = gestor.obtener_resumen_billetera()
    _imprimir_dashboard_ejecutivo(
        resumen_wallet=resumen_wallet,
        estado_orderflow=estado_orderflow,
        estado_ia=estado_ia,
        total_mercados_poly=len(mercados_poly),
        ops_m1=ops_m1,
        ops_m2=ops_m2,
    )

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "resumen_wallet": resumen_wallet,
        "estado_orderflow": estado_orderflow,
        "estado_ia": estado_ia,
        "ops_motor1": ops_m1,
        "ops_motor2": ops_m2,
        "todas_accionables": todas_ops,
    }


def _imprimir_dashboard_ejecutivo(
    resumen_wallet: Dict[str, Any],
    estado_orderflow: Dict[str, Dict[str, Any]],
    estado_ia: Dict[str, Any],
    total_mercados_poly: int,
    ops_m1: list,
    ops_m2: list,
) -> None:
    print("\n" + "═" * 98)
    print("🚀 QUANT CRYPTO ES — DASHBOARD CUANTITATIVO + SENTIMIENTO IA (LEY DE LOS GRANDES NÚMEROS)")
    print("═" * 98)
    print(
        f"🔐 Billetera Polygon: [{resumen_wallet.get('modo_ejecucion')}] | "
        f"EOA: {resumen_wallet.get('direccion_eoa', 'No config')[:12]}... | "
        f"Gas: {resumen_wallet.get('pol_gas', 0.0):.2f} POL | "
        f"pUSD Deposit Wallet: ${resumen_wallet.get('pusd_deposit_wallet', 0.0):.2f} USD"
    )

    fg = estado_ia.get("fear_and_greed", {})
    print(
        f"🧠 Oráculo Sentimiento IA ({estado_ia.get('modo_motor_ia')}):\n"
        f"   • Fear & Greed Index : {fg.get('valor', 50)}/100 ({fg.get('clasificacion', 'Neutral')}, Δ={fg.get('delta', 0):+d}) | "
        f"Cisne Negro: {'🚨 ALERTA ACTIVA' if estado_ia.get('alerta_cisne_negro') else '✅ Mercado Estable'}"
    )
    for tit in estado_ia.get("titulares_destacados", [])[:3]:
        print(f"   • Noticia Destacada  : {tit}")

    print("\n📊 TELEMETRÍA EN VIVO BINANCE (SPOT + FUTUROS PERPETUOS + SENTIMIENTO IA):")
    for sym, m in estado_orderflow.items():
        ia_sym = estado_ia.get("activos", {}).get(sym, {})
        score_ia = ia_sym.get("Score_Sentimiento_IA", 0.0)
        print(
            f"  • [{sym:<3}] Spot: ${m['Precio_Spot']:>10,.4f} ({m['Cambio_24h_Pct']:+5.2f}% 24h) | "
            f"σ Anual: {m['Sigma_Anualizada']*100:>5.1f}% | "
            f"OBI: {m['OBI_25_Niveles']:+.2f} | "
            f"TakerBuy: {m['Taker_Buy_Ratio_15m']*100:>4.1f}% | "
            f"RSI(2): {m['RSI_2_Connors']:>5.1f} | "
            f"Tendencia: {m['Regimen_Tendencia']:<16} | "
            f"IA: {score_ia:+.2f}"
        )

    print(
        f"\n🎯 MOTOR CRIPTO 1 — Favoritos Digitales Polymarket V2 (Win Rate Obj 66%-90%, Auditados: {total_mercados_poly}): "
        f"{len(ops_m1)} oportunidades"
    )
    if not ops_m1:
        print("  • Sin desajustes matemáticos >= +3.5% EV en este minuto.")
    else:
        for r in ops_m1[:8]:
            print(
                f"  • [{r['Ticker']} | {r['Tipo_Contrato']}] {r['Evento']}\n"
                f"    👉 Comprar `{r['Seleccion']}` @ ${r['Precio_Entrada_Token']:.3f} (Cuota Neta: {r['Cuota_Neta']} vs Justa BS: {r['Cuota_Justa_BS']}) | "
                f"Spot: ${r['Precio_Spot_Binance']:,.2f} vs Strike: ${r['Strike_Objetivo']:,.2f} ({r['Horas_Vencimiento']:.1f}h) ➡️ "
                f"EV: +{r['Ventaja_Neta_Pct']:.2f}% [Stake: ${r['Stake_Sugerido_USD']:.2f}]"
            )

    print(f"\n⚡ MOTOR CRIPTO 2 — Micro-Scalping On-Chain Uniswap V3 Polygon (Pool 0.05%): {len(ops_m2)} señales")
    if not ops_m2:
        print("  • Ningún activo en agotamiento RSI(2) o impulso institucional confirmado en este minuto.")
    else:
        for r in ops_m2:
            print(
                f"  • [{r['Ticker']}] {r['Estrategia']} — `{r['Seleccion']}`\n"
                f"    👉 Entrada Spot: ${r['Precio_Spot_Binance']:,.4f} | WinRate Est: {r['Prob_Real_Pct']:.1f}% | "
                f"Orderflow: {r['Score_Orderflow']:+.2f} | IA: {r['Score_Sentimiento_IA']:+.2f} | "
                f"[Stake: ${r['Stake_Sugerido_USD']:.2f}]"
            )
    print("═" * 98 + "\n")


if __name__ == "__main__":
    try:
        ejecutar_escaneo_cuantitativo_cripto()
    except KeyboardInterrupt:
        sys.exit(0)
