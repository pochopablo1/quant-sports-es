"""
Motor Cuantitativo Triple Estrategia (Meta: Rotación de $200 USD/día en micro-apuestas):
1. MOTOR 1 - VALUE_FAVORITO:
   - EV Neto >= 4.0% (después de comisión) Y Cuota Bruta <= 2.10 (Probabilidad >= ~50%).
   - Objetivo: Apostar con valor estadístico únicamente donde el resultado es el más probable.
2. MOTOR 2 - SUREBET_ARBITRAJE:
   - ROI Neto Garantizado >= 1.0% (después de comisiones en ambas casas).
   - Objetivo: Ganancia libre de riesgo apostando simultáneamente a los 2 lados.
3. MOTOR 3 - TRADING_PRE_PARTIDO (Scalping CLOB en Polymarket / SX Bet / Limitless):
   - Desfasaje (EV Neto) >= 4.0% en mercados con Cuota > 2.10 o alta liquidez CLOB.
   - En lugar de quedarse al partido (evitando la varianza de cuotas altas), compra al precio Ask actual
     y coloca inmediatamente una orden Maker de Venta (Take-Profit) ligeramente por debajo del Precio Justo
     de Pinnacle/Kalshi para capturar entre +3.5% y +6% antes de que empiece el evento.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
from extractores.pinnacle import devig_multiplicativo, devig_multiplicativo_3way
from normalizador.emparejador import (
    emparejar_con_referencia,
    parsear_datetime_utc,
    _es_prop_secundario,
)

# Parámetros de la Meta Diaria del Usuario ($200 USD/día en micro-apuestas de $2.50 a $6.00 USD)
BANKROLL_DIARIO_USD = 200.0
MICRO_STAKE_MIN_USD = 2.50
MICRO_STAKE_MAX_USD = 6.00
LIQUIDEZ_MINIMA_USD = 35.0

# Reglas exactas de los 3 Motores (Umbral de ventaja ajustado al 3.0% a pedido del usuario)
UMBRAL_EV_FAVORITO_PCT = 3.0
CUOTA_MAXIMA_FAVORITO = 2.10
UMBRAL_ROI_SUREBET_PCT = 1.0
UMBRAL_EV_TRADING_PRE_PCT = 3.0

# Límites de cordura cuantitativa
MAX_EV_REALISTA_PCT = 18.0
MAX_ROI_ARBITRAJE_REALISTA_PCT = 10.0

COMISION_GANANCIA_PLATAFORMA = {
    "Polymarket": 0.00,
    "SX Bet": 0.00,
    "Azuro V3": 0.00,
    "Limitless": 0.005,
    "Kalshi": 0.015,
    "Futuur": 0.06,
    "Manifold": 0.02,
    "Pinnacle": 0.00,
}

PLATAFORMAS_EJECUTABLES_WEB3 = {"Polymarket", "SX Bet", "Limitless", "Azuro V3"}
PLATAFORMAS_CLOB_TRADING = {"Polymarket", "SX Bet", "Limitless"}


def _extraer_cuota_empate(linea_str: str) -> float:
    s = str(linea_str or "")
    if "empate@" in s.lower():
        try:
            return float(s.lower().split("empate@")[1].strip())
        except (ValueError, IndexError):
            return 0.0
    return 0.0


def cuota_neta_despues_de_comision(cuota_bruta: float, plataforma: str) -> float:
    if cuota_bruta <= 1.0:
        return 1.0
    comision = COMISION_GANANCIA_PLATAFORMA.get(plataforma, 0.0)
    return round(1.0 + (cuota_bruta - 1.0) * (1.0 - comision), 4)


def calcular_micro_stake_usd(
    ventaja_pct: float,
    liquidez_disponible_usd: float,
    bankroll_diario: float = BANKROLL_DIARIO_USD,
) -> float:
    """
    Calcula un micro-stake entre $2.50 y $6.00 USD proporcional a la ventaja detectada,
    para distribuir los $200 USD diarios en ~40 a 65 micro-operaciones diversificadas.
    """
    # Escala proporcional entre $2.50 (para ~4% de ventaja) y $6.00 (para >=10% de ventaja)
    proporcion = max(0.0125, min((ventaja_pct / 100.0) * 0.30, 0.030))
    stake = bankroll_diario * proporcion
    stake_acotado = max(MICRO_STAKE_MIN_USD, min(stake, MICRO_STAKE_MAX_USD))
    return round(max(MICRO_STAKE_MIN_USD, min(stake_acotado, liquidez_disponible_usd * 0.25)), 2)


def _evento_en_juego_o_pasado(inicio_utc_str: Any) -> bool:
    """
    Devuelve True si el partido ya comenzó o está a menos de 10 minutos de empezar
    (evita entrar como Pre-Partido en eventos que ya están en vivo / In-Play).
    """
    dt = parsear_datetime_utc(inicio_utc_str)
    if dt is None:
        return False
    ahora_utc = datetime.now(tz=timezone.utc)
    # Si la fecha está en el rango reciente (últimos 7 días) y ya pasó o faltan < 10 min, bloquear
    if (ahora_utc - timedelta(days=7)) <= dt <= (ahora_utc + timedelta(minutes=10)):
        return True
    return False


def detectar_oportunidades_cuantitativas(
    todos_los_mercados: List[Dict[str, Any]],
    margen_maker_objetivo_pct: float = 2.5,
    liquidez_minima_usd: float = LIQUIDEZ_MINIMA_USD,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Clasifica todas las oportunidades en los 3 Motores del usuario:
      1. MOTOR_1_VALUE_FAVORITO (EV >= 4% y Cuota <= 2.10)
      2. MOTOR_2_SUREBET (ROI >= 1.0%)
      3. MOTOR_3_TRADING_PRE_PARTIDO (EV >= 4% en CLOB comprando barato y vendiendo antes del inicio)
    """
    mercados_pinnacle = [
        m
        for m in todos_los_mercados
        if m.get("Plataforma") == "Pinnacle" and not _evento_en_juego_o_pasado(m.get("Inicio_UTC"))
    ]
    mercados_exchanges = [
        m
        for m in todos_los_mercados
        if m.get("Plataforma") != "Pinnacle"
        and not _evento_en_juego_o_pasado(m.get("Inicio_UTC"))
        and not _es_prop_secundario(
            str(m.get("Evento", "")),
            str(m.get("Lado_1", "")),
            str(m.get("Lado_2", "")),
            str(m.get("Tipo_Mercado", "")),
        )
    ]
    mercados_clob_profundos = [
        m
        for m in mercados_exchanges
        if m.get("Plataforma") in ("Kalshi", "Polymarket")
        and (float(m.get("Liquidez_1_USD") or 0) >= 250.0)
    ]
    mercados_liquidos_para_arb = [
        e
        for e in mercados_exchanges
        if float(e.get("Liquidez_1_USD") or 0) >= liquidez_minima_usd
        and float(e.get("Liquidez_2_USD") or 0) >= liquidez_minima_usd
        and "1x2" not in str(e.get("Tipo_Mercado", "")).lower()
    ]

    arbitrajes: List[Dict[str, Any]] = []
    value_bets: List[Dict[str, Any]] = []
    trading_pre: List[Dict[str, Any]] = []
    market_making: List[Dict[str, Any]] = []
    cruces_verificados: List[Dict[str, Any]] = []
    oportunidades_accionables: List[Dict[str, Any]] = []

    for mkt in mercados_exchanges:
        plat_mkt = str(mkt.get("Plataforma", ""))
        c1_bruta = float(mkt.get("Cuota_Taker_1") or 0.0)
        c2_bruta = float(mkt.get("Cuota_Taker_2") or 0.0)
        liq_1 = float(mkt.get("Liquidez_1_USD") or 0.0)
        liq_2 = float(mkt.get("Liquidez_2_USD") or 0.0)

        if c1_bruta <= 1.01 or c2_bruta <= 1.01:
            continue

        c1_neta = cuota_neta_despues_de_comision(c1_bruta, plat_mkt)
        c2_neta = cuota_neta_despues_de_comision(c2_bruta, plat_mkt)
        comision_pct = round(COMISION_GANANCIA_PLATAFORMA.get(plat_mkt, 0.0) * 100.0, 2)

        # 1. Emparejar contra Pinnacle (Benchmark Sharp) o contra Kalshi/Polymarket profundo
        ref, invertido, similitud = emparejar_con_referencia(
            mkt, mercados_pinnacle, umbral_similitud=85.0
        )
        if not ref:
            candidatos_clob = [
                r for r in mercados_clob_profundos if r.get("Plataforma") != plat_mkt
            ]
            ref, invertido, similitud = emparejar_con_referencia(
                mkt, candidatos_clob, umbral_similitud=86.0
            )

        if ref:
            c1_ref = float(ref.get("Cuota_Taker_2" if invertido else "Cuota_Taker_1") or 0.0)
            c2_ref = float(ref.get("Cuota_Taker_1" if invertido else "Cuota_Taker_2") or 0.0)
            c_empate_ref = _extraer_cuota_empate(str(ref.get("Linea", "")))

            if c1_ref > 1.01 and c2_ref > 1.01:
                if c_empate_ref > 1.01:
                    prob_justa_1, prob_justa_2, _, cuota_justa_1, cuota_justa_2, _ = (
                        devig_multiplicativo_3way(c1_ref, c2_ref, c_empate_ref)
                    )
                else:
                    prob_justa_1, prob_justa_2, cuota_justa_1, cuota_justa_2 = (
                        devig_multiplicativo(c1_ref, c2_ref)
                    )

                ev_neto_1_pct = round(((c1_neta * prob_justa_1) - 1.0) * 100.0, 2)
                ev_neto_2_pct = round(((c2_neta * prob_justa_2) - 1.0) * 100.0, 2)

                cruces_verificados.append(
                    {
                        "Evento": mkt["Evento"],
                        "Fecha_UTC": mkt["Inicio_UTC"],
                        "Tipo_Mercado": mkt["Tipo_Mercado"],
                        "Linea": mkt["Linea"],
                        "Plataforma_Obj": plat_mkt,
                        "Plataforma_Ref": ref["Plataforma"],
                        "Lado_1": mkt["Lado_1"],
                        "Cuota_Obj_1": c1_bruta,
                        "Cuota_Neta_1": c1_neta,
                        "Cuota_Ref_1": c1_ref,
                        "Cuota_Justa_1": cuota_justa_1,
                        "EV_1_Pct": ev_neto_1_pct,
                        "Liquidez_1_USD": liq_1,
                        "Lado_2": mkt["Lado_2"],
                        "Cuota_Obj_2": c2_bruta,
                        "Cuota_Neta_2": c2_neta,
                        "Cuota_Ref_2": c2_ref,
                        "Cuota_Justa_2": cuota_justa_2,
                        "EV_2_Pct": ev_neto_2_pct,
                        "Liquidez_2_USD": liq_2,
                        "Similitud": similitud,
                    }
                )

                # Analizar cada lado para clasificar en MOTOR 1 (Value Favorito <= 2.10) o MOTOR 3 (Trading Pre-Partido)
                for idx_lado, nombre_lado, c_bruta, c_neta, c_justa, p_justa, ev_neto, liq_lado in [
                    (1, mkt["Lado_1"], c1_bruta, c1_neta, cuota_justa_1, prob_justa_1, ev_neto_1_pct, liq_1),
                    (2, mkt["Lado_2"], c2_bruta, c2_neta, cuota_justa_2, prob_justa_2, ev_neto_2_pct, liq_2),
                ]:
                    if liq_lado < liquidez_minima_usd or ev_neto > MAX_EV_REALISTA_PCT:
                        continue

                    es_web3 = "SÍ (Wallet EVM)" if plat_mkt in PLATAFORMAS_EJECUTABLES_WEB3 else "No (KYC/Otro)"
                    prob_ganar_pct = round(p_justa * 100.0, 1)

                    # --- MOTOR 1: VALUE BET EN FAVORITO (EV >= 4% y Cuota <= 2.10) ---
                    if ev_neto >= UMBRAL_EV_FAVORITO_PCT and c_bruta <= CUOTA_MAXIMA_FAVORITO:
                        stake_sug = calcular_micro_stake_usd(ev_neto, liq_lado)
                        item_vb = {
                            "Motor": "MOTOR_1_VALUE_FAVORITO",
                            "Plataforma": plat_mkt,
                            "Referencia": ref["Plataforma"],
                            "Evento": mkt["Evento"],
                            "Tipo_Mercado": f"{mkt['Tipo_Mercado']} ({mkt['Linea']})",
                            "Liga": mkt["Liga"],
                            "Seleccion": nombre_lado,
                            "Cuota_Taker": c_bruta,
                            "Cuota_Neta": c_neta,
                            "Prob_Real_Pct": prob_ganar_pct,
                            "Cuota_Justa_Pinnacle": c_justa,
                            "EV_Pct": ev_neto,
                            "Liquidez_USD": liq_lado,
                            "Stake_Sugerido_USD": stake_sug,
                            "Ejecutable_Web3": es_web3,
                            "ID_Mercado": mkt["ID_Mercado"],
                        }
                        value_bets.append(item_vb)
                        oportunidades_accionables.append(
                            {
                                "Estrategia": "MOTOR_1_VALUE_FAVORITO (Cuota<=2.10, EV>=4%)",
                                "Ejecutable_Web3": es_web3,
                                "Plataforma_Entrada": plat_mkt,
                                "Oraculo_Referencia": ref["Plataforma"],
                                "Deporte": mkt["Deporte"],
                                "Liga": mkt["Liga"],
                                "Evento": mkt["Evento"],
                                "Inicio_UTC": mkt["Inicio_UTC"],
                                "Mercado_y_Linea": f"{mkt['Tipo_Mercado']} ({mkt['Linea']})",
                                "Indice_Lado": idx_lado,
                                "Seleccion_Apostar": f"{nombre_lado} (Prob: {prob_ganar_pct}%)",
                                "Cuota_Bruta": c_bruta,
                                "Comision_Pct": comision_pct,
                                "Cuota_Neta": c_neta,
                                "Cuota_Justa_Ref": c_justa,
                                "Plan_Salida_Trading": "Mantener hasta final del partido (Favorito >=50%)",
                                "Ventaja_Neta_Pct": ev_neto,
                                "Liquidez_Punta_USD": liq_lado,
                                "Stake_Kelly_Sugerido_USD": stake_sug,
                                "ID_Mercado": mkt["ID_Mercado"],
                            }
                        )

                    # --- MOTOR 3: TRADING PRE-PARTIDO (Scalping CLOB cuando Cuota > 2.10 y EV >= 4%) ---
                    elif (
                        ev_neto >= UMBRAL_EV_TRADING_PRE_PCT
                        and c_bruta > CUOTA_MAXIMA_FAVORITO
                        and plat_mkt in PLATAFORMAS_CLOB_TRADING
                    ):
                        stake_sug = calcular_micro_stake_usd(ev_neto, liq_lado)
                        precio_compra_token = round(1.0 / c_bruta, 4)
                        # Objetivo de salida Maker: vender 1% más barato que el precio justo para asegurar fill rápido pre-partido
                        precio_venta_objetivo = round(p_justa * 0.99, 4)
                        cuota_venta_eq = round(1.0 / precio_venta_objetivo, 4) if precio_venta_objetivo > 0 else c_justa
                        roi_scalping_pct = round(((precio_venta_objetivo / precio_compra_token) - 1.0) * 100.0, 2)

                        if roi_scalping_pct >= 2.5:
                            plan_salida = (
                                f"Comprar token @ ${precio_compra_token:.3f} (cuota {c_bruta}) -> "
                                f"Publicar Venta Maker @ ${precio_venta_objetivo:.3f} (cuota {cuota_venta_eq}) "
                                f"antes del partido (+{roi_scalping_pct}% ROI)"
                            )
                            trading_pre.append(
                                {
                                    "Plataforma": plat_mkt,
                                    "Referencia": ref["Plataforma"],
                                    "Evento": mkt["Evento"],
                                    "Seleccion": nombre_lado,
                                    "Precio_Compra": precio_compra_token,
                                    "Precio_Venta_Maker": precio_venta_objetivo,
                                    "ROI_Scalping_Pct": roi_scalping_pct,
                                    "Liquidez_USD": liq_lado,
                                    "Stake_USD": stake_sug,
                                }
                            )
                            oportunidades_accionables.append(
                                {
                                    "Estrategia": "MOTOR_3_TRADING_PRE_PARTIDO (Scalping CLOB)",
                                    "Ejecutable_Web3": es_web3,
                                    "Plataforma_Entrada": plat_mkt,
                                    "Oraculo_Referencia": ref["Plataforma"],
                                    "Deporte": mkt["Deporte"],
                                    "Liga": mkt["Liga"],
                                    "Evento": mkt["Evento"],
                                    "Inicio_UTC": mkt["Inicio_UTC"],
                                    "Mercado_y_Linea": f"{mkt['Tipo_Mercado']} ({mkt['Linea']})",
                                    "Indice_Lado": idx_lado,
                                    "Seleccion_Apostar": nombre_lado,
                                    "Cuota_Bruta": c_bruta,
                                    "Comision_Pct": comision_pct,
                                    "Cuota_Neta": c_neta,
                                    "Cuota_Justa_Ref": c_justa,
                                    "Plan_Salida_Trading": plan_salida,
                                    "Ventaja_Neta_Pct": roi_scalping_pct,
                                    "Liquidez_Punta_USD": liq_lado,
                                    "Stake_Kelly_Sugerido_USD": stake_sug,
                                    "ID_Mercado": mkt["ID_Mercado"],
                                }
                            )

                # Market Making pasivo general
                if plat_mkt in PLATAFORMAS_CLOB_TRADING:
                    factor_margen = 1.0 + (margen_maker_objetivo_pct / 100.0)
                    market_making.append(
                        {
                            "Plataforma": plat_mkt,
                            "Evento": f"{mkt['Evento']} ({mkt['Tipo_Mercado']} {mkt['Linea']})",
                            "Lado_1": mkt["Lado_1"],
                            "Cuota_Justa_1": cuota_justa_1,
                            "Postear_Maker_1": round(cuota_justa_1 * factor_margen, 3),
                            "Lado_2": mkt["Lado_2"],
                            "Cuota_Justa_2": cuota_justa_2,
                            "Postear_Maker_2": round(cuota_justa_2 * factor_margen, 3),
                            "EV_Esperado_Maker_Pct": margen_maker_objetivo_pct,
                            "Spread_Actual_Libro_Pct": mkt["Overround_Libro_Pct"],
                        }
                    )

        # --- MOTOR 2: SUREBETS (ARBITRAJE DIRECTO CON ROI NETO >= 1.0% Y LIQUIDEZ >= $35) ---
        if liq_1 >= liquidez_minima_usd and liq_2 >= liquidez_minima_usd and "1x2" not in str(mkt.get("Tipo_Mercado", "")).lower():
            otros_exchanges = [
                e for e in mercados_liquidos_para_arb if e.get("Plataforma") != plat_mkt
            ]
            ref_ex, inv_ex, _ = emparejar_con_referencia(mkt, otros_exchanges, umbral_similitud=86.0)
            if ref_ex:
                plat_ex = str(ref_ex.get("Plataforma", ""))
                c1_ex_bruta = float(ref_ex.get("Cuota_Taker_2" if inv_ex else "Cuota_Taker_1") or 0.0)
                c2_ex_bruta = float(ref_ex.get("Cuota_Taker_1" if inv_ex else "Cuota_Taker_2") or 0.0)
                liq_1_ex = float(ref_ex.get("Liquidez_2_USD" if inv_ex else "Liquidez_1_USD") or 0.0)
                liq_2_ex = float(ref_ex.get("Liquidez_1_USD" if inv_ex else "Liquidez_2_USD") or 0.0)

                c1_ex_neta = cuota_neta_despues_de_comision(c1_ex_bruta, plat_ex)
                c2_ex_neta = cuota_neta_despues_de_comision(c2_ex_bruta, plat_ex)

                if c1_ex_neta > 1.01 and c2_ex_neta > 1.01:
                    if c1_neta >= c1_ex_neta:
                        mejor_1, p1_nom, liq_p1, id_p1, idx_p1 = c1_neta, plat_mkt, liq_1, mkt["ID_Mercado"], 1
                    else:
                        mejor_1, p1_nom, liq_p1, id_p1, idx_p1 = (
                            c1_ex_neta,
                            plat_ex,
                            liq_1_ex,
                            ref_ex["ID_Mercado"],
                            2 if inv_ex else 1,
                        )

                    if c2_neta >= c2_ex_neta:
                        mejor_2, p2_nom, liq_p2, id_p2, idx_p2 = c2_neta, plat_mkt, liq_2, mkt["ID_Mercado"], 2
                    else:
                        mejor_2, p2_nom, liq_p2, id_p2, idx_p2 = (
                            c2_ex_neta,
                            plat_ex,
                            liq_2_ex,
                            ref_ex["ID_Mercado"],
                            1 if inv_ex else 2,
                        )

                    suma_inv = (1.0 / mejor_1) + (1.0 / mejor_2)
                    if suma_inv < 0.990 and p1_nom != p2_nom:
                        roi_neto = round(((1.0 / suma_inv) - 1.0) * 100.0, 2)
                        if UMBRAL_ROI_SUREBET_PCT <= roi_neto <= MAX_ROI_ARBITRAJE_REALISTA_PCT:
                            clave_ev = f"{mkt['Evento']} [{mkt['Tipo_Mercado']} {mkt['Linea']}]"
                            par_ids_arb = "::".join(sorted([str(mkt["ID_Mercado"]), str(ref_ex["ID_Mercado"])]))
                            if not any(a.get("_par_ids") == par_ids_arb for a in arbitrajes):
                                liq_min_arb = min(liq_p1, liq_p2)
                                stake_total_arb = calcular_micro_stake_usd(roi_neto, liq_min_arb)
                                stake_pata_1 = round(stake_total_arb * ((1.0 / mejor_1) / suma_inv), 2)
                                stake_pata_2 = round(stake_total_arb - stake_pata_1, 2)

                                arbitrajes.append(
                                    {
                                        "Evento": clave_ev,
                                        "Lado_1": f"{mkt['Lado_1']} @ {mejor_1} ({p1_nom})",
                                        "Lado_2": f"{mkt['Lado_2']} @ {mejor_2} ({p2_nom})",
                                        "ROI_Garantizado_Pct": roi_neto,
                                        "Liquidez_Max_Arb_USD": liq_min_arb,
                                        "_par_ids": par_ids_arb,
                                    }
                                )
                                ambos_web3 = (
                                    "SÍ (100% Web3)"
                                    if (p1_nom in PLATAFORMAS_EJECUTABLES_WEB3 and p2_nom in PLATAFORMAS_EJECUTABLES_WEB3)
                                    else "Híbrido (Web3 + Kalshi)"
                                )
                                oportunidades_accionables.append(
                                    {
                                        "Estrategia": "MOTOR_2_SUREBET (Arbitraje >=1%)",
                                        "Ejecutable_Web3": ambos_web3,
                                        "Plataforma_Entrada": f"{p1_nom} + {p2_nom}",
                                        "Oraculo_Referencia": "Arbitraje 2 Patas",
                                        "Deporte": mkt["Deporte"],
                                        "Liga": mkt["Liga"],
                                        "Evento": mkt["Evento"],
                                        "Inicio_UTC": mkt["Inicio_UTC"],
                                        "Mercado_y_Linea": f"{mkt['Tipo_Mercado']} ({mkt['Linea']})",
                                        "Indice_Lado": idx_p1,
                                        "Seleccion_Apostar": f"P1: {mkt['Lado_1']} (${stake_pata_1} en {p1_nom}) + P2: {mkt['Lado_2']} (${stake_pata_2} en {p2_nom})",
                                        "Cuota_Bruta": mejor_1,
                                        "Comision_Pct": 0.0,
                                        "Cuota_Neta": mejor_1,
                                        "Cuota_Justa_Ref": mejor_2,
                                        "Plan_Salida_Trading": f"Surebet 2 lados simultáneos: Retorno garantizado +{roi_neto}%",
                                        "Ventaja_Neta_Pct": roi_neto,
                                        "Liquidez_Punta_USD": liq_min_arb,
                                        "Stake_Kelly_Sugerido_USD": stake_total_arb,
                                        "ID_Mercado": f"{p1_nom}::{id_p1}::{idx_p1}||{p2_nom}::{id_p2}::{idx_p2}",
                                    }
                                )

    value_bets.sort(key=lambda x: (x["Ejecutable_Web3"].startswith("SÍ"), x["EV_Pct"]), reverse=True)
    arbitrajes.sort(key=lambda x: x["ROI_Garantizado_Pct"], reverse=True)
    trading_pre.sort(key=lambda x: x["ROI_Scalping_Pct"], reverse=True)
    oportunidades_accionables.sort(
        key=lambda x: (x["Ejecutable_Web3"].startswith("SÍ"), x["Ventaja_Neta_Pct"]),
        reverse=True,
    )

    return {
        "arbitrajes": arbitrajes,
        "value_bets": value_bets,
        "trading_pre": trading_pre,
        "market_making": market_making,
        "cruces_verificados": cruces_verificados,
        "oportunidades_accionables": oportunidades_accionables,
    }
