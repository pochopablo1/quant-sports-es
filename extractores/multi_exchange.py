"""
Extractor Multi-Plataforma en Paralelo para Arbitraje y Surebets (`quant_surebets_es`).
======================================================================================
Extrae simultáneamente precios Taker (Ask), precios Maker (Bid + 1 tick), liquidez en USD
y estructura de triángulos 1X2 internos desde:
  1. Polymarket (Polygon CLOB - 2-Way + Triángulos 1X2 Internos)
  2. SX Bet (SX Rollup / Arbitrum CLOB v3 - 0% Taker Fee en simples)
  3. Limitless Exchange (Base L2 CLOB - 0% Maker Fee)
  4. Overtime Markets (Optimism / Arbitrum / Base Sports AMM - 0% Fee extra)
  5. Predict.fun (BNB Chain CLOB)
  6. Kalshi (CFTC Regulated CLOB - Bid/Ask completos y escaleras de Spreads/Totales)
  7. Futuur (USDC Orderbook)
  8. Vegas Live Consensus (Action Network + ESPN/DraftKings como ancla de precios)
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import sys
from typing import Dict, Any, List, Tuple
import requests

# Permitir reutilizar extractores base probados si están disponibles
RUTA_SUREBETS = Path(__file__).resolve().parent.parent
RUTA_SPORTS = RUTA_SUREBETS.parent / "quant_sports_es"
if str(RUTA_SUREBETS) not in sys.path:
    sys.path.insert(0, str(RUTA_SUREBETS))
if RUTA_SPORTS.exists() and str(RUTA_SPORTS) not in sys.path:
    sys.path.append(str(RUTA_SPORTS))

from configuracion import SX_API_KEY

logger = logging.getLogger("ExtractorSurebets")


def extraer_polymarket_con_triangulos_y_bids(limite: int = 100, paginas: int = 6) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Extrae mercados deportivos de Polymarket Gamma API de forma rápida y optimizada:
    Reutiliza el extractor base normalizado para obtener todos los 2-way (Moneyline, Spreads, Totals)
    y eventos 1X2 sin duplicar peticiones HTTP.
    """
    try:
        from extractores.polymarket import extraer_polymarket
        mercados_2way = extraer_polymarket(limite=limite, paginas=paginas)
        return mercados_2way, []
    except Exception as exc:
        logger.warning("Fallo importando extraer_polymarket base: %s", exc)
        return [], []


def extraer_todas_las_plataformas_en_paralelo() -> Dict[str, Any]:
    """
    Ejecuta en paralelo EXCLUSIVAMENTE las plataformas donde tenemos billeteras,
    balance y trading automático 100% activo:
      1. Polymarket (Polygon CLOB - 2-Way + Triángulos 1X2 Internos)
      2. SX Bet (SX Rollup V3 CLOB - 0% Taker Fee)
      3. Limitless Exchange (Base L2 CLOB - 0% Maker Fee)
    (Eliminadas por completo casas informativas o sin trading Web3: Kalshi, Vegas, Futuur, Manifold, Smarkets).
    """
    from extractores.sx_bet import extraer_sx_bet
    from extractores.limitless import extraer_limitless
    from normalizador.emparejador import normalizar_filas

    tareas = {
        "SX Bet": lambda: extraer_sx_bet(tamano_pagina=100, max_paginas=8),
        "Limitless": lambda: extraer_limitless(max_paginas=10),
    }

    resultados_crudos: List[Dict[str, Any]] = []
    triangulos_poly: List[Dict[str, Any]] = []
    conteo_plataformas: Dict[str, int] = {}

    with ThreadPoolExecutor(max_workers=3) as pool:
        fut_poly = pool.submit(extraer_polymarket_con_triangulos_y_bids, 100, 6)
        futuros = {pool.submit(fn): nombre for nombre, fn in tareas.items()}

        try:
            mkts_poly, triangulos_poly = fut_poly.result(timeout=45)
            resultados_crudos.extend(mkts_poly)
            conteo_plataformas["Polymarket"] = len(mkts_poly)
        except Exception as exc:
            logger.warning("Aviso extrayendo Polymarket: %s", exc)
            conteo_plataformas["Polymarket"] = 0

        for fut in as_completed(futuros):
            nombre = futuros[fut]
            try:
                filas = fut.result(timeout=45) or []
                resultados_crudos.extend(filas)
                conteo_plataformas[nombre] = len(filas)
            except Exception as exc:
                logger.warning("Aviso extrayendo %s: %s", nombre, exc)
                conteo_plataformas[nombre] = 0

    mercados_normalizados = normalizar_filas(resultados_crudos)
    return {
        "mercados_normalizados": mercados_normalizados,
        "triangulos_1x2": triangulos_poly,
        "conteo_plataformas": conteo_plataformas,
    }
