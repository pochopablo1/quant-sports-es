"""
Extractor del Benchmark Sharp (Pinnacle a través de The-Odds-API).
Calcula además las probabilidades justas (fair probabilities) y cuotas sin margen
usando devigging multiplicativo:
  prob_fair_i = (1.0 / odds_pinnacle_i) / sum(1.0 / odds_pinnacle_j)
  fair_odds_i = 1.0 / prob_fair_i
"""
import logging
from typing import List, Dict, Any, Tuple
import requests
from configuracion import ODDS_API_KEYS, calcular_overround_pct

logger = logging.getLogger(__name__)

URL_BASE_ODDS_API = "https://api.the-odds-api.com/v4/sports"

# Ligas principales de alta liquidez para consultar en Pinnacle
DEPORTES_OBJETIVO = [
    ("basketball_nba", "Básquetbol", "NBA"),
    ("americanfootball_nfl", "Fútbol Americano", "NFL"),
    ("baseball_mlb", "Béisbol", "MLB"),
    ("icehockey_nhl", "Hockey sobre Hielo", "NHL"),
    ("mma_mixed_martial_arts", "MMA / Boxeo", "MMA"),
    ("soccer_epl", "Fútbol", "Premier League"),
    ("soccer_spain_la_liga", "Fútbol", "La Liga"),
    ("soccer_italy_serie_a", "Fútbol", "Serie A"),
    ("soccer_germany_bundesliga", "Fútbol", "Bundesliga"),
    ("soccer_uefa_champs_league", "Fútbol", "UEFA Champions League"),
]


def devig_multiplicativo(cuota_1: float, cuota_2: float) -> Tuple[float, float, float, float]:
    """
    Aplica devigging multiplicativo a un par de cuotas de 2 vías.
    Retorna: (prob_justa_1, prob_justa_2, cuota_justa_1, cuota_justa_2)
    """
    if cuota_1 <= 1.0 or cuota_2 <= 1.0:
        return 0.0, 0.0, 0.0, 0.0
    inv_1 = 1.0 / cuota_1
    inv_2 = 1.0 / cuota_2
    suma_inv = inv_1 + inv_2
    prob_justa_1 = inv_1 / suma_inv
    prob_justa_2 = inv_2 / suma_inv
    return (
        round(prob_justa_1, 6),
        round(prob_justa_2, 6),
        round(1.0 / prob_justa_1, 4),
        round(1.0 / prob_justa_2, 4),
    )


def devig_multiplicativo_3way(
    cuota_1: float, cuota_2: float, cuota_empate: float
) -> Tuple[float, float, float, float, float, float]:
    """
    Aplica devigging multiplicativo exacto para mercados 1X2 (Local, Visitante, Empate):
      prob_justa_i = (1 / cuota_i) / (1/cuota_1 + 1/cuota_2 + 1/cuota_empate)
    Retorna: (prob_1, prob_2, prob_empate, cuota_justa_1, cuota_justa_2, cuota_justa_empate)
    """
    if cuota_1 <= 1.0 or cuota_2 <= 1.0 or cuota_empate <= 1.0:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    inv_1 = 1.0 / cuota_1
    inv_2 = 1.0 / cuota_2
    inv_x = 1.0 / cuota_empate
    suma = inv_1 + inv_2 + inv_x
    p1 = inv_1 / suma
    p2 = inv_2 / suma
    px = inv_x / suma
    return (
        round(p1, 6),
        round(p2, 6),
        round(px, 6),
        round(1.0 / p1, 4),
        round(1.0 / p2, 4),
        round(1.0 / px, 4),
    )


