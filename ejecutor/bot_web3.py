"""
Módulo Ejecutor Web3 y Verificador de Orderbook al Milisegundo (Paso B).
Diseñado para operar sobre las plataformas de 0% / baja comisión con una sola Wallet EVM:
- Polymarket (Polygon CLOB)
- SX Bet (SX Rollup / Arbitrum CLOB v3)
- Limitless Exchange (Base L2 CLOB)

Características principales:
1. `MODO_SIMULACION = True` por defecto (Paper Trading Realista):
   Consulta el libro de órdenes real (`/book` en Polymarket o `/orders-v3/odds/best` en SX Bet)
   un instante antes de disparar, calcula el precio promedio ponderado (VWAP) según tu Stake en USD,
   verifica que después del slippage el EV siga siendo positivo (`>= ev_minimo_pct`) y registra
   la ejecución en `datos/historial_ejecuciones.csv`.
2. Cuando configures `PRIVATE_KEY_WEB3` en `.env` y pases `--ejecucion-real`, firma y envía
   la orden FOK (Fill-or-Kill) al CLOB correspondiente.
"""
import argparse
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import sys
from typing import Dict, Any, List, Tuple
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from configuracion import DIRECTORIO_DATOS, SX_API_KEY
from estrategias.motor_cuantitativo import _evento_en_juego_o_pasado
from ejecutor.gestor_wallet import firmar_orden_polymarket_clob

logger = logging.getLogger("EjecutorWeb3")

RUTA_ACCIONABLES = DIRECTORIO_DATOS / "oportunidades_accionables.csv"
RUTA_HISTORIAL_EJECUCIONES = DIRECTORIO_DATOS / "historial_ejecuciones.csv"

URL_POLY_BOOK = "https://clob.polymarket.com/book"
URL_SX_BEST_ODDS = "https://api.sx.bet/orders-v3/odds/best"
URL_LIMITLESS_MARKET = "https://api.limitless.exchange/markets"


def verificar_orderbook_polymarket_en_vivo(
    id_mercado_compuesto: str,
    indice_lado: int,
    stake_usd: float,
) -> Tuple[bool, float, float, str]:
    """
    Consulta `https://clob.polymarket.com/book?token_id=...` en tiempo real y calcula:
      (ejecutable_ok, cuota_efectiva_vwap, liquidez_disponible_mejor_nivel_usd, detalle)
    """
    partes = str(id_mercado_compuesto).split("::")
    if len(partes) < 3:
        return False, 0.0, 0.0, "ID_Mercado no contiene clobTokenIds (actualizar extracción)"

    token_id = partes[1] if int(indice_lado) == 1 else partes[2]
    try:
        resp = requests.get(URL_POLY_BOOK, params={"token_id": token_id}, timeout=8)
        if resp.status_code != 200:
            return False, 0.0, 0.0, f"HTTP {resp.status_code} en Polymarket CLOB"
        libro = resp.json()
    except Exception as exc:
        return False, 0.0, 0.0, f"Error de red Polymarket CLOB: {exc}"

    asks = libro.get("asks") or []
    if not asks:
        return False, 0.0, 0.0, "Sin órdenes Ask activas en el libro"

    # Ordenar asks de menor precio (mejor cuota para el comprador Taker) a mayor precio
    niveles_ask = sorted(
        [(float(a["price"]), float(a["size"])) for a in asks if float(a.get("price", 0)) > 0],
        key=lambda x: x[0],
    )
    if not niveles_ask:
        return False, 0.0, 0.0, "Libro Ask vacío"

    mejor_precio, mejor_tamano_contratos = niveles_ask[0]
    liquidez_mejor_nivel_usd = round(mejor_precio * mejor_tamano_contratos, 2)

    # Calcular VWAP para cubrir `stake_usd`
    usd_restante = stake_usd
    contratos_acumulados = 0.0
    usd_gastado = 0.0

    for precio_nivel, contratos_nivel in niveles_ask:
        costo_nivel_usd = precio_nivel * contratos_nivel
        if costo_nivel_usd >= usd_restante:
            contratos_comprados = usd_restante / precio_nivel
            contratos_acumulados += contratos_comprados
            usd_gastado += usd_restante
            usd_restante = 0.0
            break
        else:
            contratos_acumulados += contratos_nivel
            usd_gastado += costo_nivel_usd
            usd_restante -= costo_nivel_usd

    if usd_restante > 0.01 or usd_gastado <= 0:
        return (
            False,
            0.0,
            liquidez_mejor_nivel_usd,
            f"Liquidez insuficiente para cubrir ${stake_usd:.2f} USD",
        )

    precio_vwap = usd_gastado / contratos_acumulados
    cuota_efectiva = round(1.0 / precio_vwap, 4)
    return (
        True,
        cuota_efectiva,
        liquidez_mejor_nivel_usd,
        f"Token={token_id[:10]}... | Ask_Top={mejor_precio} (${liquidez_mejor_nivel_usd:,.2f} USD disponibles)",
    )


