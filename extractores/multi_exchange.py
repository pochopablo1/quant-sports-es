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


def extraer_overtime_markets_v2() -> List[Dict[str, Any]]:
    """
    Intenta consultar el feed de Overtime Markets V2 (Base 8453 / Arbitrum 42161 / Optimism 10 Sports AMM).
    Overtime no cobra fee de taker aparte (el margen está incluido en la cuota on-chain).
    """
    filas: List[Dict[str, Any]] = []
    urls_candidatas = [
        "https://api.overtime.io/overtime-v2/networks/8453/markets",
        "https://api.overtime.io/overtime-v2/networks/42161/markets",
        "https://api.overtimemarkets.xyz/overtime-v2/networks/8453/markets",
        "https://api.overtimemarkets.xyz/overtime-v2/networks/42161/markets",
    ]
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    for url in urls_candidatas:
        try:
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code != 200:
                continue
            datos = resp.json()
            if not isinstance(datos, list):
                continue
            for item in datos[:150]:
                if not isinstance(item, dict) or item.get("isOpen") is False:
                    continue
                local = str(item.get("homeTeam") or "").strip()
                vis = str(item.get("awayTeam") or "").strip()
                odds = item.get("odds") or []
                if not local or not vis or len(odds) < 2:
                    continue
                c1 = float(odds[0].get("decimal") or 0.0) if isinstance(odds[0], dict) else 0.0
                c2 = float(odds[1].get("decimal") or 0.0) if isinstance(odds[1], dict) else 0.0
                if c1 > 1.02 and c2 > 1.02:
                    filas.append({
                        "Plataforma": "Overtime",
                        "Deporte": str(item.get("sport") or "Deportes"),
                        "Liga": str(item.get("leagueName") or "General"),
                        "Evento": f"{local} vs {vis}",
                        "Inicio_UTC": str(item.get("maturityDate") or ""),
                        "Tipo_Mercado": "Ganador (Moneyline)",
                        "Linea": "N/A",
                        "Lado_1": local,
                        "Cuota_Taker_1": round(c1, 4),
                        "Liquidez_1_USD": 500.0,
                        "Lado_2": vis,
                        "Cuota_Taker_2": round(c2, 4),
                        "Liquidez_2_USD": 500.0,
                        "Overround_Libro_Pct": round(((1.0 / c1) + (1.0 / c2) - 1.0) * 100.0, 2),
                        "ID_Mercado": str(item.get("gameId") or ""),
                    })
        except Exception:
            continue
    return filas


def extraer_manifold_deportes() -> List[Dict[str, Any]]:
    """Extrae mercados deportivos binarios de Manifold Markets para referencia cruzada adicional."""
    filas: List[Dict[str, Any]] = []
    try:
        resp = requests.get(
            "https://api.manifold.markets/v0/search-markets",
            params={"term": "vs", "filter": "open", "contractType": "BINARY", "limit": "100"},
            timeout=6,
        )
        if resp.status_code != 200:
            return filas
        for m in resp.json():
            preg = str(m.get("question") or "").strip()
            if " vs " not in preg.lower() and " vs. " not in preg.lower():
                continue
            p = float(m.get("probability") or 0.0)
            if not (0.05 < p < 0.95):
                continue
            partes = preg.replace(" vs. ", " vs ").split(" vs ")
            if len(partes) != 2:
                continue
            eq1 = partes[0].split(":")[-1].replace("Will ", "").strip()
            eq2 = partes[1].split("?")[0].replace("win", "").strip()
            c1 = round(1.0 / p, 4)
            c2 = round(1.0 / (1.0 - p), 4)
            filas.append({
                "Plataforma": "Manifold",
                "Deporte": "Deportes",
                "Liga": "General",
                "Evento": f"{eq1} vs {eq2}",
                "Inicio_UTC": str(m.get("closeTime") or ""),
                "Tipo_Mercado": "Ganador (Moneyline)",
                "Linea": "N/A",
                "Lado_1": eq1,
                "Cuota_Taker_1": c1,
                "Liquidez_1_USD": float(m.get("totalLiquidity") or 100.0),
                "Lado_2": eq2,
                "Cuota_Taker_2": c2,
                "Liquidez_2_USD": float(m.get("totalLiquidity") or 100.0),
                "Overround_Libro_Pct": 0.0,
                "ID_Mercado": str(m.get("id") or ""),
            })
    except Exception:
        pass
    return filas


