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


def extraer_polymarket_con_triangulos_y_bids(limite: int = 100, paginas: int = 5) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Extrae mercados deportivos de Polymarket Gamma API:
      1. Devuelve la lista estándar de mercados 2-Way con precios Ask (Taker) y Bid (Maker).
      2. Detecta eventos 1X2 (Local / Empate / Visitante) dentro de Polymarket para
         Arbitraje Interno (Motor A: Intra-Exchange Dutching sin riesgo de segunda casa).
    """
    mercados_2way: List[Dict[str, Any]] = []
    triangulos_1x2: List[Dict[str, Any]] = []
    url = "https://gamma-api.polymarket.com/events"
    headers = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}

    for tag_consulta, max_pags in [("sports", paginas), ("soccer", 2)]:
        for pag in range(max_pags):
            params = {
                "active": "true",
                "closed": "false",
                "tag_slug": tag_consulta,
                "limit": str(limite),
                "offset": str(pag * limite),
            }
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=10)
                if resp.status_code != 200:
                    break
                eventos = resp.json()
                if not isinstance(eventos, list) or not eventos:
                    break
            except Exception as exc:
                logger.debug("Error Polymarket página %d: %s", pag, exc)
                break

            for ev in eventos:
                titulo_ev = str(ev.get("title") or "").strip()
                inicio_utc = str(ev.get("startTime") or ev.get("startDate") or ev.get("endDate") or "")
                mkts = ev.get("markets") or []
                if not mkts:
                    continue

                # Detectar posible triángulo 1X2 (3 mercados binarios Moneyline en el mismo partido: Local, Draw/Tie, Visitante)
                patas_1x2 = []
                for m in mkts:
                    if not m.get("active") or m.get("closed") or not m.get("enableOrderBook"):
                        continue
                    pregunta = str(m.get("question") or m.get("groupItemTitle") or "").strip()
                    best_bid = float(m.get("bestBid") or 0.0)
                    best_ask = float(m.get("bestAsk") or 0.0)
                    if best_ask <= 0.01 and best_bid > 0.01:
                        best_ask = min(0.99, round(best_bid + 0.02, 2))
                    liq_total = float(m.get("liquidityNum") or m.get("liquidity") or 0.0)
                    clob_ids_raw = m.get("clobTokenIds")
                    try:
                        clob_ids = json.loads(clob_ids_raw) if isinstance(clob_ids_raw, str) else (clob_ids_raw or [])
                    except Exception:
                        clob_ids = []
                    outcomes_raw = m.get("outcomes")
                    try:
                        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else (outcomes_raw or [])
                    except Exception:
                        outcomes = []

                    tipo_mkt_deporte = str(m.get("sportsMarketType") or "").lower()
                    item_title = str(m.get("groupItemTitle") or "").strip()

                    # Si es un sub-mercado de un evento 1X2 (Yes/No sobre un equipo o Draw)
                    es_candidato_1x2 = (
                        outcomes == ["Yes", "No"]
                        and (not tipo_mkt_deporte or tipo_mkt_deporte == "moneyline")
                        and not any(k in pregunta.lower() for k in ("spread", "o/u", "total", "both teams", "halftime"))
                    )
                    if es_candidato_1x2 and 0.01 < best_ask < 0.99:
                        patas_1x2.append({
                            "etiqueta": item_title or pregunta,
                            "ask_yes": best_ask,
                            "bid_yes": best_bid if best_bid > 0.01 else max(0.01, round(best_ask - 0.02, 2)),
                            "ask_no": round(1.0 - best_bid, 4) if best_bid > 0.01 else round(1.0 - best_ask + 0.02, 4),
                            "liquidez_usd": max(50.0, round(liq_total * 0.25, 2)),
                            "token_yes": clob_ids[0] if len(clob_ids) >= 1 else "",
                            "token_no": clob_ids[1] if len(clob_ids) >= 2 else "",
                            "id_mkt": str(m.get("id") or ""),
                        })

                if len(patas_1x2) == 3 and any("draw" in p["etiqueta"].lower() or "tie" in p["etiqueta"].lower() for p in patas_1x2):
                    triangulos_1x2.append({
                        "Plataforma": "Polymarket",
                        "Evento": titulo_ev,
                        "Inicio_UTC": inicio_utc,
                        "Patas": patas_1x2,
                    })

    # Reutilizar también el extractor normalizado completo de Polymarket para todos los 2-way (Moneyline, Spreads, Totals)
    try:
        from extractores.polymarket import extraer_polymarket
        mercados_2way = extraer_polymarket(limite=limite, paginas=paginas)
    except Exception as exc:
        logger.warning("Fallo importando extraer_polymarket base: %s", exc)

    return mercados_2way, triangulos_1x2


def extraer_overtime_markets_v2() -> List[Dict[str, Any]]:
    """
    Intenta consultar el feed público de Overtime Markets V2 (Optimism / Arbitrum / Base Sports AMM).
    Overtime no cobra fee de taker aparte (el margen está incluido en la cuota on-chain).
    """
    filas: List[Dict[str, Any]] = []
    urls_candidatas = [
        "https://api.overtimemarkets.xyz/overtime-v2/networks/10/markets",
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
    Ejecuta en paralelo la extracción de todas las plataformas del Mapa Mundial 2026:
      - Polymarket (2-Way + Triángulos 1X2 Internos)
      - SX Bet (0% Taker Fee en simples)
      - Limitless (Base L2 CLOB)
      - Overtime Markets (Optimism/Arbitrum AMM)
      - Kalshi (CFTC CLOB con escaleras completas de Spreads y Totales)
      - Futuur (USDC)
      - Smarkets Exchange
      - Vegas Live Consensus (Action Network + ESPN/DraftKings)
    """
    from extractores.sx_bet import extraer_sx_bet
    from extractores.limitless import extraer_limitless
    from extractores.kalshi import extraer_kalshi
    from extractores.futuur import extraer_futuur
    from extractores.smarkets import extraer_smarkets
    from extractores.oraculo_gratis import extraer_oraculo_gratis_en_vivo
    from normalizador.emparejador import normalizar_filas

    tareas = {
        "SX Bet": lambda: extraer_sx_bet(tamano_pagina=100),
        "Limitless": lambda: extraer_limitless(max_paginas=6),
        "Kalshi": lambda: extraer_kalshi(),
        "Futuur": lambda: extraer_futuur(max_paginas=4),
        "Overtime": lambda: extraer_overtime_markets_v2(),
        "Smarkets": lambda: extraer_smarkets(limite_eventos=40),
        "Vegas_AN_DK": lambda: extraer_oraculo_gratis_en_vivo(),
        "Vegas_InPlay_Live": lambda: extraer_oraculo_inplay_en_vivo(),
    }

    resultados_crudos: List[Dict[str, Any]] = []
    triangulos_poly: List[Dict[str, Any]] = []
    conteo_plataformas: Dict[str, int] = {}

    with ThreadPoolExecutor(max_workers=8) as pool:
        fut_poly = pool.submit(extraer_polymarket_con_triangulos_y_bids, 100, 5)
        futuros = {pool.submit(fn): nombre for nombre, fn in tareas.items()}

        try:
            mkts_poly, triangulos_poly = fut_poly.result(timeout=45)
            resultados_crudos.extend(mkts_poly)
            conteo_plataformas["Polymarket"] = len(mkts_poly)
        except Exception as exc:
            logger.warning("Error extrayendo Polymarket: %s", exc)
            conteo_plataformas["Polymarket"] = 0

        for fut in as_completed(futuros):
            nombre = futuros[fut]
            try:
                filas = fut.result(timeout=45) or []
                resultados_crudos.extend(filas)
                conteo_plataformas[nombre] = len(filas)
            except Exception as exc:
                logger.warning("Error extrayendo %s: %s", nombre, exc)
                conteo_plataformas[nombre] = 0

    mercados_normalizados = normalizar_filas(resultados_crudos)
    return {
        "mercados_normalizados": mercados_normalizados,
        "triangulos_1x2": triangulos_poly,
        "conteo_plataformas": conteo_plataformas,
    }
