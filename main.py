"""
Orquestador Principal del Mega-Proyecto de Surebets y Arbitraje (`quant_surebets_es/main.py`).
=============================================================================================
Ejecuta el Mapa Mundial de Plataformas 2026 con los 4 Motores de Arbitraje:
  - MOTOR A: Arbitraje Interno en la Misma Casa (Triángulos 1X2 Yes/No y Maker 1 Pata, 0 riesgo de 2da casa).
  - MOTOR B: Surebets Cross-Exchange Taker-Taker (con auditoría exacta de la Tabla 2026: fee = k * (1 - p)).
  - MOTOR C: Arbitraje Maker-Taker Sin Fee (Pata 1 Post-Only Maker 0% fee + Rebate -> Pata 2 Taker FOK).
  - MOTOR D: Pasillos / Middles de Riesgo Cero o Bajo Costo (Gana 1 pata siempre, o GANA LAS 2 en el pasillo).
"""
import argparse
from collections import Counter
import logging
from pathlib import Path
import sys
import pandas as pd

from configuracion import (
    DIRECTORIO_DATOS,
    COEFICIENTE_K_TAKER_2026,
    ESTADO_ARGENTINA_PLATAFORMA,
    calcular_fee_pct_stake_2026,
)
from extractores.multi_exchange import (
    extraer_todas_las_plataformas_en_paralelo,
    extraer_polymarket_con_triangulos_y_bids,
)
from motores.motor_surebets import (
    ejecutar_motor_a_intra_exchange,
    ejecutar_motores_cross_exchange,
    ejecutar_motor_e_inplay_en_vivo,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("OrquestadorSurebets")


def imprimir_tabla_verificacion_comisiones_2026() -> None:
    """Imprime la verificación matemática exacta de la Tabla de Comisiones 2026 del usuario."""
    print("\n" + "═" * 100)
    print("📐 VERIFICACIÓN MATEMÁTICA DE LA TABLA DE COMISIONES 2026: fee_%_stake = k × (1 − p)")
    print("═" * 100)
    precios_prueba = [0.30, 0.50, 0.70, 0.85]
    encabezado = f"{'Precio Share (p)':<18} | {'Polymarket/Limitless (k=5%)':<28} | {'Kalshi (k=7%)':<16} | {'Predict.fun (k=4%)':<19} | {'SX Bet / Overtime':<18}"
    print(encabezado)
    print("-" * 100)
    for p in precios_prueba:
        f_poly = calcular_fee_pct_stake_2026("Limitless", p, es_maker=False)
        f_kal = calcular_fee_pct_stake_2026("Kalshi", p, es_maker=False)
        f_pred = calcular_fee_pct_stake_2026("Predict.fun", p, es_maker=False)
        f_sx = calcular_fee_pct_stake_2026("SX Bet", p, es_maker=False)
        print(
            f"${p:<17.2f} | {f_poly:>6.2f}% (Maker: -0.15%)      | {f_kal:>6.2f}%          | {f_pred:>6.2f}%             | {f_sx:>5.2f}% (0% Taker)"
        )
    print("═" * 100)


def ejecutar_escaneo_surebets(usar_cache_rapida: bool = False) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    imprimir_tabla_verificacion_comisiones_2026()

    ruta_csv_propio = DIRECTORIO_DATOS / "mercados_surebets_consolidado.csv"
    if usar_cache_rapida and ruta_csv_propio.exists():
        logger.info("Cargando mercados normalizados frescos desde %s...", ruta_csv_propio)
        df_base = pd.read_csv(ruta_csv_propio).fillna("N/A")
        mercados_norm = df_base.to_dict(orient="records")
        triangulos_1x2 = []
        conteo = dict(Counter(m["Plataforma"] for m in mercados_norm))
    else:
        logger.info("Extrayendo en paralelo todas las plataformas del Mapa Mundial 2026...")
        datos = extraer_todas_las_plataformas_en_paralelo()
        mercados_norm = datos["mercados_normalizados"]
        triangulos_1x2 = datos["triangulos_1x2"]
        conteo = datos["conteo_plataformas"]
        if mercados_norm:
            pd.DataFrame(mercados_norm).to_csv(ruta_csv_propio, index=False, encoding="utf-8-sig")

    # Ejecutar los 5 Motores (incluyendo Motor E In-Play En Vivo)
    res_motor_a = ejecutar_motor_a_intra_exchange(triangulos_1x2)
    res_cross = ejecutar_motores_cross_exchange(mercados_norm)
    res_inplay = ejecutar_motor_e_inplay_en_vivo(mercados_norm)
    mkts_inplay = res_inplay["mercados_inplay_activos"]
    cruces_inplay = res_inplay["cruces_inplay"]
    if cruces_inplay:
        pd.DataFrame(cruces_inplay).to_csv(DIRECTORIO_DATOS / "motor_e_inplay_en_vivo.csv", index=False, encoding="utf-8-sig")

    surebets_taker = res_cross["surebets_taker"]
    trampas_fee = res_cross["trampas_fee_2026"]
    maker_taker = res_cross["arbs_maker_taker"]
    pasillos = res_cross["pasillos_middles"]

    # Guardar artefactos CSV
    if res_motor_a:
        pd.DataFrame(res_motor_a).to_csv(DIRECTORIO_DATOS / "motor_a_intra_exchange_1x2.csv", index=False, encoding="utf-8-sig")
    if surebets_taker:
        pd.DataFrame(surebets_taker).to_csv(DIRECTORIO_DATOS / "motor_b_surebets_taker_2026.csv", index=False, encoding="utf-8-sig")
    if trampas_fee:
        pd.DataFrame(trampas_fee).to_csv(DIRECTORIO_DATOS / "auditoria_trampas_comision_2026.csv", index=False, encoding="utf-8-sig")
    if maker_taker:
        pd.DataFrame(maker_taker).to_csv(DIRECTORIO_DATOS / "motor_c_arbitraje_maker_taker.csv", index=False, encoding="utf-8-sig")
    if pasillos:
        pd.DataFrame(pasillos).to_csv(DIRECTORIO_DATOS / "motor_d_pasillos_middles.csv", index=False, encoding="utf-8-sig")

    print("\n" + "═" * 100)
    print(f"🌍 REPORTE GLOBAL DE SUREBETS Y ARBITRAJE 2026 — Total Mercados Auditados: {len(mercados_norm)}")
    print("═" * 100)
    for plat, cant in conteo.items():
        estado_ar = ESTADO_ARGENTINA_PLATAFORMA.get(plat, "ORÁCULO / REFERENCIA")
        print(f"  • {plat:<15}: {cant:>5} mercados | [{estado_ar}]")

    # 1. MOTOR A: Intra-Exchange 1X2
    print("\n" + "-" * 100)
    print(f"🏛️ MOTOR A — ARBITRAJE INTERNO MISMA CASA (Triángulos 1X2 sin riesgo de 2da pata): {len(res_motor_a)} analizados")
    print("-" * 100)
    if res_motor_a:
        df_a = pd.DataFrame(res_motor_a)[
            ["Evento", "Subtipo", "Suma_Asks_YES", "ROI_Taker_SinFee_Pct", "ROI_Maker_1Pata_Pct", "ROI_3xNO_Pct"]
        ].head(8)
        print(df_a.to_string(index=False))
    else:
        print("  (Sin triángulos 1X2 activos con spread cerrado en este barrido)")

    # 2. MOTOR B: Surebets Cross-Exchange Taker-Taker
    print("\n" + "-" * 100)
    print(f"⚡ MOTOR B — SUREBETS CROSS-EXCHANGE TAKER-TAKER (Sobreviven tras Comisiones): {len(surebets_taker)}")
    print("-" * 100)
    if surebets_taker:
        cols_b = [
            "Evento",
            "Mercado",
            "Pata_1_Casa",
            "Pata_1_Seleccion",
            "Pata_1_Cuota_Bruta",
            "Pata_2_Casa",
            "Pata_2_Seleccion",
            "Pata_2_Cuota_Bruta",
            "ROI_Bruto_Sin_Fees_Pct",
            "ROI_Neto_Tabla_2026_Pct",
            "ROI_Neto_OnChain_0Bps_Pct",
        ]
        print(pd.DataFrame(surebets_taker)[cols_b].head(12).to_string(index=False))
    else:
        print("  (Ninguna surebet Taker-Taker pura supera hoy el filtro tras descontar la comisión k*(1-p))")

    # 3. AUDITORÍA DE TRAMPAS DE COMISIÓN 2026
    print("\n" + "-" * 100)
    print(
        f"⚠️ AUDITORÍA 2026 — 'FALSAS SUREBETS' COMIDAS POR EL FEE TAKER k*(1-p): {len(trampas_fee)} detectadas"
    )
    print("   (Daban ROI Bruto > 0%, pero quedan en pérdida al restar el 2.5% - 3.5% de fee Taker en 50/50)")
    print("-" * 100)
    if trampas_fee:
        cols_t = [
            "Evento",
            "Mercado",
            "Pata_1_Casa",
            "Pata_1_Cuota_Bruta",
            "Pata_1_Fee_2026_Pct",
            "Pata_2_Casa",
            "Pata_2_Cuota_Bruta",
            "Pata_2_Fee_2026_Pct",
            "ROI_Bruto_Sin_Fees_Pct",
            "ROI_Neto_Tabla_2026_Pct",
            "ROI_Maker_Taker_Pct",
        ]
        print(pd.DataFrame(trampas_fee)[cols_t].head(10).to_string(index=False))

    # 4. MOTOR C: Arbitraje Maker-Taker (0% Fee + Rebate en Pata 1)
    print("\n" + "-" * 100)
    print(
        f"🎯 MOTOR C — ARBITRAJE MAKER-TAKER (Pata 1 Post-Only Maker 0% Fee -> Pata 2 Taker FOK): {len(maker_taker)} oportunidades"
    )
    print("-" * 100)
    if maker_taker:
        cols_c = [
            "Evento",
            "Mercado",
            "Pata_1_Casa",
            "Pata_1_Seleccion",
            "Precio_PostOnly_Maker_Pata1",
            "Pata_2_Casa",
            "Pata_2_Seleccion",
            "Pata_2_Cuota_Bruta",
            "ROI_Neto_Tabla_2026_Pct",
            "ROI_Maker_Taker_Pct",
        ]
        print(pd.DataFrame(maker_taker)[cols_c].head(12).to_string(index=False))

    # 5. MOTOR D: Pasillos / Middles
    print("\n" + "-" * 100)
    print(
        f"🎰 MOTOR D — PASILLOS / MIDDLES DE RIESGO CERO O BAJO COSTO (Jackpot si cae en el medio): {len(pasillos)} detectados"
    )
    print("-" * 100)
    if pasillos:
        print(pd.DataFrame(pasillos).head(12).to_string(index=False))

    # 6. MOTOR E: Deportes EN VIVO (IN-PLAY AHORA MISMO)
    print("\n" + "-" * 100)
    print(
        f"🔴 MOTOR E — DEPORTES EN JUEGO AHORA MISMO (IN-PLAY LIVE): {len(mkts_inplay)} mercados en vivo | {len(cruces_inplay)} cruces"
    )
    print("-" * 100)
    if cruces_inplay:
        print(pd.DataFrame(cruces_inplay).head(15).to_string(index=False))
    elif mkts_inplay:
        df_ip = pd.DataFrame(mkts_inplay)[
            ["Plataforma", "Deporte", "Evento", "Minutos_En_Juego", "Tipo_Mercado", "Lado_1", "Cuota_Taker_1", "Lado_2", "Cuota_Taker_2"]
        ].head(15)
        print(df_ip.to_string(index=False))
    else:
        print("  (No hay partidos en juego en este minuto exacto)")
    print("═" * 100 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Motor Global de Surebets y Arbitraje 2026 (quant_surebets_es)")
    parser.add_argument(
        "--usar-cache-deportes",
        action="store_true",
        help="Usa el CSV recién extraído de quant_sports_es + Triángulos 1X2 en vivo para auditoría instantánea",
    )
    args = parser.parse_args()
    ejecutar_escaneo_surebets(usar_cache_rapida=args.usar_cache_deportes)
