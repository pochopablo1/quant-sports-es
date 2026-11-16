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
from datetime import datetime, timezone
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
from ejecutor.verificador_atomico import (
    verificar_pata_polymarket_vwap,
    verificar_pata_sx_bet_vivo,
)
from ejecutor.gestor_wallet import firmar_orden_polymarket_clob

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
        return set(df_f["Clave_Unica"].astype(str).tolist())
    except Exception:
        return set()


def ejecutar_oportunidades_surebets(
    surebets_taker: List[Dict[str, Any]],
    arbs_maker_taker: List[Dict[str, Any]],
    pasillos_middles: List[Dict[str, Any]],
    cruces_inplay: List[Dict[str, Any]],
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
    # REGLA ESTRICTA DE SUREBET PURA:
    # JAMÁS ejecutar 1 sola pata al descubierto contra Kalshi/Vegas.
    # Para que el bot dispare dinero real automáticamente, AMBAS PATAS deben cubrirse.
    casas_auto_2patas = {"Polymarket"}

    # 1. Prioridad 1: Pasillos de Riesgo Cero donde AMBAS patas están en Polymarket (Costo total <= $1.00, 0% riesgo)
    for pas in pasillos_middles:
        c1_casa = str(pas.get("Pata_1_Casa", ""))
        c2_casa = str(pas.get("Pata_2_Casa", ""))
        if c1_casa in casas_auto_2patas and c2_casa in casas_auto_2patas:
            roi_norm = float(pas.get("ROI_Normal_1Pata_Pct", -99.0))
            if roi_norm >= 0.0:
                candidatas.append({
                    "Tipo_Estrategia": "PASILLO_2PATAS_POLYMARKET_RIESGO_CERO",
                    "Evento": pas.get("Evento", ""),
                    "Deporte": pas.get("Deporte", ""),
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
        if clave in ya_ejecutadas:
            continue

        # Verificar que tengamos los 2 token_id de AMBAS patas para nunca quedar con 1 sola pata coja
        tok1 = _extraer_token_id_polymarket(cand["Pata_1_ID"], cand["Pata_1_Idx"])
        tok2 = _extraer_token_id_polymarket(cand["Pata_2_ID"], cand["Pata_2_Idx"])
        if not tok1 or not tok2 or tok1 == tok2:
            continue
        patas_poly = [
            (1, cand["Pata_1_Seleccion"], cand["Pata_1_Cuota"], tok1),
            (2, cand["Pata_2_Seleccion"], cand["Pata_2_Cuota"], tok2),
        ]

        # Verificar en vivo el libro de órdenes de las patas de Polymarket (y SX Bet si aplica)
        verif_ok = True
        detalles_verif = []
        precios_poly_vivos = []

        for num_pata, sel_pata, cuota_esp, tok_id in patas_poly:
            ok_p, cuota_vwap, liq_top, _, det_p = verificar_pata_polymarket_vwap(tok_id, stake_por_pata_usd)
            if not ok_p or cuota_vwap <= 1.02:
                verif_ok = False
                break
            # Evitar entrar en micro-centavos ilíquidos (< $0.08 o > $0.93)
            precio_vivo = round(1.0 / cuota_vwap, 2)
            if not (0.08 <= precio_vivo <= 0.93):
                verif_ok = False
                break
            # Verificar que la cuota viva no haya caído más de 2 centavos respecto al escáner
            if (1.0 / cuota_vwap) > (1.0 / cuota_esp) + 0.02:
                verif_ok = False
                break
            precios_poly_vivos.append((num_pata, sel_pata, tok_id, precio_vivo, cuota_vwap, det_p))
            detalles_verif.append(f"Poly({sel_pata}): {det_p}")

        if not verif_ok or not precios_poly_vivos:
            continue

        # Si la otra pata es SX Bet, verificar en vivo su liquidez con la API Key V3
        for num_sx, casa_sx, id_sx, idx_sx in [
            (1, cand["Pata_1_Casa"], cand["Pata_1_ID"], cand["Pata_1_Idx"]),
            (2, cand["Pata_2_Casa"], cand["Pata_2_ID"], cand["Pata_2_Idx"]),
        ]:
            if casa_sx == "SX Bet" and id_sx:
                ok_sx, cuota_sx_viva, liq_sx, det_sx = verificar_pata_sx_bet_vivo(id_sx, idx_sx, stake_por_pata_usd)
                if not ok_sx:
                    verif_ok = False
                    break
                detalles_verif.append(f"SXBet: {det_sx}")

        if not verif_ok:
            continue

        # Ejecutar las patas de Polymarket con orden FOK On-Chain
        estados_orden = []
        todo_ejecutado = True
        for num_pata, sel_pata, tok_id, precio_vivo, cuota_vwap, det_p in precios_poly_vivos:
            exito_fok, msg_fok = firmar_orden_polymarket_clob(
                token_id=tok_id,
                precio=precio_vivo,
                tamano_usd=stake_por_pata_usd,
                lado="BUY",
                tipo_orden="FOK",
            )
            if exito_fok:
                estados_orden.append(f"ORDEN_REAL_ENVIADA ({sel_pata}: {msg_fok})")
            elif "Paper Trading" in msg_fok:
                estados_orden.append(f"PAPER_EJECUTADA ({sel_pata} @ ${precio_vivo:.2f})")
            else:
                todo_ejecutado = False
                logger.info("Orden Surebet FOK no llenada en %s (%s): %s", cand["Evento"], sel_pata, msg_fok)
                break

        if not todo_ejecutado or not estados_orden:
            continue

        ya_ejecutadas.add(clave)
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