def verificar_orderbook_sx_bet_en_vivo(
    market_hash: str,
    indice_lado: int,
    stake_usd: float,
) -> Tuple[bool, float, float, str]:
    """
    Consulta `/orders-v3/odds/best` en SX Bet en tiempo real para verificar cuota y volumen disponible.
    """
    headers = {"Accept": "application/json"}
    if SX_API_KEY:
        headers["x-sx-api-key"] = SX_API_KEY

    try:
        resp = requests.get(
            URL_SX_BEST_ODDS,
            params={"marketHashes": market_hash, "showTakerPerspective": "true"},
            headers=headers,
            timeout=8,
        )
        if resp.status_code != 200:
            return False, 0.0, 0.0, f"HTTP {resp.status_code} en SX Bet"
        datos = resp.json().get("data", {})
        best_list = datos.get("bestOdds", []) if isinstance(datos, dict) else datos
        item = best_list[0] if (isinstance(best_list, list) and best_list) else {}
    except Exception as exc:
        return False, 0.0, 0.0, f"Error de red SX Bet: {exc}"

    nodo_lado = item.get("outcomeOne" if int(indice_lado) == 1 else "outcomeTwo") or {}
    prob_raw = nodo_lado.get("percentageOdds")
    vol_raw = nodo_lado.get("availableVolume") or nodo_lado.get("size") or 0

    if not prob_raw:
        return False, 0.0, 0.0, "Sin cotización activa en SX Bet"

    prob = float(prob_raw) / 1e20
    liq_usd = round(float(vol_raw) / 1e6, 2)
    if prob <= 0.001 or prob >= 0.999:
        return False, 0.0, liq_usd, "Probabilidad fuera de rango"

    cuota_efectiva = round(1.0 / prob, 4)
    if liq_usd < stake_usd:
        return False, cuota_efectiva, liq_usd, f"Liquidez insuficiente en SX Bet (${liq_usd:.2f} < ${stake_usd:.2f})"

    return True, cuota_efectiva, liq_usd, f"Hash={market_hash[:10]}... | Liq=${liq_usd:,.2f} USD"


def verificar_orderbook_kalshi_en_vivo(
    ticker: str,
    indice_lado: int,
    stake_usd: float,
) -> Tuple[bool, float, float, str]:
    """Consulta el mercado individual en Kalshi API v2 en tiempo real para verificar ask y liquidez."""
    try:
        resp = requests.get(
            f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}",
            timeout=8,
        )
        if resp.status_code != 200:
            return False, 0.0, 0.0, f"HTTP {resp.status_code} en Kalshi market {ticker}"
        mkt = resp.json().get("market") or {}
        ask_key = "yes_ask_dollars" if int(indice_lado) == 1 else "no_ask_dollars"
        size_key = "yes_ask_size_fp" if int(indice_lado) == 1 else "yes_bid_size_fp"
        ask = float(mkt.get(ask_key) or 0.0)
        size = float(mkt.get(size_key) or 0.0)
        if not (0.01 < ask < 0.99):
            return False, 0.0, 0.0, "Sin punta Ask válida en Kalshi"
        liq_usd = round(ask * size, 2)
        cuota = round(1.0 / ask, 4)
        if liq_usd < stake_usd:
            return False, cuota, liq_usd, f"Liquidez insuficiente en Kalshi (${liq_usd:.2f} < ${stake_usd:.2f})"
        return True, cuota, liq_usd, f"Kalshi {ticker} Ask={ask} (${liq_usd:.2f} USD)"
    except Exception as exc:
        return False, 0.0, 0.0, f"Error Kalshi en vivo: {exc}"


def _verificar_pata_individual(
    plat: str,
    id_mkt: str,
    idx_lado: int,
    stake_usd: float,
    cuota_fallback: float,
    liq_fallback: float,
) -> Tuple[bool, float, float, str]:
    """Verifica una pata individual en el orderbook en vivo de Polymarket, SX Bet o Kalshi."""
    if plat == "Polymarket":
        return verificar_orderbook_polymarket_en_vivo(id_mkt, idx_lado, stake_usd)
    if plat == "SX Bet":
        return verificar_orderbook_sx_bet_en_vivo(id_mkt, idx_lado, stake_usd)
    if plat == "Kalshi":
        return verificar_orderbook_kalshi_en_vivo(id_mkt, idx_lado, stake_usd)
    return False, 0.0, 0.0, f"Plataforma sin verificador de orderbook en vivo ({plat})"


