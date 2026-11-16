"""
Cuatro Motores de Arbitraje y Surebets (`motores/motor_surebets.py`).
====================================================================
Implementa los 4 Motores diseñados con la Tabla de Comisiones Dinámicas 2026:
  1. MOTOR A — Arbitraje Interno Misma Casa (Intra-Exchange 1X2 Yes/No & Sintéticas, 0 riesgo de 2da casa).
  2. MOTOR B — Surebets Cross-Exchange Taker-Taker (con auditoría comparativa Bruto vs Tabla 2026 vs On-Chain).
  3. MOTOR C — Arbitraje Maker-Taker Sin Fee (Pata 1 Post-Only Maker 0% fee + Rebate -> Pata 2 Taker FOK).
  4. MOTOR D — Pasillos / Middles de Bajo Costo o Riesgo Cero (Gana 1 pata siempre, o GANA LAS 2 en la ventana).
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Dict, Any, List, Tuple

RUTA_SUREBETS = Path(__file__).resolve().parent.parent
RUTA_SPORTS = RUTA_SUREBETS.parent / "quant_sports_es"
if str(RUTA_SUREBETS) not in sys.path:
    sys.path.insert(0, str(RUTA_SUREBETS))
if RUTA_SPORTS.exists() and str(RUTA_SPORTS) not in sys.path:
    sys.path.append(str(RUTA_SPORTS))

from configuracion import (
    STAKE_TOTAL_SUREBET_USD,
    LIQUIDEZ_MINIMA_POR_PATA_USD,
    ESTADO_ARGENTINA_PLATAFORMA,
    calcular_cuota_efectiva_neta,
)
from normalizador.emparejador import (
    emparejar_con_referencia,
    parsear_datetime_utc,
    _es_prop_secundario,
    similitud_equipos,
    fechas_compatibles,
)


def _es_evento_en_juego_inplay(inicio_utc_str: Any, max_duracion_horas: float = 3.5) -> Tuple[bool, float]:
    """
    Devuelve (True, minutos_transcurridos) si el partido YA COMENZÓ y se está jugando en este momento
    (entre 0 y `max_duracion_horas` desde su hora de inicio UTC).
    """
    dt = parsear_datetime_utc(inicio_utc_str)
    if dt is None:
        return False, 0.0
    ahora = datetime.now(tz=timezone.utc)
    minutos = (ahora - dt).total_seconds() / 60.0
    if -5.0 <= minutos <= (max_duracion_horas * 60.0):
        return True, round(minutos, 1)
    return False, 0.0


def ejecutar_motor_e_inplay_en_vivo(mercados: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    MOTOR E: Escáner de Surebets y Latencia en Partidos EN VIVO (IN-PLAY).
    Filtra exclusivamente los mercados de partidos que se están jugando AHORA MISMO
    y busca:
      1. Surebets In-Play (cuando un punto/gol mueve una casa y la otra queda rezagada).
      2. Desfasajes de Latencia In-Play (diferencia de precio entre dos libros abiertos en vivo).
    """
    mercados_inplay: List[Dict[str, Any]] = []
    for m in mercados:
        es_live, min_juego = _es_evento_en_juego_inplay(m.get("Inicio_UTC"))
        if es_live or str(m.get("Plataforma")) == "Vegas_InPlay_Live":
            if float(m.get("Cuota_Taker_1") or 0.0) > 1.02 and float(m.get("Cuota_Taker_2") or 0.0) > 1.02:
                copia = dict(m)
                copia["Minutos_En_Juego"] = min_juego
                mercados_inplay.append(copia)

    cruces_inplay: List[Dict[str, Any]] = []
    vistas = set()

    for i, m1 in enumerate(mercados_inplay):
        plat_1 = str(m1.get("Plataforma", ""))
        # Buscar contra TODOS los mercados de otras plataformas (porque Kalshi reporta expected_expiration_time +3h en vez de startTime)
        candidatos = [x for x in mercados if x.get("Plataforma") != plat_1]
        m2, inv, sim = emparejar_con_referencia(m1, candidatos, umbral_similitud=85.0)
        if not m2:
            continue
        plat_2 = str(m2.get("Plataforma", ""))
        clave = "|".join(sorted([f"{plat_1}:{m1.get('ID_Mercado')}", f"{plat_2}:{m2.get('ID_Mercado')}"]))
        if clave in vistas:
            continue
        vistas.add(clave)

        c1_m1, c2_m1 = float(m1["Cuota_Taker_1"]), float(m1["Cuota_Taker_2"])
        c1_m2 = float(m2["Cuota_Taker_2" if inv else "Cuota_Taker_1"])
        c2_m2 = float(m2["Cuota_Taker_1" if inv else "Cuota_Taker_2"])

        combos = [
            (plat_1, str(m1["Lado_1"]), c1_m1, str(m1.get("ID_Mercado", "")), 1, plat_2, str(m2["Lado_1" if inv else "Lado_2"]), c2_m2, str(m2.get("ID_Mercado", "")), 1 if inv else 2),
            (plat_2, str(m2["Lado_2" if inv else "Lado_1"]), c1_m2, str(m2.get("ID_Mercado", "")), 2 if inv else 1, plat_1, str(m1["Lado_2"]), c2_m1, str(m1.get("ID_Mercado", "")), 2),
        ]
        mejor_combo = None
        mejor_roi_bruto = -999.0
        for p_a, sel_a, ca, id_a, idx_a, p_b, sel_b, cb, id_b, idx_b in combos:
            suma_b = (1.0 / ca) + (1.0 / cb)
            roi_b = round(((1.0 / suma_b) - 1.0) * 100.0, 2)
            if roi_b > mejor_roi_bruto:
                mejor_roi_bruto = roi_b
                mejor_combo = (p_a, sel_a, ca, id_a, idx_a, p_b, sel_b, cb, id_b, idx_b)

        if mejor_combo:
            p_a, sel_a, ca, id_a, idx_a, p_b, sel_b, cb, id_b, idx_b = mejor_combo
            _, costo_a_2026, _ = calcular_cuota_efectiva_neta(ca, p_a, es_maker=False, usar_tabla_conservadora_poly=True)
            _, costo_b_2026, _ = calcular_cuota_efectiva_neta(cb, p_b, es_maker=False, usar_tabla_conservadora_poly=True)
            roi_2026 = round(((1.0 / (costo_a_2026 + costo_b_2026)) - 1.0) * 100.0, 2)

            _, costo_a_0bps, _ = calcular_cuota_efectiva_neta(ca, p_a, es_maker=False, usar_tabla_conservadora_poly=False)
            _, costo_b_0bps, _ = calcular_cuota_efectiva_neta(cb, p_b, es_maker=False, usar_tabla_conservadora_poly=False)
            roi_onchain = round(((1.0 / (costo_a_0bps + costo_b_0bps)) - 1.0) * 100.0, 2)

            p_maker_a = max(0.02, round((1.0 / ca) - 0.01, 3))
            _, costo_mk_a, _ = calcular_cuota_efectiva_neta(1.0 / p_maker_a, p_a, es_maker=True)
            roi_mk_tk = round(((1.0 / (costo_mk_a + costo_b_2026)) - 1.0) * 100.0, 2)

            cruces_inplay.append({
                "Evento": m1.get("Evento", ""),
                "Deporte": m1.get("Deporte", ""),
                "Min_Juego": m1.get("Minutos_En_Juego", 0.0),
                "Mercado": f"{m1.get('Tipo_Mercado')} ({m1.get('Linea')})",
                "Pata_1": f"[{p_a}] {sel_a} @ {ca:.3f} (${1/ca:.2f})",
                "Pata_2": f"[{p_b}] {sel_b} @ {cb:.3f} (${1/cb:.2f})",
                "Pata_1_Casa": p_a,
                "Pata_1_Seleccion": sel_a,
                "Pata_1_Cuota_Bruta": round(ca, 4),
                "Pata_1_ID_Mercado": id_a,
                "Pata_1_Indice_Lado": idx_a,
                "Pata_2_Casa": p_b,
                "Pata_2_Seleccion": sel_b,
                "Pata_2_Cuota_Bruta": round(cb, 4),
                "Pata_2_ID_Mercado": id_b,
                "Pata_2_Indice_Lado": idx_b,
                "ROI_Bruto_Pct": mejor_roi_bruto,
                "ROI_Neto_2026_Pct": roi_2026,
                "ROI_OnChain_0Bps_Pct": roi_onchain,
                "ROI_Maker_Taker_Pct": roi_mk_tk,
            })

    cruces_inplay.sort(key=lambda x: x["ROI_Bruto_Pct"], reverse=True)
    return {
        "mercados_inplay_activos": mercados_inplay,
        "cruces_inplay": cruces_inplay,
    }


