"""
Extractor de deportes de Polymarket (Gamma API y CLOB API).
Obtiene mercados deportivos activos, parsea strings JSON embebidos y calcula cuotas decimales.
"""
import json
import logging
import time
from typing import List, Dict, Any
import requests
from configuracion import calcular_overround_pct

logger = logging.getLogger(__name__)

URL_GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"
URL_CLOB_BOOK = "https://clob.polymarket.com/book"


def inferir_deporte_y_liga(evento: Dict[str, Any]) -> tuple[str, str]:
    """Infiere el deporte y la liga a partir de los tags o el slug/título del evento."""
    tags = evento.get("tags") or []
    etiquetas_slug = [str(t.get("slug", "")).lower() for t in tags if isinstance(t, dict)]
    etiquetas_label = [str(t.get("label", "")) for t in tags if isinstance(t, dict)]
    titulo = str(evento.get("title", "")).lower()
    slug = str(evento.get("slug", "")).lower()

    texto_busqueda = " ".join(etiquetas_slug + [titulo, slug])

    # Mapeo de ligas y deportes comunes en español
    mapeos = [
        (["nba", "basketball", "ncaa-basketball", "euroleague"], "Básquetbol", "NBA / Básquetbol"),
        (["nfl", "american-football", "cfb"], "Fútbol Americano", "NFL"),
        (["mlb", "baseball"], "Béisbol", "MLB"),
        (["nhl", "hockey"], "Hockey sobre Hielo", "NHL"),
        (["ufc", "mma", "boxing"], "MMA / Boxeo", "UFC / Boxeo"),
        (["atp", "wta", "tennis"], "Tenis", "ATP / WTA"),
        (["champions-league", "ucl"], "Fútbol", "UEFA Champions League"),
        (["premier-league", "epl"], "Fútbol", "Premier League"),
        (["la-liga", "laliga"], "Fútbol", "La Liga"),
        (["serie-a"], "Fútbol", "Serie A"),
        (["bundesliga"], "Fútbol", "Bundesliga"),
        (["MLS", "mls", "copa-libertadores", "soccer", "football", "futbol"], "Fútbol", "Fútbol Internacional"),
        (["f1", "formula-1", "nascar"], "Motor", "Fórmula 1"),
    ]

    for palabras_clave, deporte, liga_defecto in mapeos:
        if any(p in texto_busqueda for p in palabras_clave):
            # Intentar sacar una liga más específica de los tags
            for lbl in etiquetas_label:
                if lbl.lower() not in ("sports", "all", "games", "daily"):
                    return deporte, lbl
            return deporte, liga_defecto

    liga_tag = next((lbl for lbl in etiquetas_label if lbl.lower() not in ("sports", "all")), "General")
    return "Deportes", liga_tag


