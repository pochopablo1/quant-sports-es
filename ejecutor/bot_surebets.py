"""
Ejecutor Atómico On-Chain de Surebets, Pasillos de Riesgo Cero y Arbitraje En Vivo (`ejecutor/bot_surebets.py`).
===============================================================================================================
Evalúa las oportunidades detectadas por los 5 Motores de Surebets cada 1 minuto:
  1. MOTOR E (In-Play En Vivo): Partidos en juego ahora mismo con Surebet / Desfasaje Neto >= 0.80%.
  2. MOTOR B & C (Surebets Cross-Exchange Pre-Partido): Surebets puras Polymarket <-> SX Bet / Kalshi / Limitless.
  3. MOTOR D & A (Pasillos de Riesgo Cero Costo <= $1.00 y Triángulos 1X2 Intra-Polymarket).
Verifica el Orderbook L2 (`/book` en Polymarket y `/orders-v3/odds/best` en SX Bet) al milisegundo y dispara
la orden FOK real cuando `EJECUCION_REAL_HABILITADA=true` en `.env`.
"""
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import sys
from typing import Dict, Any, List, Tuple
import pandas as pd

RUTA_BASE = Path(__file__).resolve().parent.parent
RUTA_SPORTS = RUTA_BASE.parent / "quant_sports_es"
if str(RUTA_BASE) not in sys.path:
    sys.path.insert(0, str(RUTA_BASE))
if RUTA_SPORTS.exists() and str(RUTA_SPORTS) not in sys.path:
    sys.path.append(str(RUTA_SPORTS))

from configuracion import DIRECTORIO_DATOS, calcular_cuota_efectiva_neta
from normalizador.emparejador import parsear_datetime_utc
from ejecutor.verificador_atomico import (
    verificar_pata_polymarket_vwap,
    verificar_pata_sx_bet_vivo,
)
from ejecutor.gestor_wallet import (
    firmar_orden_polymarket_clob,
    firmar_orden_sx_bet_v3,
)

logger = logging.getLogger("EjecutorSurebets")
RUTA_HISTORIAL_SUREBETS = DIRECTORIO_DATOS / "historial_surebets_ejecutadas.csv"


def _extraer_token_id_polymarket(id_mercado_compuesto: str, indice_lado: int) -> str:
    partes = str(id_mercado_compuesto).split("::")
    if len(partes) >= 3:
        return partes[1] if int(indice_lado) == 1 else partes[2]
    return ""


def _cargar_claves_ya_ejecutadas() -> set:
    if not RUTA_HISTORIAL_SUREBETS.exists():
        return set()
    try:
        df = pd.read_csv(RUTA_HISTORIAL_SUREBETS)
        modo_real = os.getenv("EJECUCION_REAL_HABILITADA", "false").lower() == "true"
        prefijo = "ORDEN_REAL" if modo_real else "PAPER"
        df_f = df[df["Estado_Ejecucion"].astype(str).str.startswith(prefijo)]
        claves = set(df_f["Clave_Unica"].astype(str).tolist())
        if "Evento" in df_f.columns:
            claves.update(df_f["Evento"].astype(str).tolist())
        return claves
    except Exception:
        return set()


def _es_evento_en_vivo_o_liquida_hoy(inicio_utc_str: Any, max_horas: float = 14.0) -> bool:
    """
    CANDADO DE VELOCIDAD DE CAPITAL (PARTIDOS DE HOY O EN VIVO):
    Solo permite operar partidos que estén EN VIVO ahora mismo (últimas 3.5h)
    o que empiecen dentro de la jornada de hoy (hasta 14h de distancia, cubriendo
    tarde y noche sin congelar saldo para mañana ni fin de semana).
    """
    dt = parsear_datetime_utc(inicio_utc_str)
    if dt is None:
        return False
    ahora = datetime.now(tz=timezone.utc)
    return (ahora - timedelta(hours=3.5)) <= dt <= (ahora + timedelta(hours=max_horas))


