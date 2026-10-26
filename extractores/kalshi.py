"""
Extractor de Kalshi (Trade API v2 - CLOB Deportivo).
Extrae mercados deportivos en tiempo real (Moneyline, Hándicaps/Spreads y Totales Over/Under)
a través de las series deportivas oficiales de Kalshi sin necesidad de API Key para lectura.
Convierte precios `yes_ask_dollars` / `no_ask_dollars` a cuotas decimales Taker.
"""
import logging
import re
from typing import List, Dict, Any, Tuple
import requests
from configuracion import calcular_overround_pct

logger = logging.getLogger(__name__)

URL_KALSHI_EVENTS = "https://api.elections.kalshi.com/trade-api/v2/events"

# Series deportivas principales en Kalshi: (series_ticker, Deporte, Liga, categoría)
SERIES_DEPORTIVAS_KALSHI: List[Tuple[str, str, str, str]] = [
    ("KXNBAGAME", "Básquetbol", "NBA", "moneyline"),
    ("KXNBASPREAD", "Básquetbol", "NBA", "spread"),
    ("KXNBATOTAL", "Básquetbol", "NBA", "total"),
    ("KXNFLGAME", "Fútbol Americano", "NFL", "moneyline"),
    ("KXNFLSPREAD", "Fútbol Americano", "NFL", "spread"),
    ("KXNFLTOTAL", "Fútbol Americano", "NFL", "total"),
    ("KXMLBGAME", "Béisbol", "MLB", "moneyline"),
    ("KXMLBSPREAD", "Béisbol", "MLB", "spread"),
    ("KXMLBTOTAL", "Béisbol", "MLB", "total"),
    ("KXNHLGAME", "Hockey sobre Hielo", "NHL", "moneyline"),
    ("KXNHLSPREAD", "Hockey sobre Hielo", "NHL", "spread"),
    ("KXNHLTOTAL", "Hockey sobre Hielo", "NHL", "total"),
    ("KXUFCFIGHT", "MMA / Boxeo", "UFC", "moneyline"),
    ("KXATPMATCH", "Tenis", "ATP", "moneyline"),
    ("KXWTAMATCH", "Tenis", "WTA", "moneyline"),
    ("KXATPCHALLENGERMATCH", "Tenis", "ATP Challenger", "moneyline"),
    ("KXEPLGAME", "Fútbol", "Premier League", "1x2"),
    ("KXUCLGAME", "Fútbol", "UEFA Champions League", "1x2"),
    ("KXUELGAME", "Fútbol", "UEFA Europa League", "1x2"),
    ("KXUECLGAME", "Fútbol", "UEFA Conference League", "1x2"),
    ("KXLALIGAGAME", "Fútbol", "La Liga", "1x2"),
    ("KXSERIEAGAME", "Fútbol", "Serie A", "1x2"),
    ("KXBUNDESLIGAGAME", "Fútbol", "Bundesliga", "1x2"),
    ("KXLIGUE1GAME", "Fútbol", "Ligue 1", "1x2"),
    ("KXMLSGAME", "Fútbol", "MLS", "1x2"),
]


def _limpiar_titulo_evento_kalshi(titulo: str) -> str:
    """Elimina sufijos como ': Spread' o ': Total Points' del título del evento."""
    t = re.sub(r":\s*(Spread|Total.*|Point.*)$", "", str(titulo or ""), flags=re.IGNORECASE)
    return t.strip()


def _extraer_equipos_de_titulo(titulo: str) -> Tuple[str, str]:
    """Separa los dos equipos desde el título del evento en Kalshi (ej. 'Washington vs San Francisco')."""
    limpio = _limpiar_titulo_evento_kalshi(titulo)
    # Si tiene prefijo de cartelera como '333: Fighter A vs Fighter B'
    limpio = re.sub(r"^\d+:\s*", "", limpio)
    partes = re.split(r"\s+vs\.?\s+|\s+@\s+", limpio, flags=re.IGNORECASE)
    if len(partes) >= 2:
        return partes[0].strip(), partes[1].strip()
    return "Lado 1", "Lado 2"