def _evento_valido_pre_partido(inicio_utc_str: Any, max_horas: float = 72.0) -> bool:
    """Devuelve True si el partido aún no comenzó (faltan >= 10 min) y es dentro de las próximas `max_horas`."""
    dt = parsear_datetime_utc(inicio_utc_str)
    if dt is None:
        return True
    ahora = datetime.now(tz=timezone.utc)
    if dt <= (ahora + timedelta(minutes=10)):
        return False
    if dt > (ahora + timedelta(hours=max_horas)):
        return False
    return True


def _calcular_stakes_proporcionales(costo_1: float, costo_2: float, stake_total: float) -> Tuple[float, float, float]:
    """
    Dado el costo efectivo por cada $1 de pago en Pata 1 (`costo_1`) y Pata 2 (`costo_2`),
    calcula cuántos dólares apostar en cada pata para garantizar el mismo retorno exacto.
    Retorna: (stake_1_usd, stake_2_usd, pago_garantizado_usd)
    """
    suma_costos = costo_1 + costo_2
    if suma_costos <= 0:
        return 0.0, 0.0, 0.0
    stake_1 = round(stake_total * (costo_1 / suma_costos), 2)
    stake_2 = round(stake_total - stake_1, 2)
    pago_garantizado = round(stake_total / suma_costos, 2)
    return stake_1, stake_2, pago_garantizado