def ejecutar_oportunidades_surebets(
    surebets_taker: List[Dict[str, Any]],
    arbs_maker_taker: List[Dict[str, Any]],
    pasillos_middles: List[Dict[str, Any]],
    cruces_inplay: List[Dict[str, Any]],
    triangulos_1x2: List[Dict[str, Any]] = None,
    stake_por_pata_usd: float = 4.0,
    max_ejecuciones_ciclo: int = 3,
) -> List[Dict[str, Any]]:
    """
    Revisa todas las oportunidades de Surebets (En Vivo y Pre-Partido), verifica el libro L2
    en tiempo real y ejecuta las patas accionables sin repetir eventos.
    """
    ya_ejecutadas = _cargar_claves_ya_ejecutadas()
    nuevas_ejecuciones: List[Dict[str, Any]] = []

    candidatas: List[Dict[str, Any]] = []
    # Casas donde tenemos billetera y balance activo
    casas_con_billetera = {"Polymarket", "SX Bet", "Limitless"}

    # 1. Prioridad 1: Surebets EN VIVO de 2 Patas (Polymarket <-> SX Bet / Limitless)
    for ip in cruces_inplay:
        c1_casa = str(ip.get("Pata_1_Casa", ""))
        c2_casa = str(ip.get("Pata_2_Casa", ""))
        roi_oc = float(ip.get("ROI_OnChain_0Bps_Pct", -99.0))
        roi_26 = float(ip.get("ROI_Neto_2026_Pct", -99.0))
        roi_max = max(roi_oc, roi_26)
        ev_nombre = ip.get("Evento", "")

        if c1_casa in casas_con_billetera and c2_casa in casas_con_billetera:
            if roi_max >= 0.40:
                logger.info("🎯 [IN-PLAY ACCIONABLE] %s | [%s] vs [%s] | ROI: %+.2f%%", ev_nombre, c1_casa, c2_casa, roi_max)
                candidatas.append({
                    "Tipo_Estrategia": "SUREBET_2CASAS_INPLAY",
                    "Evento": ev_nombre,
                    "Deporte": ip.get("Deporte", ""),
                    "Inicio_UTC": ip.get("Inicio_UTC", ""),
                    "Mercado": ip.get("Mercado", ""),
                    "Pata_1_Casa": c1_casa,
                    "Pata_1_Seleccion": ip.get("Pata_1_Seleccion", ""),
                    "Pata_1_Cuota": float(ip.get("Pata_1_Cuota_Bruta", 0.0)),
                    "Pata_1_ID": ip.get("Pata_1_ID_Mercado", ""),
                    "Pata_1_Idx": int(ip.get("Pata_1_Indice_Lado", 1)),
                    "Pata_2_Casa": c2_casa,
                    "Pata_2_Seleccion": ip.get("Pata_2_Seleccion", ""),
                    "Pata_2_Cuota": float(ip.get("Pata_2_Cuota_Bruta", 0.0)),
                    "Pata_2_ID": ip.get("Pata_2_ID_Mercado", ""),
                    "Pata_2_Idx": int(ip.get("Pata_2_Indice_Lado", 2)),
                    "ROI_Esperado_Pct": roi_max,
                })
        else:
            logger.debug("ℹ️ [In-Play Informativo] %s | [%s] vs [%s] ROI: %+.2f%% (No ejecutable: solo trading en %s)", ev_nombre, c1_casa, c2_casa, roi_max, casas_con_billetera)

    # 2. Prioridad 2: Surebets Cross-Exchange del Día (Liquidan en horas: <= 14h)
    for sb in surebets_taker:
        ini_utc = sb.get("Inicio_UTC")
        if not _es_evento_en_vivo_o_liquida_hoy(ini_utc, max_horas=14.0):
            continue
        c1_casa = str(sb.get("Pata_1_Casa", ""))
        c2_casa = str(sb.get("Pata_2_Casa", ""))
        roi_oc = float(sb.get("ROI_Neto_OnChain_0Bps_Pct", -99.0))
        roi_26 = float(sb.get("ROI_Neto_Tabla_2026_Pct", -99.0))
        roi_max = max(roi_oc, roi_26)
        ev_nombre = sb.get("Evento", "")

        if c1_casa in casas_con_billetera and c2_casa in casas_con_billetera:
            if roi_max >= 0.35:
                logger.info("🎯 [SUREBET HOY ACCIONABLE] %s | [%s] vs [%s] | ROI: %+.2f%%", ev_nombre, c1_casa, c2_casa, roi_max)
                candidatas.append({
                    "Tipo_Estrategia": "SUREBET_2CASAS_POLY_SXBET",
                    "Evento": ev_nombre,
                    "Deporte": sb.get("Deporte", ""),
                    "Inicio_UTC": ini_utc,
                    "Mercado": sb.get("Mercado", ""),
                    "Pata_1_Casa": c1_casa,
                    "Pata_1_Seleccion": sb.get("Pata_1_Seleccion", ""),
                    "Pata_1_Cuota": float(sb.get("Pata_1_Cuota_Bruta", 0.0)),
                    "Pata_1_ID": sb.get("Pata_1_ID_Mercado", ""),
                    "Pata_1_Idx": int(sb.get("Pata_1_Indice_Lado", 1)),
                    "Pata_2_Casa": c2_casa,
                    "Pata_2_Seleccion": sb.get("Pata_2_Seleccion", ""),
                    "Pata_2_Cuota": float(sb.get("Pata_2_Cuota_Bruta", 0.0)),
                    "Pata_2_ID": sb.get("Pata_2_ID_Mercado", ""),
                    "Pata_2_Idx": int(sb.get("Pata_2_Indice_Lado", 2)),
                    "ROI_Esperado_Pct": roi_max,
                })
        else:
            logger.debug("ℹ️ [Surebet Informativa] %s | [%s] vs [%s] ROI: %+.2f%% (No ejecutable: solo trading en %s)", ev_nombre, c1_casa, c2_casa, roi_max, casas_con_billetera)

    # 3. Prioridad 3: Maker-Taker Arbitraje del Día (Pata 1 Maker 0% Fee -> Pata 2 Taker FOK)
    for mt in (arbs_maker_taker or []):
        ini_utc = mt.get("Inicio_UTC")
        if not _es_evento_en_vivo_o_liquida_hoy(ini_utc, max_horas=14.0):
            continue
        c1_casa = str(mt.get("Pata_1_Casa", ""))
        c2_casa = str(mt.get("Pata_2_Casa", ""))
        roi_mt = float(mt.get("ROI_Maker_Taker_Pct", -99.0))
        ev_nombre = mt.get("Evento", "")

        if c1_casa in casas_con_billetera and c2_casa in casas_con_billetera:
            if roi_mt >= 0.35:
                logger.info("🎯 [MAKER-TAKER ACCIONABLE] %s | [%s] vs [%s] | ROI: %+.2f%%", ev_nombre, c1_casa, c2_casa, roi_mt)
                candidatas.append({
                    "Tipo_Estrategia": "MAKER_TAKER_2CASAS",
                    "Evento": ev_nombre,
                    "Deporte": mt.get("Deporte", ""),
                    "Inicio_UTC": ini_utc,
                    "Mercado": mt.get("Mercado", "Maker-Taker"),
                    "Pata_1_Casa": c1_casa,
                    "Pata_1_Seleccion": mt.get("Pata_1_Seleccion", ""),
                    "Pata_1_Cuota": float(mt.get("Pata_1_Cuota_Bruta", 0.0)),
                    "Pata_1_ID": mt.get("Pata_1_ID_Mercado", ""),
                    "Pata_1_Idx": int(mt.get("Pata_1_Indice_Lado", 1)),
                    "Pata_2_Casa": c2_casa,
                    "Pata_2_Seleccion": mt.get("Pata_2_Seleccion", ""),
                    "Pata_2_Cuota": float(mt.get("Pata_2_Cuota_Bruta", 0.0)),
                    "Pata_2_ID": mt.get("Pata_2_ID_Mercado", ""),
                    "Pata_2_Idx": int(mt.get("Pata_2_Indice_Lado", 2)),
                    "ROI_Esperado_Pct": roi_mt,
                })

    # 4. Prioridad 4: Pasillos de Riesgo Cero EN VIVO o del Día (Liquidan en horas: <= 14h)
    for pas in pasillos_middles:
        if not _es_evento_en_vivo_o_liquida_hoy(pas.get("Inicio_UTC"), max_horas=14.0):
            continue
        c1_casa = str(pas.get("Pata_1_Casa", ""))
        c2_casa = str(pas.get("Pata_2_Casa", ""))
        if c1_casa in casas_con_billetera and c2_casa in casas_con_billetera:
            roi_norm = float(pas.get("ROI_Normal_1Pata_Pct", -99.0))
            if roi_norm >= 0.0:
                candidatas.append({
                    "Tipo_Estrategia": "PASILLO_2PATAS_RIESGO_CERO",
                    "Evento": pas.get("Evento", ""),
                    "Deporte": pas.get("Deporte", ""),
                    "Inicio_UTC": pas.get("Inicio_UTC", ""),
                    "Mercado": pas.get("Ventana_Ganar_Ambas", "Pasillo"),
                    "Pata_1_Casa": c1_casa,
                    "Pata_1_Seleccion": pas.get("Pata_1_Seleccion", ""),
                    "Pata_1_Cuota": float(pas.get("Pata_1_Cuota_Bruta", 0.0)),
                    "Pata_1_ID": pas.get("Pata_1_ID_Mercado", ""),
                    "Pata_1_Idx": int(pas.get("Pata_1_Indice_Lado", 1)),
                    "Pata_2_Casa": c2_casa,
                    "Pata_2_Seleccion": pas.get("Pata_2_Seleccion", ""),
                    "Pata_2_Cuota": float(pas.get("Pata_2_Cuota_Bruta", 0.0)),
                    "Pata_2_ID": pas.get("Pata_2_ID_Mercado", ""),
                    "Pata_2_Idx": int(pas.get("Pata_2_Indice_Lado", 2)),
                    "ROI_Esperado_Pct": roi_norm,
                })

    for cand in candidatas:
        if len(nuevas_ejecuciones) >= max_ejecuciones_ciclo:
            break

        clave = f"{cand['Tipo_Estrategia']}|{cand['Evento']}|{cand['Pata_1_Seleccion']}|{cand['Pata_2_Seleccion']}"
        if clave in ya_ejecutadas or cand["Evento"] in ya_ejecutadas:
            logger.info("⏭️ [Filtro Antiduplicado] Omitiendo %s: ya fue operado hoy.", cand["Evento"])
            continue

        # Verificar y ejecutar AMBAS patas (Polymarket y/o SX Bet)
        patas_a_ejecutar = [
            (1, cand["Pata_1_Casa"], cand["Pata_1_Seleccion"], cand["Pata_1_Cuota"], cand["Pata_1_ID"], cand["Pata_1_Idx"]),
            (2, cand["Pata_2_Casa"], cand["Pata_2_Seleccion"], cand["Pata_2_Cuota"], cand["Pata_2_ID"], cand["Pata_2_Idx"]),
        ]
        verif_ok = True
        detalles_verif = []
        ordenes_preparadas = []

        for num_p, casa_p, sel_p, cuota_esp, id_mkt, idx_lado in patas_a_ejecutar:
            if casa_p == "Polymarket":
                tok_id = _extraer_token_id_polymarket(id_mkt, idx_lado)
                if not tok_id:
                    verif_ok = False
                    detalles_verif.append(f"Poly({sel_p}): Sin Token ID CLOB")
                    break
                ok_p, cuota_vwap, liq_top, _, det_p = verificar_pata_polymarket_vwap(tok_id, stake_por_pata_usd)
                if not ok_p or cuota_vwap <= 1.02:
                    verif_ok = False
                    detalles_verif.append(f"Poly({sel_p}): {det_p}")
                    break
                precio_vivo = round(1.0 / cuota_vwap, 2)
                if not (0.08 <= precio_vivo <= 0.93) or (1.0 / cuota_vwap) > (1.0 / cuota_esp) + 0.02:
                    verif_ok = False
                    detalles_verif.append(f"Poly({sel_p}): Precio fuera de rango o cuota degradada ({cuota_vwap:.3f} vs esp {cuota_esp:.3f})")
                    break
                ordenes_preparadas.append(("Polymarket", sel_p, tok_id, precio_vivo, cuota_vwap, idx_lado))
                detalles_verif.append(f"Poly({sel_p}): {det_p}")
            elif casa_p == "SX Bet":
                if not id_mkt:
                    verif_ok = False
                    detalles_verif.append(f"SXBet({sel_p}): Sin marketHash")
                    break
                ok_sx, cuota_sx_viva, liq_sx, det_sx = verificar_pata_sx_bet_vivo(id_mkt, idx_lado, stake_por_pata_usd)
                if not ok_sx or (1.0 / cuota_sx_viva) > (1.0 / cuota_esp) + 0.02:
                    verif_ok = False
                    detalles_verif.append(f"SXBet({sel_p}): {det_sx}")
                    break
                ordenes_preparadas.append(("SX Bet", sel_p, id_mkt, round(1.0 / cuota_sx_viva, 4), cuota_sx_viva, idx_lado))
                detalles_verif.append(f"SXBet({sel_p}): {det_sx}")
            else:
                verif_ok = False
                detalles_verif.append(f"{casa_p}: Casa sin conector de ordenes")
                break

        if not verif_ok or len(ordenes_preparadas) != 2:
            logger.info("⚠️ [Libro L2 Rechazado] %s: %s", cand["Evento"], " ; ".join(detalles_verif) if detalles_verif else "Libro incompleto")
            continue

        # CANDADO MARK-BEFORE-SEND: Bloquear clave y evento ANTES de enviar cualquier orden a la red
        ya_ejecutadas.add(clave)
        ya_ejecutadas.add(cand["Evento"])

        # Si hay una pata de SX Bet, ejecutar SIEMPRE primero SX Bet para que si falla no gaste nada en Polymarket
        ordenes_preparadas.sort(key=lambda x: 0 if x[0] == "SX Bet" else 1)

        # Calcular stakes proporcionales para que AMBAS patas compren exactamente los mismos contratos / mismo cobro
        suma_precios_vivos = sum(float(x[3]) for x in ordenes_preparadas)
        presupuesto_par_usd = min(9.50, float(stake_por_pata_usd) * 2.0)
        pago_objetivo_shares = max(5.2, round(presupuesto_par_usd / max(0.50, suma_precios_vivos), 2))

        # Disparar AMBAS patas (Pata 1 + Pata 2) con monto proporcional exacto
        estados_orden = []
        todo_ejecutado = True
        for casa_p, sel_p, id_ref, precio_vivo, cuota_viva, idx_lado in ordenes_preparadas:
            stake_pata_exacto = max(1.50, min(5.80, round(pago_objetivo_shares * float(precio_vivo), 2)))
            if casa_p == "Polymarket":
                exito, msg = firmar_orden_polymarket_clob(
                    token_id=id_ref,
                    precio=precio_vivo,
                    tamano_usd=stake_pata_exacto,
                    lado="BUY",
                    tipo_orden="FOK",
                )
            else:
                exito, msg = firmar_orden_sx_bet_v3(
                    market_hash=id_ref,
                    indice_lado=idx_lado,
                    cuota_decimal=cuota_viva,
                    tamano_usd=stake_pata_exacto,
                    tipo_orden="IOC",
                )
            if exito:
                estados_orden.append(f"ORDEN_REAL ({casa_p} {sel_p}: {msg})")
            elif "Paper Trading" in msg:
                estados_orden.append(f"PAPER ({casa_p} {sel_p} @ {cuota_viva:.2f})")
            else:
                todo_ejecutado = False
                logger.info("Pata %s no ejecutada en %s (%s): %s", casa_p, cand["Evento"], sel_p, msg)
                break

        # Si al menos 1 orden salió a la red, registrarla SIEMPRE en el CSV para que jamás se repita en el próximo minuto
        if not estados_orden:
            continue
        reg_ejecucion = {
            "Timestamp_UTC": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "Clave_Unica": clave,
            "Tipo_Estrategia": cand["Tipo_Estrategia"],
            "Deporte": cand["Deporte"],
            "Evento": cand["Evento"],
            "Mercado": cand["Mercado"],
            "Pata_1": f"[{cand['Pata_1_Casa']}] {cand['Pata_1_Seleccion']} @ {cand['Pata_1_Cuota']:.3f}",
            "Pata_2": f"[{cand['Pata_2_Casa']}] {cand['Pata_2_Seleccion']} @ {cand['Pata_2_Cuota']:.3f}",
            "ROI_Esperado_Pct": cand["ROI_Esperado_Pct"],
            "Stake_Por_Pata_USD": stake_por_pata_usd,
            "Estado_Ejecucion": " | ".join(estados_orden),
            "Detalle_Libro_Vivo": " ; ".join(detalles_verif),
        }
        nuevas_ejecuciones.append(reg_ejecucion)

    if nuevas_ejecuciones:
        df_nuevas = pd.DataFrame(nuevas_ejecuciones)
        if RUTA_HISTORIAL_SUREBETS.exists():
            df_prev = pd.read_csv(RUTA_HISTORIAL_SUREBETS)
            df_out = pd.concat([df_prev, df_nuevas], ignore_index=True)
        else:
            df_out = df_nuevas
        df_out.to_csv(RUTA_HISTORIAL_SUREBETS, index=False, encoding="utf-8-sig")

    return nuevas_ejecuciones