def extraer_kalshi() -> List[Dict[str, Any]]:
    """
    Recorre las series deportivas activas en Kalshi y normaliza los libros de órdenes (CLOB)
    al esquema estándar de 15 columnas en español.
    """
    filas_normalizadas: List[Dict[str, Any]] = []

    for series_ticker, deporte_es, liga_es, categoria in SERIES_DEPORTIVAS_KALSHI:
        parametros = {
            "series_ticker": series_ticker,
            "status": "open",
            "with_nested_markets": "true",
            "limit": "100",
        }
        try:
            resp = requests.get(URL_KALSHI_EVENTS, params=parametros, timeout=12)
            if resp.status_code != 200:
                logger.warning("Kalshi devolvió %s para %s", resp.status_code, series_ticker)
                continue
            eventos = resp.json().get("events") or []
        except Exception as exc:
            logger.error("Error consultando Kalshi serie %s: %s", series_ticker, exc)
            continue

        for ev in eventos:
            titulo_ev = _limpiar_titulo_evento_kalshi(ev.get("title", "Evento Kalshi"))
            mercados = [m for m in (ev.get("markets") or []) if m.get("status") == "active"]
            if not mercados:
                continue

            inicio_utc = (
                mercados[0].get("occurrence_datetime")
                or mercados[0].get("expected_expiration_time")
                or ""
            )

            # --- 1) MONEYLINE 2-WAY (NBA, NFL, MLB, NHL, UFC) ---
            if categoria == "moneyline" and len(mercados) == 2:
                m1, m2 = mercados[0], mercados[1]
                try:
                    ask_1 = float(m1.get("yes_ask_dollars") or 0.0)
                    ask_2 = float(m2.get("yes_ask_dollars") or 0.0)
                except (ValueError, TypeError):
                    continue

                if not (0.01 < ask_1 < 0.99 and 0.01 < ask_2 < 0.99):
                    continue

                cuota_1 = round(1.0 / ask_1, 4)
                cuota_2 = round(1.0 / ask_2, 4)

                liq_1 = round(float(m1.get("yes_ask_size_fp") or 0.0) * ask_1, 2)
                liq_2 = round(float(m2.get("yes_ask_size_fp") or 0.0) * ask_2, 2)

                # Usar el nombre completo del título si está disponible (ej. 'WAS Commanders vs SF 49ers')
                eq_titulo_1, eq_titulo_2 = _extraer_equipos_de_titulo(titulo_ev)
                sub_1 = str(m1.get("yes_sub_title") or eq_titulo_1)
                sub_2 = str(m2.get("yes_sub_title") or eq_titulo_2)

                # Si el sub_title es solo la ciudad ('San Francisco') pero el título tiene 'SF 49ers', conservar el más descriptivo
                if sub_1.lower() in eq_titulo_1.lower():
                    lado_1, lado_2 = eq_titulo_1, eq_titulo_2
                elif sub_1.lower() in eq_titulo_2.lower():
                    lado_1, lado_2 = eq_titulo_2, eq_titulo_1
                else:
                    lado_1, lado_2 = sub_1, sub_2

                filas_normalizadas.append(
                    {
                        "Plataforma": "Kalshi",
                        "Deporte": deporte_es,
                        "Liga": liga_es,
                        "Evento": titulo_ev,
                        "Inicio_UTC": str(inicio_utc),
                        "Tipo_Mercado": "Ganador (Moneyline)",
                        "Linea": "N/A",
                        "Lado_1": lado_1,
                        "Cuota_Taker_1": cuota_1,
                        "Liquidez_1_USD": liq_1,
                        "Lado_2": lado_2,
                        "Cuota_Taker_2": cuota_2,
                        "Liquidez_2_USD": liq_2,
                        "Overround_Libro_Pct": calcular_overround_pct(cuota_1, cuota_2),
                        "ID_Mercado": str(ev.get("event_ticker") or m1.get("ticker")),
                    }
                )

            # --- 2) FÚTBOL 1X2 (EPL, UCL, La Liga) ---
            elif categoria == "1x2" and len(mercados) == 3:
                mkt_empate = next(
                    (m for m in mercados if str(m.get("yes_sub_title", "")).lower() in ("tie", "draw")),
                    None,
                )
                mkts_equipos = [
                    m for m in mercados if str(m.get("yes_sub_title", "")).lower() not in ("tie", "draw")
                ]
                if len(mkts_equipos) == 2 and mkt_empate:
                    m1, m2 = mkts_equipos[0], mkts_equipos[1]
                    try:
                        ask_1 = float(m1.get("yes_ask_dollars") or 0.0)
                        ask_2 = float(m2.get("yes_ask_dollars") or 0.0)
                        ask_tie = float(mkt_empate.get("yes_ask_dollars") or 0.0)
                    except (ValueError, TypeError):
                        continue

                    if not (0.01 < ask_1 < 0.99 and 0.01 < ask_2 < 0.99 and 0.01 < ask_tie < 0.99):
                        continue

                    cuota_1 = round(1.0 / ask_1, 4)
                    cuota_2 = round(1.0 / ask_2, 4)
                    cuota_empate = round(1.0 / ask_tie, 4)
                    overround_3way = round((ask_1 + ask_2 + ask_tie - 1.0) * 100.0, 2)

                    liq_1 = round(float(m1.get("yes_ask_size_fp") or 0.0) * ask_1, 2)
                    liq_2 = round(float(m2.get("yes_ask_size_fp") or 0.0) * ask_2, 2)

                    filas_normalizadas.append(
                        {
                            "Plataforma": "Kalshi",
                            "Deporte": deporte_es,
                            "Liga": liga_es,
                            "Evento": titulo_ev,
                            "Inicio_UTC": str(inicio_utc),
                            "Tipo_Mercado": "Ganador (1X2 - Sin Empate Ref)",
                            "Linea": f"Empate@{cuota_empate}",
                            "Lado_1": str(m1.get("yes_sub_title", "Local")),
                            "Cuota_Taker_1": cuota_1,
                            "Liquidez_1_USD": liq_1,
                            "Lado_2": str(m2.get("yes_sub_title", "Visitante")),
                            "Cuota_Taker_2": cuota_2,
                            "Liquidez_2_USD": liq_2,
                            "Overround_Libro_Pct": overround_3way,
                            "ID_Mercado": str(ev.get("event_ticker") or m1.get("ticker")),
                        }
                    )

            # --- 3) SPREADS (Hándicap) ---
            elif categoria == "spread":
                eq_1, eq_2 = _extraer_equipos_de_titulo(titulo_ev)
                for m in mercados:
                    # Ejemplo title: "San Francisco wins by over 7.5 points?" -> San Francisco -7.5 vs Washington +7.5
                    titulo_mkt = str(m.get("title") or m.get("yes_sub_title") or "")
                    match_sp = re.match(
                        r"^(.+?)\s+wins\s+by\s+over\s+(\d+(?:\.\d+)?)\s+points",
                        titulo_mkt,
                        flags=re.IGNORECASE,
                    )
                    if not match_sp:
                        continue

                    equipo_fav = match_sp.group(1).strip()
                    valor_strike = float(match_sp.group(2))
                    linea_negativa = f"-{valor_strike}"

                    try:
                        yes_ask = float(m.get("yes_ask_dollars") or 0.0)
                        no_ask = float(m.get("no_ask_dollars") or 0.0)
                    except (ValueError, TypeError):
                        continue

                    # Filtrar líneas extremas sin liquidez real (ej. wins by over 27.5 points)
                    if not (0.05 < yes_ask < 0.95 and 0.05 < no_ask < 0.95):
                        continue

                    cuota_1 = round(1.0 / yes_ask, 4)
                    cuota_2 = round(1.0 / no_ask, 4)

                    # Determinar cuál es el otro equipo del partido
                    equipo_dog = eq_2 if equipo_fav.lower() in eq_1.lower() else eq_1

                    liq_1 = round(float(m.get("yes_ask_size_fp") or 0.0) * yes_ask, 2)
                    liq_2 = round(float(m.get("yes_bid_size_fp") or 0.0) * no_ask, 2)

                    filas_normalizadas.append(
                        {
                            "Plataforma": "Kalshi",
                            "Deporte": deporte_es,
                            "Liga": liga_es,
                            "Evento": titulo_ev,
                            "Inicio_UTC": str(m.get("occurrence_datetime") or inicio_utc),
                            "Tipo_Mercado": "Hándicap (Spread)",
                            "Linea": linea_negativa,
                            "Lado_1": equipo_fav,
                            "Cuota_Taker_1": cuota_1,
                            "Liquidez_1_USD": liq_1,
                            "Lado_2": equipo_dog,
                            "Cuota_Taker_2": cuota_2,
                            "Liquidez_2_USD": liq_2,
                            "Overround_Libro_Pct": calcular_overround_pct(cuota_1, cuota_2),
                            "ID_Mercado": str(m.get("ticker")),
                        }
                    )

            # --- 4) TOTALES (Over/Under) ---
            elif categoria == "total":
                for m in mercados:
                    strike = m.get("floor_strike")
                    if strike is None:
                        match_tot = re.search(r"over\s+(\d+(?:\.\d+)?)", str(m.get("title", "")), re.I)
                        strike = match_tot.group(1) if match_tot else None
                    if strike is None:
                        continue

                    try:
                        yes_ask = float(m.get("yes_ask_dollars") or 0.0)
                        no_ask = float(m.get("no_ask_dollars") or 0.0)
                    except (ValueError, TypeError):
                        continue

                    if not (0.05 < yes_ask < 0.95 and 0.05 < no_ask < 0.95):
                        continue

                    cuota_over = round(1.0 / yes_ask, 4)
                    cuota_under = round(1.0 / no_ask, 4)

                    liq_over = round(float(m.get("yes_ask_size_fp") or 0.0) * yes_ask, 2)
                    liq_under = round(float(m.get("yes_bid_size_fp") or 0.0) * no_ask, 2)

                    filas_normalizadas.append(
                        {
                            "Plataforma": "Kalshi",
                            "Deporte": deporte_es,
                            "Liga": liga_es,
                            "Evento": titulo_ev,
                            "Inicio_UTC": str(m.get("occurrence_datetime") or inicio_utc),
                            "Tipo_Mercado": "Totales (Over/Under)",
                            "Linea": str(float(strike)),
                            "Lado_1": "Over",
                            "Cuota_Taker_1": cuota_over,
                            "Liquidez_1_USD": liq_over,
                            "Lado_2": "Under",
                            "Cuota_Taker_2": cuota_under,
                            "Liquidez_2_USD": liq_under,
                            "Overround_Libro_Pct": calcular_overround_pct(cuota_over, cuota_under),
                            "ID_Mercado": str(m.get("ticker")),
                        }
                    )

    return filas_normalizadas


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    datos = extraer_kalshi()
    print(f"Total mercados extraídos de Kalshi: {len(datos)}")
    for muestra in datos[:10]:
        print(muestra)