def ejecutar_motor_a_intra_exchange(triangulos_1x2: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    MOTOR A: Arbitraje Interno dentro de una misma plataforma (Triángulos 1X2 Yes/Yes/Yes,
    Triángulos Inversos No/No/No que pagan $2.00 garantizados, y Maker-Taker 1X2).
    """
    oportunidades_intra: List[Dict[str, Any]] = []

    for tri in triangulos_1x2:
        if not _evento_valido_pre_partido(tri.get("Inicio_UTC")):
            continue
        patas = tri.get("Patas") or []
        if len(patas) != 3:
            continue

        # 1. Suma de comprar los 3 YES como Taker (paga $1.00 garantizado porque exactamente 1 ocurre)
        asks_yes = [float(p["ask_yes"]) for p in patas]
        bids_yes = [float(p["bid_yes"]) for p in patas]
        asks_no = [float(p["ask_no"]) for p in patas]
        liq_min = min(float(p["liquidez_usd"]) for p in patas)

        # Costo Taker con Tabla 2026 vs Sin Fee (o Maker)
        costos_yes_tabla = []
        for p_ask in asks_yes:
            _, c_ef, _ = calcular_cuota_efectiva_neta(1.0 / p_ask, "Polymarket", es_maker=False, usar_tabla_conservadora_poly=True)
            costos_yes_tabla.append(c_ef)

        suma_yes_bruta = round(sum(asks_yes), 4)
        suma_yes_tabla = round(sum(costos_yes_tabla), 4)

        # Si posteamos la pata de mayor spread como Maker (al Bid + $0.01, 0% fee) y las otras 2 como Taker
        spreads = [asks_yes[i] - bids_yes[i] for i in range(3)]
        idx_maker = spreads.index(max(spreads))
        precio_maker_pata = round(min(asks_yes[idx_maker] - 0.01, bids_yes[idx_maker] + 0.01), 3)
        suma_yes_maker_1pata = round(
            precio_maker_pata + sum(asks_yes[i] for i in range(3) if i != idx_maker), 4
        )

        # 2. Suma de comprar los 3 NO (exactamente 2 de los 3 NO ganan siempre -> pago garantizado = $2.00 USD!)
        suma_no_bruta = round(sum(asks_no), 4)
        roi_no_bruto_pct = round(((2.0 / suma_no_bruta) - 1.0) * 100.0, 2) if suma_no_bruta > 0 else -99.0

        roi_yes_bruto_pct = round(((1.0 / suma_yes_bruta) - 1.0) * 100.0, 2) if suma_yes_bruta > 0 else -99.0
        roi_yes_tabla_pct = round(((1.0 / suma_yes_tabla) - 1.0) * 100.0, 2) if suma_yes_tabla > 0 else -99.0
        roi_yes_maker_pct = round(((1.0 / suma_yes_maker_1pata) - 1.0) * 100.0, 2) if suma_yes_maker_1pata > 0 else -99.0

        mejor_roi = max(roi_yes_bruto_pct, roi_yes_maker_pct, roi_no_bruto_pct)
        if mejor_roi >= -3.5:
            etiquetas = " | ".join(f"{p['etiqueta']} (Ask:${p['ask_yes']:.2f}/Bid:${p['bid_yes']:.2f})" for p in patas)
            tipo_sub = (
                "TRIANGULO_1X2_TAKER_PURO"
                if roi_yes_bruto_pct > 0
                else ("TRIANGULO_1X2_NOx3_PAGA_$2" if roi_no_bruto_pct > roi_yes_maker_pct else "TRIANGULO_1X2_MAKER_1_PATA")
            )
            oportunidades_intra.append({
                "Motor": "MOTOR_A_INTRA_EXCHANGE",
                "Subtipo": tipo_sub,
                "Plataforma": tri["Plataforma"],
                "Evento": tri["Evento"],
                "Inicio_UTC": tri["Inicio_UTC"],
                "Detalle_Patas": etiquetas,
                "Suma_Asks_YES": suma_yes_bruta,
                "ROI_Taker_SinFee_Pct": roi_yes_bruto_pct,
                "ROI_Taker_Tabla2026_Pct": roi_yes_tabla_pct,
                "ROI_Maker_1Pata_Pct": roi_yes_maker_pct,
                "ROI_3xNO_Pct": roi_no_bruto_pct,
                "Liquidez_Min_USD": liq_min,
            })

    oportunidades_intra.sort(key=lambda x: x["ROI_Maker_1Pata_Pct"], reverse=True)
    return oportunidades_intra


def ejecutar_motores_cross_exchange(
    mercados: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Ejecuta simultáneamente:
      - MOTOR B: Surebets Cross-Exchange Taker-Taker (y auditoría de Surebets comidas por el Fee 2026).
      - MOTOR C: Arbitraje Maker-Taker Sin Fee (Pata 1 Maker 0% fee + Rebate -> Pata 2 Taker FOK).
      - MOTOR D: Pasillos / Middles de Bajo Costo o Riesgo Cero (2 líneas distintas del mismo partido).
    """
    validos = [
        m
        for m in mercados
        if _evento_valido_pre_partido(m.get("Inicio_UTC"))
        and not _es_prop_secundario(
            str(m.get("Evento", "")),
            str(m.get("Lado_1", "")),
            str(m.get("Lado_2", "")),
            str(m.get("Tipo_Mercado", "")),
        )
        and "1x2" not in str(m.get("Tipo_Mercado", "")).lower()
        and float(m.get("Cuota_Taker_1") or 0.0) > 1.02
        and float(m.get("Cuota_Taker_2") or 0.0) > 1.02
    ]

    surebets_taker: List[Dict[str, Any]] = []
    trampas_fee_2026: List[Dict[str, Any]] = []
    arbs_maker_taker: List[Dict[str, Any]] = []
    pasillos_middles: List[Dict[str, Any]] = []

    vistas_cross = set()
    vistas_middles = set()

    # Separar por deporte para acelerar el cruce O(N*M)
    por_deporte: Dict[str, List[Dict[str, Any]]] = {}
    for m in validos:
        dep = str(m.get("Deporte") or "General")
        por_deporte.setdefault(dep, []).append(m)

    for dep, lista_dep in por_deporte.items():
        n = len(lista_dep)
        for i in range(n):
            m1 = lista_dep[i]
            plat_1 = str(m1.get("Plataforma", ""))
            ev_1 = str(m1.get("Evento", ""))
            tipo_1 = str(m1.get("Tipo_Mercado", ""))
            lin_1_str = str(m1.get("Linea", "N/A"))
            liq_1_a = float(m1.get("Liquidez_1_USD") or 0.0)
            liq_1_b = float(m1.get("Liquidez_2_USD") or 0.0)

            # 1. Búsqueda de Surebets Exactas (Misma Línea) usando `emparejar_con_referencia`
            candidatos_otra_casa = [
                x for x in lista_dep[i + 1 :] if x.get("Plataforma") != plat_1
            ]
            m2, invertido, sim = emparejar_con_referencia(m1, candidatos_otra_casa, umbral_similitud=86.0)
            if m2:
                plat_2 = str(m2.get("Plataforma", ""))
                clave_par = "|".join(sorted([f"{plat_1}:{m1.get('ID_Mercado')}", f"{plat_2}:{m2.get('ID_Mercado')}"]))
                if clave_par not in vistas_cross:
                    vistas_cross.add(clave_par)

                    c1_m1 = float(m1["Cuota_Taker_1"])
                    c2_m1 = float(m1["Cuota_Taker_2"])
                    c1_m2 = float(m2["Cuota_Taker_2" if invertido else "Cuota_Taker_1"])
                    c2_m2 = float(m2["Cuota_Taker_1" if invertido else "Cuota_Taker_2"])

                    liq1_m2 = float(m2["Liquidez_2_USD" if invertido else "Liquidez_1_USD"] or 0.0)
                    liq2_m2 = float(m2["Liquidez_1_USD" if invertido else "Liquidez_2_USD"] or 0.0)

                    # Evaluar las 2 combinaciones cruzadas posibles:
                    # Combo 1: Lado 1 en M1 + Lado 2 en M2
                    # Combo 2: Lado 1 en M2 + Lado 2 en M1
                    combos = [
                        (
                            plat_1, str(m1["Lado_1"]), c1_m1, liq_1_a, str(m1.get("ID_Mercado", "")), 1,
                            plat_2, str(m2["Lado_1" if invertido else "Lado_2"]), c2_m2, liq2_m2, str(m2.get("ID_Mercado", "")), 1 if invertido else 2,
                        ),
                        (
                            plat_2, str(m2["Lado_2" if invertido else "Lado_1"]), c1_m2, liq1_m2, str(m2.get("ID_Mercado", "")), 2 if invertido else 1,
                            plat_1, str(m1["Lado_2"]), c2_m1, liq_1_b, str(m1.get("ID_Mercado", "")), 2,
                        ),
                    ]

                    for p_a, sel_a, cuota_a, liq_a, id_a, idx_a, p_b, sel_b, cuota_b, liq_b, id_b, idx_b in combos:
                        if min(liq_a, liq_b) < LIQUIDEZ_MINIMA_POR_PATA_USD:
                            continue

                        # a) ROI Bruto (sin comisiones, como lo calculaban los bots viejos)
                        costo_bruto_a = 1.0 / cuota_a
                        costo_bruto_b = 1.0 / cuota_b
                        suma_bruta = costo_bruto_a + costo_bruto_b
                        roi_bruto_pct = round(((1.0 / suma_bruta) - 1.0) * 100.0, 2)

                        # Filtrar errores de datos obvios (> 14% bruto suele ser partido distinto o línea mal etiquetada)
                        if roi_bruto_pct > 14.0:
                            continue

                        # b) ROI Neto Tabla 2026 (aplicando k * (1 - p) en Polymarket 5%, Limitless 5%, Kalshi 7%, SX Bet 0%)
                        cuota_neta_a_2026, costo_a_2026, fee_a_pct = calcular_cuota_efectiva_neta(
                            cuota_a, p_a, es_maker=False, usar_tabla_conservadora_poly=True
                        )
                        cuota_neta_b_2026, costo_b_2026, fee_b_pct = calcular_cuota_efectiva_neta(
                            cuota_b, p_b, es_maker=False, usar_tabla_conservadora_poly=True
                        )
                        suma_2026 = costo_a_2026 + costo_b_2026
                        roi_neto_2026_pct = round(((1.0 / suma_2026) - 1.0) * 100.0, 2)

                        # c) ROI Neto On-Chain Real (contratos deportivos de Polymarket con fee_rate_bps=0)
                        _, costo_a_onchain, _ = calcular_cuota_efectiva_neta(
                            cuota_a, p_a, es_maker=False, usar_tabla_conservadora_poly=False, poly_fee_bps_vivo=0
                        )
                        _, costo_b_onchain, _ = calcular_cuota_efectiva_neta(
                            cuota_b, p_b, es_maker=False, usar_tabla_conservadora_poly=False, poly_fee_bps_vivo=0
                        )
                        suma_onchain = costo_a_onchain + costo_b_onchain
                        roi_neto_onchain_pct = round(((1.0 / suma_onchain) - 1.0) * 100.0, 2)

                        # d) MOTOR C: Qué pasa si entramos como MAKER (Post-Only 0% fee + Rebate, ganando 1 centavo de spread)
                        #    en la Pata A y cubrimos como TAKER instantáneo en la Pata B
                        precio_maker_a = max(0.02, round(costo_bruto_a - 0.01, 3))
                        cuota_maker_a = round(1.0 / precio_maker_a, 4)
                        _, costo_maker_a, fee_maker_a = calcular_cuota_efectiva_neta(
                            cuota_maker_a, p_a, es_maker=True, usar_tabla_conservadora_poly=True
                        )
                        suma_maker_taker = costo_maker_a + costo_b_2026
                        roi_maker_taker_pct = round(((1.0 / suma_maker_taker) - 1.0) * 100.0, 2)

                        stake_1, stake_2, pago_gar = _calcular_stakes_proporcionales(
                            costo_a_2026, costo_b_2026, STAKE_TOTAL_SUREBET_USD
                        )

                        registro_base = {
                            "Evento": ev_1,
                            "Deporte": dep,
                            "Liga": m1.get("Liga", ""),
                            "Inicio_UTC": m1.get("Inicio_UTC", ""),
                            "Mercado": f"{tipo_1} ({lin_1_str})",
                            "Pata_1_Casa": p_a,
                            "Pata_1_Seleccion": sel_a,
                            "Pata_1_Cuota_Bruta": round(cuota_a, 4),
                            "Pata_1_Precio_Share": round(costo_bruto_a, 3),
                            "Pata_1_Fee_2026_Pct": fee_a_pct,
                            "Pata_1_Cuota_Neta_2026": cuota_neta_a_2026,
                            "Pata_1_ID_Mercado": id_a,
                            "Pata_1_Indice_Lado": idx_a,
                            "Pata_2_Casa": p_b,
                            "Pata_2_Seleccion": sel_b,
                            "Pata_2_Cuota_Bruta": round(cuota_b, 4),
                            "Pata_2_Precio_Share": round(costo_bruto_b, 3),
                            "Pata_2_Fee_2026_Pct": fee_b_pct,
                            "Pata_2_Cuota_Neta_2026": cuota_neta_b_2026,
                            "Pata_2_ID_Mercado": id_b,
                            "Pata_2_Indice_Lado": idx_b,
                            "ROI_Bruto_Sin_Fees_Pct": roi_bruto_pct,
                            "ROI_Neto_Tabla_2026_Pct": roi_neto_2026_pct,
                            "ROI_Neto_OnChain_0Bps_Pct": roi_neto_onchain_pct,
                            "ROI_Maker_Taker_Pct": roi_maker_taker_pct,
                            "Precio_PostOnly_Maker_Pata1": precio_maker_a,
                            "Stake_Pata_1_USD": stake_1,
                            "Stake_Pata_2_USD": stake_2,
                            "Pago_Garantizado_USD": pago_gar,
                            "Liquidez_Min_USD": round(min(liq_a, liq_b), 2),
                            "Acceso_Argentina_P1": ESTADO_ARGENTINA_PLATAFORMA.get(p_a, "VERIFICAR"),
                            "Acceso_Argentina_P2": ESTADO_ARGENTINA_PLATAFORMA.get(p_b, "VERIFICAR"),
                        }

                        # Clasificación en Motor B (Surebets Taker rentables) vs Trampas de Comisión 2026
                        if roi_neto_2026_pct >= 0.25 or roi_neto_onchain_pct >= 0.50:
                            surebets_taker.append(registro_base)
                        elif roi_bruto_pct > 0.0 and roi_neto_2026_pct <= 0.0:
                            # ¡Caso exacto del documento del usuario! Era surebet bruta pero el fee 2026 la dejó en pérdida
                            trampas_fee_2026.append(registro_base)

                        # Clasificación en Motor C (Arbitraje Maker-Taker sin Fee en Pata 1)
                        if roi_maker_taker_pct >= 0.80 and p_a in ("Polymarket", "Limitless", "SX Bet", "Kalshi"):
                            arbs_maker_taker.append(registro_base)

            # 2. MOTOR D: Búsqueda de PASILLOS / MIDDLES en Totales (Over/Under)
            if "totales" in tipo_1.lower():
                try:
                    val_lin_1 = float(lin_1_str)
                except ValueError:
                    val_lin_1 = -999.0
                if val_lin_1 > 0:
                    partes_1 = [x.strip() for x in ev_1.replace(" vs. ", " vs ").split(" vs ") if x.strip()]
                    if len(partes_1) == 2:
                        for m_otro in lista_dep[i + 1 :]:
                            if "totales" not in str(m_otro.get("Tipo_Mercado", "")).lower():
                                continue
                            try:
                                val_lin_2 = float(str(m_otro.get("Linea", "N/A")))
                            except ValueError:
                                continue
                            ancho_pasillo = abs(val_lin_2 - val_lin_1)
                            if not (1.0 <= ancho_pasillo <= 4.5):
                                continue
                            if not fechas_compatibles(m1.get("Inicio_UTC"), m_otro.get("Inicio_UTC")):
                                continue
                            ev_2 = str(m_otro.get("Evento", ""))
                            partes_2 = [x.strip() for x in ev_2.replace(" vs. ", " vs ").split(" vs ") if x.strip()]
                            if len(partes_2) != 2:
                                continue
                            sim_dir = min(similitud_equipos(partes_1[0], partes_2[0]), similitud_equipos(partes_1[1], partes_2[1]))
                            sim_inv = min(similitud_equipos(partes_1[0], partes_2[1]), similitud_equipos(partes_1[1], partes_2[0]))
                            if max(sim_dir, sim_inv) < 86.0:
                                continue

                            # Para armar un Pasillo (Middle) en Totales:
                            # Compramos OVER en la línea más BAJA y UNDER en la línea más ALTA
                            mkt_bajo, lin_baja, mkt_alto, lin_alta = (
                                (m1, val_lin_1, m_otro, val_lin_2)
                                if val_lin_1 < val_lin_2
                                else (m_otro, val_lin_2, m1, val_lin_1)
                            )
                            c_over_bajo = float(mkt_bajo["Cuota_Taker_1"])  # Lado 1 = Over
                            c_under_alto = float(mkt_alto["Cuota_Taker_2"]) # Lado 2 = Under
                            plat_over = str(mkt_bajo["Plataforma"])
                            plat_under = str(mkt_alto["Plataforma"])

                            _, costo_over, _ = calcular_cuota_efectiva_neta(
                                c_over_bajo, plat_over, es_maker=False, usar_tabla_conservadora_poly=False
                            )
                            _, costo_under, _ = calcular_cuota_efectiva_neta(
                                c_under_alto, plat_under, es_maker=False, usar_tabla_conservadora_poly=False
                            )
                            suma_costo_pasillo = costo_over + costo_under
                            roi_fuera_pasillo_pct = round(((1.0 / suma_costo_pasillo) - 1.0) * 100.0, 2)
                            roi_jackpot_ambas_ganan_pct = round(((2.0 / suma_costo_pasillo) - 1.0) * 100.0, 2)

                            # Guardar pasillos cuyo costo fuera del pasillo sea <= 1.8% (o positivo = Surebet + Jackpot!)
                            if roi_fuera_pasillo_pct >= -1.80:
                                clave_mid = f"{ev_1}|{plat_over}:O{lin_baja}|{plat_under}:U{lin_alta}"
                                if clave_mid not in vistas_middles:
                                    vistas_middles.add(clave_mid)
                                    pasillos_middles.append({
                                        "Evento": ev_1,
                                        "Deporte": dep,
                                        "Pata_1": f"[{plat_over}] Over {lin_baja} @ {c_over_bajo:.3f} (${1/c_over_bajo:.2f})",
                                        "Pata_2": f"[{plat_under}] Under {lin_alta} @ {c_under_alto:.3f} (${1/c_under_alto:.2f})",
                                        "Pata_1_Casa": plat_over,
                                        "Pata_1_Seleccion": f"Over {lin_baja}",
                                        "Pata_1_Cuota_Bruta": round(c_over_bajo, 4),
                                        "Pata_1_ID_Mercado": str(mkt_bajo.get("ID_Mercado", "")),
                                        "Pata_1_Indice_Lado": 1,
                                        "Pata_2_Casa": plat_under,
                                        "Pata_2_Seleccion": f"Under {lin_alta}",
                                        "Pata_2_Cuota_Bruta": round(c_under_alto, 4),
                                        "Pata_2_ID_Mercado": str(mkt_alto.get("ID_Mercado", "")),
                                        "Pata_2_Indice_Lado": 2,
                                        "Ventana_Ganar_Ambas": f"Total entre {lin_baja} y {lin_alta} ({ancho_pasillo:.1f} pts)",
                                        "ROI_Normal_1Pata_Pct": roi_fuera_pasillo_pct,
                                        "ROI_Jackpot_2Patas_Pct": roi_jackpot_ambas_ganan_pct,
                                    })

            # 3. MOTOR D (Parte 2): PASILLOS / MIDDLES en Hándicap (Spread)
            elif "spread" in tipo_1.lower() or "hándicap" in tipo_1.lower():
                try:
                    val_sp_1 = abs(float(lin_1_str))
                except ValueError:
                    val_sp_1 = -999.0
                if val_sp_1 > 0:
                    fav_1 = str(m1.get("Lado_1", ""))
                    dog_1 = str(m1.get("Lado_2", ""))
                    for m_otro in lista_dep[i + 1 :]:
                        t_otro = str(m_otro.get("Tipo_Mercado", "")).lower()
                        if "spread" not in t_otro and "hándicap" not in t_otro:
                            continue
                        try:
                            val_sp_2 = abs(float(str(m_otro.get("Linea", "N/A"))))
                        except ValueError:
                            continue
                        ancho_sp = abs(val_sp_2 - val_sp_1)
                        if not (1.0 <= ancho_sp <= 4.0):
                            continue
                        if not fechas_compatibles(m1.get("Inicio_UTC"), m_otro.get("Inicio_UTC")):
                            continue
                        # Verificar que el favorito (Lado_1, que tiene el spread negativo) sea el mismo equipo en ambos mercados
                        fav_2 = str(m_otro.get("Lado_1", ""))
                        dog_2 = str(m_otro.get("Lado_2", ""))
                        if similitud_equipos(fav_1, fav_2) < 88.0 or similitud_equipos(dog_1, dog_2) < 88.0:
                            continue

                        # Para armar un Pasillo en Spread:
                        # Compramos el FAVORITO con el hándicap MÁS CHICO (-val_bajo) y el UNDERDOG con el hándicap MÁS GRANDE (+val_alto)
                        mkt_bajo, sp_bajo, mkt_alto, sp_alto = (
                            (m1, val_sp_1, m_otro, val_sp_2)
                            if val_sp_1 < val_sp_2
                            else (m_otro, val_sp_2, m1, val_sp_1)
                        )
                        c_fav_bajo = float(mkt_bajo["Cuota_Taker_1"])
                        c_dog_alto = float(mkt_alto["Cuota_Taker_2"])
                        plat_fav = str(mkt_bajo["Plataforma"])
                        plat_dog = str(mkt_alto["Plataforma"])

                        # En un Hándicap real, el favorito (cuota menor o línea negativa) no puede costar > 2.40 en un pasillo de 1-3 pts
                        if c_fav_bajo > 2.35 or c_dog_alto > 2.35:
                            continue

                        _, costo_fav, _ = calcular_cuota_efectiva_neta(
                            c_fav_bajo, plat_fav, es_maker=False, usar_tabla_conservadora_poly=False
                        )
                        _, costo_dog, _ = calcular_cuota_efectiva_neta(
                            c_dog_alto, plat_dog, es_maker=False, usar_tabla_conservadora_poly=False
                        )
                        suma_costo_sp = costo_fav + costo_dog
                        roi_normal_sp = round(((1.0 / suma_costo_sp) - 1.0) * 100.0, 2)
                        roi_jackpot_sp = round(((2.0 / suma_costo_sp) - 1.0) * 100.0, 2)

                        if roi_normal_sp >= -1.80:
                            clave_sp = f"{ev_1}|{plat_fav}:{fav_1}-{sp_bajo}|{plat_dog}:{dog_1}+{sp_alto}"
                            if clave_sp not in vistas_middles:
                                vistas_middles.add(clave_sp)
                                pasillos_middles.append({
                                    "Evento": ev_1,
                                    "Deporte": dep,
                                    "Pata_1": f"[{plat_fav}] {fav_1} -{sp_bajo} @ {c_fav_bajo:.3f} (${1/c_fav_bajo:.2f})",
                                    "Pata_2": f"[{plat_dog}] {dog_1} +{sp_alto} @ {c_dog_alto:.3f} (${1/c_dog_alto:.2f})",
                                    "Pata_1_Casa": plat_fav,
                                    "Pata_1_Seleccion": f"{fav_1} -{sp_bajo}",
                                    "Pata_1_Cuota_Bruta": round(c_fav_bajo, 4),
                                    "Pata_1_ID_Mercado": str(mkt_bajo.get("ID_Mercado", "")),
                                    "Pata_1_Indice_Lado": 1,
                                    "Pata_2_Casa": plat_dog,
                                    "Pata_2_Seleccion": f"{dog_1} +{sp_alto}",
                                    "Pata_2_Cuota_Bruta": round(c_dog_alto, 4),
                                    "Pata_2_ID_Mercado": str(mkt_alto.get("ID_Mercado", "")),
                                    "Pata_2_Indice_Lado": 2,
                                    "Ventana_Ganar_Ambas": f"{fav_1} gana por {sp_bajo} a {sp_alto} pts ({ancho_sp:.1f} pts)",
                                    "ROI_Normal_1Pata_Pct": roi_normal_sp,
                                    "ROI_Jackpot_2Patas_Pct": roi_jackpot_sp,
                                })

    surebets_taker.sort(key=lambda x: x["ROI_Neto_Tabla_2026_Pct"], reverse=True)
    trampas_fee_2026.sort(key=lambda x: x["ROI_Bruto_Sin_Fees_Pct"], reverse=True)
    arbs_maker_taker.sort(key=lambda x: x["ROI_Maker_Taker_Pct"], reverse=True)
    pasillos_middles.sort(key=lambda x: x["ROI_Normal_1Pata_Pct"], reverse=True)

    return {
        "surebets_taker": surebets_taker,
        "trampas_fee_2026": trampas_fee_2026,
        "arbs_maker_taker": arbs_maker_taker,
        "pasillos_middles": pasillos_middles,
    }