def ejecutar_barrido_oportunidades(
    ev_minimo_pct: float = 0.40,
    modo_simulacion: bool = True,
    max_ordenes: int = 30,
) -> List[Dict[str, Any]]:
    """
    Lee `datos/oportunidades_accionables.csv`, procesa los Motores del usuario:
      - MOTOR 1 (Value Favorito 1.16 <= Cuota <= 1.85, EV >= 0.40%)
      - MOTOR 2 (Surebet Arbitraje >= 1.0%)
    verifica el orderbook en vivo al milisegundo y registra el plan de rotación diaria.
    """
    if not RUTA_ACCIONABLES.exists():
        logger.error("No existe %s. Ejecuta primero `python main.py`.", RUTA_ACCIONABLES)
        return []

    df = pd.read_csv(RUTA_ACCIONABLES)
    if df.empty:
        logger.info("No hay oportunidades accionables en este momento.")
        return []

    # Priorizar Polymarket (ejecución real on-chain) y ordenar de mayor a menor ventaja matemática
    df = df[df["Ventaja_Neta_Pct"] >= ev_minimo_pct].copy()
    if df.empty:
        logger.info("No hay oportunidades que superen el EV mínimo de %.2f%%.", ev_minimo_pct)
        return []
    df["_es_poly"] = (df["Plataforma_Entrada"].astype(str) == "Polymarket").astype(int)
    df = df.sort_values(by=["_es_poly", "Ventaja_Neta_Pct"], ascending=[False, False])
    if not modo_simulacion:
        df = df[df["Plataforma_Entrada"].astype(str) == "Polymarket"]
    candidatas = df.head(max_ordenes)

    ahora_iso = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Candado Global Anti-Duplicados:
    # En modo real solo bloquea contra órdenes reales previas (jamás deja que un test Paper bloquee una orden Real)
    claves_ejecutadas_historico = set()
    eventos_ejecutados_historico = set()
    if RUTA_HISTORIAL_EJECUCIONES.exists():
        try:
            df_prev = pd.read_csv(RUTA_HISTORIAL_EJECUCIONES)
            if not df_prev.empty and "Estado_Orden" in df_prev.columns:
                patron_prev = "ORDEN_REAL|LISTA_SUREBET_REAL" if not modo_simulacion else "OK|EJECUTAD|ACTIVO"
                df_aprobadas = df_prev[
                    df_prev["Estado_Orden"].astype(str).str.contains(patron_prev, na=False)
                ]
                for _, r_ant in df_aprobadas.iterrows():
                    ev_ant = str(r_ant.get("Evento", "")).strip()
                    sel_base_ant = str(r_ant.get("Seleccion", "")).split(" (Prob:")[0].strip()
                    claves_ejecutadas_historico.add(
                        f"{r_ant.get('Estrategia')}|{r_ant.get('Plataforma')}|{ev_ant}|{sel_base_ant}"
                    )
                    if ev_ant:
                        eventos_ejecutados_historico.add(ev_ant.lower())
        except Exception:
            pass

    registros_ejecucion: List[Dict[str, Any]] = []

    for _, fila in candidatas.iterrows():
        estrategia = str(fila.get("Estrategia", "MOTOR_1"))
        estrategia_corta = estrategia.split(" ")[0]
        plat = str(fila["Plataforma_Entrada"])
        evento = str(fila["Evento"]).strip()
        mercado_linea = str(fila["Mercado_y_Linea"])
        seleccion = str(fila["Seleccion_Apostar"])
        sel_base = seleccion.split(" (Prob:")[0].strip()
        clave_unica = f"{estrategia_corta}|{plat}|{evento}|{sel_base}"

        # Bloquear si ya se apostó este partido en cualquier día anterior o en este mismo barrido (Máximo 1 tiro por partido)
        if clave_unica in claves_ejecutadas_historico or evento.lower() in eventos_ejecutados_historico:
            continue

        # Candado Pre-Vuelo: bloquear si el partido ya comenzó o faltan menos de 10 minutos
        if _evento_en_juego_o_pasado(fila.get("Inicio_UTC")):
            continue

        id_mkt = str(fila["ID_Mercado"])
        val_idx = fila.get("Indice_Lado")
        idx_lado = int(val_idx) if pd.notna(val_idx) else 1
        cuota_justa = float(fila["Cuota_Justa_Ref"])
        stake_usd = max(2.50, min(float(fila["Stake_Kelly_Sugerido_USD"]), 6.00))
        plan_salida = str(fila.get("Plan_Salida_Trading", "Mantener al cierre"))
        liq_inicial = float(fila["Liquidez_Punta_USD"])
        cuota_detectada = float(fila["Cuota_Neta"])

        # Caso A: MOTOR 2 SUREBET (2 patas simultáneas separadas por '||')
        if "MOTOR_2_SUREBET" in estrategia and "||" in id_mkt:
            pata1_str, pata2_str = id_mkt.split("||", 1)
            partes_p1 = pata1_str.split("::")
            partes_p2 = pata2_str.split("::")
            plat_1, idx_1 = partes_p1[0], int(partes_p1[-1])
            id_1 = "::".join(partes_p1[1:-1])
            plat_2, idx_2 = partes_p2[0], int(partes_p2[-1])
            id_2 = "::".join(partes_p2[1:-1])

            suma_inv_det = (1.0 / cuota_detectada) + (1.0 / cuota_justa)
            stake_1 = round(stake_usd * ((1.0 / cuota_detectada) / suma_inv_det), 2)
            stake_2 = round(stake_usd - stake_1, 2)

            ok1, c1_vivo, liq1_vivo, det1 = _verificar_pata_individual(
                plat_1, id_1, idx_1, stake_1, cuota_detectada, liq_inicial
            )
            ok2, c2_vivo, liq2_vivo, det2 = _verificar_pata_individual(
                plat_2, id_2, idx_2, stake_2, cuota_justa, liq_inicial
            )

            if ok1 and ok2 and c1_vivo > 1.01 and c2_vivo > 1.01:
                suma_inv_vivo = (1.0 / c1_vivo) + (1.0 / c2_vivo)
                roi_vivo_pct = round(((1.0 / suma_inv_vivo) - 1.0) * 100.0, 2)
                if roi_vivo_pct >= 0.8:
                    estado = "SUREBET_EJECUTADA_2_PATAS (PAPER)" if modo_simulacion else "LISTA_SUREBET_REAL"
                else:
                    estado = f"DESCARTADA_SUREBET (ROI vivo bajó a {roi_vivo_pct}%)"
            else:
                roi_vivo_pct = 0.0
                estado = f"DESCARTADA_ORDERBOOK_SUREBET ({det1} | {det2})"

            cuota_vwap = c1_vivo
            ev_vivo_pct = roi_vivo_pct
            liq_vivo = min(liq1_vivo, liq2_vivo)
            detalle_libro = f"P1[{plat_1}]: {det1} || P2[{plat_2}]: {det2}"

        # Caso B: MOTOR 1 (Value Favorito <= 1.85)
        else:
            # En Polymarket el mínimo técnico del CLOB es 5 shares; ajustar stake_usd real antes de consultar VWAP
            if plat == "Polymarket" and cuota_detectada > 1.01:
                min_usd_5_shares = round(5.0 * round(1.0 / cuota_detectada, 2), 2)
                stake_usd = round(max(stake_usd, min_usd_5_shares), 2)

            ok_libro, cuota_vwap, liq_vivo, detalle_libro = _verificar_pata_individual(
                plat, id_mkt, idx_lado, stake_usd, cuota_detectada, liq_inicial
            )
            if not ok_libro or cuota_vwap <= 1.01:
                estado = f"DESCARTADA_EN_ORDERBOOK ({detalle_libro})"
                ev_vivo_pct = 0.0
            else:
                if plat == "Polymarket":
                    precio_grid = round(1.0 / cuota_vwap, 2)
                    contratos_reales = max(5.0, round(stake_usd / precio_grid, 2))
                    stake_usd = round(contratos_reales * precio_grid, 2)

                prob_justa = 1.0 / cuota_justa
                if "MOTOR_1_VALUE_FAVORITO" in estrategia:
                    ev_vivo_pct = round(((cuota_vwap * prob_justa) - 1.0) * 100.0, 2)
                    if cuota_vwap > 1.85 or cuota_vwap < 1.16:
                        estado = f"DESCARTADA_FUERA_RANGO_FAVORITO ({cuota_vwap} fuera de [1.16, 1.85])"
                    elif stake_usd > 6.00:
                        estado = f"DESCARTADA_STAKE_MINIMO_5_SHARES (${stake_usd:.2f} supera tope de $6.00 USD)"
                    elif ev_vivo_pct >= max(0.35, ev_minimo_pct):
                        if not modo_simulacion:
                            if plat == "Polymarket":
                                partes_tok = str(id_mkt).split("::")
                                tok_id = partes_tok[1] if int(idx_lado) == 1 else partes_tok[2]
                                ok_real, msg_real = firmar_orden_polymarket_clob(
                                    tok_id, 1.0 / cuota_vwap, stake_usd, lado="BUY", tipo_orden="FOK"
                                )
                                estado = "ORDEN_REAL_FOK_EJECUTADA" if ok_real else f"FALLO_ORDEN_REAL ({msg_real})"
                            else:
                                estado = f"OMITIDA_MODO_REAL_SOLO_POLYMARKET ({plat})"
                        else:
                            estado = "FAVORITO_EJECUTADO_OK (PAPER)"
                    else:
                        estado = f"DESCARTADA_POR_SLIPPAGE (EV vivo bajó a {ev_vivo_pct}%)"
                else:
                    estado = "DESCARTADA_MOTOR_3_DESACTIVADO_EN_V2"
                    ev_vivo_pct = 0.0

        if any(k in estado for k in ("OK", "EJECUTAD", "ACTIVO")):
            claves_ejecutadas_historico.add(clave_unica)
            eventos_ejecutados_historico.add(evento.lower())

        registros_ejecucion.append(
            {
                "Timestamp_UTC": ahora_iso,
                "Estrategia": estrategia.split(" ")[0],
                "Estado_Orden": estado,
                "Plataforma": plat,
                "Evento": evento,
                "Mercado": mercado_linea,
                "Seleccion": seleccion,
                "Stake_USD": stake_usd,
                "Cuota_Detectada": cuota_detectada,
                "Cuota_VWAP_Real_Libro": cuota_vwap,
                "Cuota_Justa_Ref": cuota_justa,
                "Ventaja_Viva_Pct": ev_vivo_pct,
                "Liquidez_Punta_Vivo_USD": liq_vivo,
                "Plan_Salida_Trading": plan_salida,
                "Detalle_Orderbook": detalle_libro,
            }
        )

    if registros_ejecucion:
        df_nuevos = pd.DataFrame(registros_ejecucion)
        if RUTA_HISTORIAL_EJECUCIONES.exists():
            df_ant = pd.read_csv(RUTA_HISTORIAL_EJECUCIONES)
            df_total = pd.concat([df_ant, df_nuevos], ignore_index=True)
        else:
            df_total = df_nuevos
        df_total.to_csv(RUTA_HISTORIAL_EJECUCIONES, index=False, encoding="utf-8-sig")

    return registros_ejecucion


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Bot Ejecutor Web3 Triple Motor y Verificador de Orderbook en Vivo")
    parser.add_argument("--ev-min", type=float, default=1.0, help="Ventaja neta minima en %% para verificar/ejecutar")
    parser.add_argument("--max-ordenes", type=int, default=25, help="Maximo de ordenes a verificar por barrido")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    resultados = ejecutar_barrido_oportunidades(
        ev_minimo_pct=args.ev_min,
        modo_simulacion=True,
        max_ordenes=args.max_ordenes,
    )
    print("\n" + "=" * 105)
    print(f"🤖 REPORTE DEL EJECUTOR TRIPLE MOTOR EN VIVO (Total verificadas en Orderbook: {len(resultados)})")
    print("=" * 105)
    if resultados:
        df_res = pd.DataFrame(resultados)
        cols = [
            "Estrategia",
            "Estado_Orden",
            "Plataforma",
            "Evento",
            "Seleccion",
            "Stake_USD",
            "Cuota_VWAP_Real_Libro",
            "Ventaja_Viva_Pct",
            "Plan_Salida_Trading",
        ]
        print(df_res[cols].to_string(index=False))
        ok_df = df_res[df_res["Estado_Orden"].str.contains("OK|EJECUTAD|ACTIVO", na=False)]
        capital_rotado = ok_df["Stake_USD"].sum() if not ok_df.empty else 0.0
        ganancia_esp = (ok_df["Stake_USD"] * (ok_df["Ventaja_Viva_Pct"] / 100.0)).sum() if not ok_df.empty else 0.0
        print("-" * 105)
        print(
            f"💰 RESUMEN DE ROTACIÓN EN ESTE BARRIDO: {len(ok_df)} micro-apuestas aprobadas | "
            f"Capital rotado: ${capital_rotado:.2f} USD | Ganancia matemática esperada: +${ganancia_esp:.2f} USD"
        )
        print(f"📁 Historial guardado en: {RUTA_HISTORIAL_EJECUCIONES}")
    print("=" * 105 + "\n")