def extraer_oraculo_inplay_en_vivo() -> List[Dict[str, Any]]:
    """
    Extrae cuotas EN JUEGO (In-Play: `status == 'inprogress'` / `state == 'in'`)
    desde Action Network y ESPN/DraftKings para cruzar contra Polymarket, Kalshi, SX Bet y Limitless
    mientras los partidos se están jugando en vivo.
    """
    from extractores.oraculo_gratis import LIGAS_ACTION_NETWORK, LIGAS_ESPN_DRAFTKINGS, _americana_a_decimal
    from configuracion import calcular_overround_pct

    filas_inplay: List[Dict[str, Any]] = []
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    # 1. Action Network In-Play ('inprogress')
    for slug_liga, deporte_es, liga_es in LIGAS_ACTION_NETWORK:
        url = f"https://api.actionnetwork.com/web/v1/scoreboard/{slug_liga}"
        try:
            resp = requests.get(url, headers=headers, timeout=6)
            if resp.status_code != 200:
                continue
            juegos = resp.json().get("games") or []
        except Exception:
            continue

        for g in juegos:
            if str(g.get("status", "")).lower() != "inprogress":
                continue
            equipos = {t.get("id"): t.get("full_name") for t in (g.get("teams") or []) if isinstance(t, dict)}
            local = str(equipos.get(g.get("home_team_id")) or "")
            vis = str(equipos.get(g.get("away_team_id")) or "")
            if not local or not vis:
                continue
            odds_juego = [o for o in (g.get("odds") or []) if isinstance(o, dict)]
            if not odds_juego:
                continue
            nodo = odds_juego[0]
            c_loc = _americana_a_decimal(nodo.get("ml_home"))
            c_vis = _americana_a_decimal(nodo.get("ml_away"))
            if c_loc and c_vis and c_loc > 1.02 and c_vis > 1.02:
                filas_inplay.append({
                    "Plataforma": "Vegas_InPlay_Live",
                    "Deporte": deporte_es,
                    "Liga": liga_es,
                    "Evento": f"{local} vs {vis}",
                    "Inicio_UTC": str(g.get("start_time") or ""),
                    "Tipo_Mercado": "Ganador (Moneyline)",
                    "Linea": "N/A",
                    "Lado_1": local,
                    "Cuota_Taker_1": c_loc,
                    "Liquidez_1_USD": 5000.0,
                    "Lado_2": vis,
                    "Cuota_Taker_2": c_vis,
                    "Liquidez_2_USD": 5000.0,
                    "Overround_Libro_Pct": calcular_overround_pct(c_loc, c_vis),
                    "ID_Mercado": f"an_live_{g.get('id')}",
                })

    # 2. ESPN / DraftKings In-Play ('state' == 'in')
    hoy_str = datetime.now(tz=timezone.utc).strftime("%Y%m%d")
    for ruta_dep, deporte_es, liga_es in LIGAS_ESPN_DRAFTKINGS:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{ruta_dep}/scoreboard"
        try:
            resp = requests.get(url, params={"dates": hoy_str, "limit": "100"}, headers=headers, timeout=6)
            if resp.status_code != 200:
                continue
            eventos = resp.json().get("events") or []
        except Exception:
            continue
        for ev in eventos:
            estado_tipo = ((ev.get("status") or {}).get("type") or {}).get("state")
            if estado_tipo != "in":
                continue
            comp = (ev.get("competitions") or [{}])[0]
            odds_list = comp.get("odds") or []
            competidores = comp.get("competitors") or []
            if not odds_list or len(competidores) < 2:
                continue
            nodo = odds_list[0]
            local, vis = "", ""
            for c in competidores:
                nom = str((c.get("team") or {}).get("displayName") or (c.get("athlete") or {}).get("displayName") or "")
                if c.get("homeAway") == "home":
                    local = nom
                else:
                    vis = nom
            if not local or not vis:
                continue
            ml_h = ((nodo.get("homeTeamOdds") or {}).get("moneyLine"))
            ml_a = ((nodo.get("awayTeamOdds") or {}).get("moneyLine"))
            c_loc = _americana_a_decimal(ml_h)
            c_vis = _americana_a_decimal(ml_a)
            if c_loc and c_vis and c_loc > 1.02 and c_vis > 1.02:
                filas_inplay.append({
                    "Plataforma": "Vegas_InPlay_Live",
                    "Deporte": deporte_es,
                    "Liga": liga_es,
                    "Evento": f"{local} vs {vis}",
                    "Inicio_UTC": str(ev.get("date") or ""),
                    "Tipo_Mercado": "Ganador (Moneyline)",
                    "Linea": "N/A",
                    "Lado_1": local,
                    "Cuota_Taker_1": c_loc,
                    "Liquidez_1_USD": 5000.0,
                    "Lado_2": vis,
                    "Cuota_Taker_2": c_vis,
                    "Liquidez_2_USD": 5000.0,
                    "Overround_Libro_Pct": calcular_overround_pct(c_loc, c_vis),
                    "ID_Mercado": f"espn_live_{ev.get('id')}",
                })

    return filas_inplay


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
        "SX Bet": lambda: extraer_sx_bet(tamano_pagina=100, max_paginas=6),
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