def parsear_campo_json(valor: Any) -> List[Any]:
    """Parsea de forma segura campos que Polymarket devuelve como string JSON embebido."""
    if isinstance(valor, list):
        return valor
    if isinstance(valor, str):
        try:
            resultado = json.loads(valor)
            return resultado if isinstance(resultado, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def extraer_polymarket(limite: int = 100) -> List[Dict[str, Any]]:
    """
    Consulta los eventos deportivos activos en Polymarket y normaliza los mercados de 2 vías
    al esquema estándar en español.
    """
    parametros = {
        "active": "true",
        "closed": "false",
        "tag_slug": "sports",
        "order": "volume24hr",
        "ascending": "false",
        "limit": str(limite),
    }

    filas_normalizadas: List[Dict[str, Any]] = []

    eventos = None
    for intento in range(3):
        try:
            respuesta = requests.get(URL_GAMMA_EVENTS, params=parametros, timeout=15)
            respuesta.raise_for_status()
            eventos = respuesta.json()
            break
        except Exception as exc:
            if intento < 2:
                time.sleep(1.5)
            else:
                logger.error("Error al consultar Polymarket Gamma API tras 3 intentos: %s", exc)
                return filas_normalizadas

    if not isinstance(eventos, list):
        return filas_normalizadas

    for evento in eventos:
        titulo_evento = evento.get("title", "Evento Desconocido")
        deporte, liga = inferir_deporte_y_liga(evento)
        mercados = evento.get("markets") or []

        for mercado in mercados:
            if not mercado.get("active", True) or mercado.get("closed", False):
                continue

            outcomes = parsear_campo_json(mercado.get("outcomes"))
            precios = parsear_campo_json(mercado.get("outcomePrices"))
            clob_tokens = parsear_campo_json(mercado.get("clobTokenIds"))

            # Nos enfocamos en mercados binarios / 2 lados con precios válidos
            if len(outcomes) != 2 or len(precios) != 2:
                continue

            try:
                precio_mid_1 = float(precios[0])
                precio_mid_2 = float(precios[1])
            except (ValueError, TypeError):
                continue

            # En Polymarket Gamma, bestAsk y bestBid corresponden al primer token (outcomes[0]).
            # Para una ejecución Taker real, comprar Lado_1 paga `bestAsk`, y comprar Lado_2 equivale a `1.0 - bestBid`.
            best_ask_1 = float(mercado.get("bestAsk") or 0.0)
            best_bid_1 = float(mercado.get("bestBid") or 0.0)
            spread_libro = float(mercado.get("spread") or 0.0)

            # Descartar mercados fantasma sin puntas activas o con spread mayor a 12 centavos
            if best_ask_1 > 0.01 and best_bid_1 > 0.01 and spread_libro <= 0.12:
                precio_1 = best_ask_1
                precio_2 = round(1.0 - best_bid_1, 4)
            else:
                # Si no reporta bestAsk/bestBid cerrado, descartar si los precios son exactamente 0.5/0.5 sin volumen
                if abs(precio_mid_1 - 0.5) < 0.001 and float(mercado.get("volumeNum") or 0) < 100:
                    continue
                precio_1 = precio_mid_1
                precio_2 = precio_mid_2

            # Descartar mercados resueltos o sin cotización real (ej. precio 0 o 1)
            if not (0.01 < precio_1 < 0.99 and 0.01 < precio_2 < 0.99):
                continue

            cuota_1 = round(1.0 / precio_1, 4)
            cuota_2 = round(1.0 / precio_2, 4)

            liquidez_total = float(mercado.get("liquidityNum") or mercado.get("liquidity") or 0.0)
            liquidez_lado = round(liquidez_total / 2.0, 2)

            inicio_utc = (
                mercado.get("gameStartTime")
                or evento.get("startDate")
                or mercado.get("endDate")
                or ""
            )

            pregunta_mercado = str(mercado.get("question") or titulo_evento)
            smt = str(mercado.get("sportsMarketType") or "").lower().strip()
            linea_raw = mercado.get("line")
            linea = str(linea_raw) if linea_raw is not None else "N/A"

            if smt == "moneyline":
                tipo_mercado = "Ganador (Moneyline)"
            elif smt == "spreads":
                tipo_mercado = "Hándicap (Spread)"
            elif smt == "totals":
                tipo_mercado = "Totales (Over/Under)"
            elif smt:
                tipo_mercado = f"Prop ({smt})"
            else:
                q_low = pregunta_mercado.lower()
                if any(x in q_low for x in ("1h ", "2h ", "1q ", "2q ", "3q ", "4q ", "first half", "second half")):
                    tipo_mercado = "Prop (Periodo/Mitad)"
                elif "spread" in q_low or "handicap" in q_low:
                    tipo_mercado = "Hándicap (Spread)"
                elif "o/u" in q_low or "over/under" in q_low or "total" in q_low:
                    tipo_mercado = "Totales (Over/Under)"
                elif str(outcomes[0]).lower() in ("yes", "no", "sí"):
                    tipo_mercado = "Prop (Binario Sí/No)"
                else:
                    tipo_mercado = "Ganador (Moneyline)"

            overround = calcular_overround_pct(cuota_1, cuota_2)
            cond_id = str(mercado.get("conditionId") or mercado.get("id") or "")
            if len(clob_tokens) == 2:
                id_mercado = f"{cond_id}::{clob_tokens[0]}::{clob_tokens[1]}"
            else:
                id_mercado = cond_id

            nombre_evento = titulo_evento
            if tipo_mercado.startswith("Prop") and pregunta_mercado and pregunta_mercado != titulo_evento:
                nombre_evento = f"{titulo_evento} - {pregunta_mercado}"

            filas_normalizadas.append(
                {
                    "Plataforma": "Polymarket",
                    "Deporte": deporte,
                    "Liga": liga,
                    "Evento": nombre_evento,
                    "Inicio_UTC": str(inicio_utc),
                    "Tipo_Mercado": tipo_mercado,
                    "Linea": linea,
                    "Lado_1": str(outcomes[0]),
                    "Cuota_Taker_1": cuota_1,
                    "Liquidez_1_USD": liquidez_lado,
                    "Lado_2": str(outcomes[1]),
                    "Cuota_Taker_2": cuota_2,
                    "Liquidez_2_USD": liquidez_lado,
                    "Overround_Libro_Pct": overround,
                    "ID_Mercado": id_mercado,
                }
            )

    return filas_normalizadas


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    datos = extraer_polymarket(limite=25)
    print(f"Total mercados extraídos de Polymarket: {len(datos)}")
    for muestra in datos[:5]:
        print(muestra)