def extraer_pinnacle(max_deportes: int = 6) -> List[Dict[str, Any]]:
    """
    Consulta The-Odds-API filtrando por el bookmaker 'pinnacle' (y 'pinnacle' + equivalentes sharp
    si un evento solo tiene mercados 2-way).
    """
    filas_normalizadas: List[Dict[str, Any]] = []
    if not ODDS_API_KEYS:
        logger.warning("No se encontraron claves ODDS_API_KEYS en la configuración.")
        return filas_normalizadas

    api_key = ODDS_API_KEYS[0]

    # Primero obtenemos qué deportes están activos en este momento para no gastar cuota en ligas fuera de temporada
    try:
        resp_deportes = requests.get(
            URL_BASE_ODDS_API, params={"apiKey": api_key}, timeout=15
        )
        resp_deportes.raise_for_status()
        deportes_activos_api = {
            d.get("key"): d for d in resp_deportes.json() if isinstance(d, dict) and d.get("active")
        }
    except Exception as exc:
        logger.error("Error al consultar lista de deportes en The-Odds-API: %s", exc)
        deportes_activos_api = {}

    deportes_a_consultar = []
    for key, dep_es, liga_es in DEPORTES_OBJETIVO:
        if not deportes_activos_api or key in deportes_activos_api:
            deportes_a_consultar.append((key, dep_es, liga_es))
        if len(deportes_a_consultar) >= max_deportes:
            break

    # Si ninguno de la lista fija coincidió, tomar los primeros activos
    if not deportes_a_consultar and deportes_activos_api:
        for key, info in list(deportes_activos_api.items())[:max_deportes]:
            deportes_a_consultar.append(
                (key, str(info.get("group", "Deportes")), str(info.get("title", key)))
            )

    # Prioridad de libros Sharp (Pinnacle primero, seguido de su clon LowVig y Betfair Exchange)
    JERARQUIA_SHARP = ["pinnacle", "lowvig", "betfair_ex_eu", "marathonbet"]

    for sport_key, deporte_es, liga_es in deportes_a_consultar:
        url_odds = f"{URL_BASE_ODDS_API}/{sport_key}/odds"
        parametros = {
            "apiKey": api_key,
            "bookmakers": ",".join(JERARQUIA_SHARP),
            "markets": "h2h,totals,spreads",
            "oddsFormat": "decimal",
        }
        try:
            resp = requests.get(url_odds, params=parametros, timeout=15)
            if resp.status_code != 200:
                logger.warning(
                    "The-Odds-API devolvió %s para %s: %s",
                    resp.status_code,
                    sport_key,
                    resp.text[:200],
                )
                continue
            eventos = resp.json()
        except Exception as exc:
            logger.error("Error consultando Pinnacle/Sharp para %s: %s", sport_key, exc)
            continue

        if not isinstance(eventos, list):
            continue

        for ev in eventos:
            local = ev.get("home_team", "Local")
            visitante = ev.get("away_team", "Visitante")
            nombre_evento = f"{local} vs {visitante}"
            inicio_utc = str(ev.get("commence_time", ""))
            id_ev = str(ev.get("id", ""))

            libros_evento = {b.get("key"): b for b in (ev.get("bookmakers") or []) if isinstance(b, dict)}
            book_elegido = None
            for clave_sharp in JERARQUIA_SHARP:
                if clave_sharp in libros_evento:
                    book_elegido = libros_evento[clave_sharp]
                    break

            if not book_elegido:
                continue

            for mkt in book_elegido.get("markets") or []:
                mkt_key = mkt.get("key", "h2h")
                outcomes = mkt.get("outcomes") or []

                # Para mercados de 2 lados (Moneyline 2-way, Spreads, Totals)
                if len(outcomes) == 2:
                    o1, o2 = outcomes[0], outcomes[1]
                    c1 = float(o1.get("price", 0.0))
                    c2 = float(o2.get("price", 0.0))
                    if c1 <= 1.0 or c2 <= 1.0:
                        continue

                    linea = "N/A"
                    if mkt_key == "spreads":
                        tipo_mkt = "Hándicap (Spread)"
                        linea = str(o1.get("point", "N/A"))
                    elif mkt_key == "totals":
                        tipo_mkt = "Totales (Over/Under)"
                        linea = str(o1.get("point", "N/A"))
                    else:
                        tipo_mkt = "Ganador (Moneyline)"

                    filas_normalizadas.append(
                        {
                            "Plataforma": "Pinnacle",
                            "Deporte": deporte_es,
                            "Liga": liga_es,
                            "Evento": nombre_evento,
                            "Inicio_UTC": inicio_utc,
                            "Tipo_Mercado": tipo_mkt,
                            "Linea": linea,
                            "Lado_1": str(o1.get("name", local)),
                            "Cuota_Taker_1": round(c1, 4),
                            "Liquidez_1_USD": 10000.0,
                            "Lado_2": str(o2.get("name", visitante)),
                            "Cuota_Taker_2": round(c2, 4),
                            "Liquidez_2_USD": 10000.0,
                            "Overround_Libro_Pct": calcular_overround_pct(c1, c2),
                            "ID_Mercado": f"pin_{id_ev}_{mkt_key}_{linea}",
                        }
                    )
                elif len(outcomes) == 3 and mkt_key == "h2h":
                    equipos_outcomes = [o for o in outcomes if str(o.get("name", "")).lower() != "draw"]
                    empate_outcome = next((o for o in outcomes if str(o.get("name", "")).lower() == "draw"), None)
                    if len(equipos_outcomes) == 2 and empate_outcome:
                        o1, o2 = equipos_outcomes[0], equipos_outcomes[1]
                        c1 = float(o1.get("price", 0.0))
                        c2 = float(o2.get("price", 0.0))
                        c_empate = float(empate_outcome.get("price", 0.0))
                        if c1 > 1.0 and c2 > 1.0 and c_empate > 1.0:
                            overround_3way = round(((1.0 / c1) + (1.0 / c2) + (1.0 / c_empate) - 1.0) * 100.0, 2)
                            filas_normalizadas.append(
                                {
                                    "Plataforma": "Pinnacle",
                                    "Deporte": deporte_es,
                                    "Liga": liga_es,
                                    "Evento": nombre_evento,
                                    "Inicio_UTC": inicio_utc,
                                    "Tipo_Mercado": "Ganador (1X2 - Sin Empate Ref)",
                                    "Linea": f"Empate@{c_empate}",
                                    "Lado_1": str(o1.get("name", local)),
                                    "Cuota_Taker_1": round(c1, 4),
                                    "Liquidez_1_USD": 10000.0,
                                    "Lado_2": str(o2.get("name", visitante)),
                                    "Cuota_Taker_2": round(c2, 4),
                                    "Liquidez_2_USD": 10000.0,
                                    "Overround_Libro_Pct": overround_3way,
                                    "ID_Mercado": f"pin_{id_ev}_1x2",
                                }
                            )

    return filas_normalizadas


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    datos = extraer_pinnacle(max_deportes=4)
    print(f"Total mercados extraídos de Pinnacle: {len(datos)}")
    for muestra in datos[:5]:
        print(muestra)
