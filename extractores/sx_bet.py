"""
Extractor de SX Bet (V3 CLOB API).
Obtiene mercados principales activos y el mejor nivel del libro de órdenes (perspectiva Taker),
convirtiendo probabilidades en escala 1e20 a cuotas decimales y tamaños en escala 1e6 a USD.
"""
import logging
from typing import List, Dict, Any
import requests
from configuracion import SX_API_KEY, calcular_overround_pct

logger = logging.getLogger(__name__)

URL_MERCADOS_ACTIVOS = "https://api.sx.bet/markets/active"
URL_MEJORES_CUOTAS = "https://api.sx.bet/orders-v3/odds/best"

ESCALA_PROBABILIDAD_SX = 1e20
ESCALA_USDC_SX = 1e6


def _mapear_tipo_mercado_sx(tipo_id: Any) -> str:
    """Traduce el identificador numérico de mercado de SX Bet al español."""
    mapa = {
        1: "Ganador (1X2)",
        52: "Ganador (Moneyline)",
        226: "Ganador (Moneyline)",
        3: "Hándicap (Spread)",
        342: "Hándicap (Spread)",
        2: "Totales (Over/Under)",
        28: "Totales (Over/Under)",
        29: "Totales (Over/Under)",
    }
    try:
        return mapa.get(int(tipo_id), f"Mercado_{tipo_id}")
    except (ValueError, TypeError):
        return str(tipo_id or "Ganador")


def extraer_sx_bet(tamano_pagina: int = 100) -> List[Dict[str, Any]]:
    """
    Extrae mercados activos de SX Bet y cruza con el endpoint /orders-v3/odds/best
    para obtener cuotas Taker y liquidez en USD.
    """
    headers = {"Accept": "application/json"}
    if SX_API_KEY:
        headers["x-sx-api-key"] = SX_API_KEY

    parametros_mercados = {
        "onlyMainLine": "true",
        "pageSize": str(tamano_pagina),
    }

    filas_normalizadas: List[Dict[str, Any]] = []

    try:
        resp_mercados = requests.get(
            URL_MERCADOS_ACTIVOS, params=parametros_mercados, headers=headers, timeout=15
        )
        resp_mercados.raise_for_status()
        payload_mercados = resp_mercados.json()
    except Exception as exc:
        logger.error("Error al consultar mercados activos de SX Bet: %s", exc)
        return filas_normalizadas

    datos_mercados = payload_mercados.get("data", {})
    lista_mercados = (
        datos_mercados.get("markets", [])
        if isinstance(datos_mercados, dict)
        else datos_mercados
    )
    if not isinstance(lista_mercados, list) or not lista_mercados:
        return filas_normalizadas

    # Agrupar marketHashes en lotes de hasta 50 para consultar el libro de órdenes
    mapa_mercados: Dict[str, Dict[str, Any]] = {}
    for m in lista_mercados:
        m_hash = m.get("marketHash")
        if m_hash:
            mapa_mercados[m_hash] = m

    hashes_totales = list(mapa_mercados.keys())
    tamano_lote = 50
    mejores_cuotas_por_hash: Dict[str, Dict[str, Any]] = {}

    for i in range(0, len(hashes_totales), tamano_lote):
        lote = hashes_totales[i : i + tamano_lote]
        parametros_odds = {
            "marketHashes": ",".join(lote),
            "showTakerPerspective": "true",
        }
        try:
            resp_odds = requests.get(
                URL_MEJORES_CUOTAS, params=parametros_odds, headers=headers, timeout=15
            )
            if resp_odds.status_code != 200:
                logger.warning(
                    "Respuesta %s en SX Bet odds/best: %s",
                    resp_odds.status_code,
                    resp_odds.text[:200],
                )
                continue
            payload_odds = resp_odds.json()
            datos_odds = payload_odds.get("data", payload_odds)
            # SX Bet puede devolver {"bestOdds": [...]} o directamente una lista o diccionario
            lista_best = (
                datos_odds.get("bestOdds", [])
                if isinstance(datos_odds, dict)
                else datos_odds
            )
            if isinstance(lista_best, list):
                for item in lista_best:
                    mh = item.get("marketHash")
                    if mh:
                        mejores_cuotas_por_hash[mh] = item
            elif isinstance(datos_odds, dict):
                for mh, info in datos_odds.items():
                    if isinstance(info, dict):
                        mejores_cuotas_por_hash[mh] = info
        except Exception as exc:
            logger.error("Error al consultar mejores cuotas en SX Bet: %s", exc)

    for m_hash, m in mapa_mercados.items():
        info_odds = mejores_cuotas_por_hash.get(m_hash, {})
        o1 = info_odds.get("outcomeOne") or {}
        o2 = info_odds.get("outcomeTwo") or {}

        prob_1_raw = o1.get("percentageOdds")
        prob_2_raw = o2.get("percentageOdds")

        cuota_1 = 0.0
        cuota_2 = 0.0
        if prob_1_raw:
            try:
                p1 = float(prob_1_raw) / ESCALA_PROBABILIDAD_SX
                if 0.001 < p1 < 0.999:
                    cuota_1 = round(1.0 / p1, 4)
            except (ValueError, TypeError):
                pass

        if prob_2_raw:
            try:
                p2 = float(prob_2_raw) / ESCALA_PROBABILIDAD_SX
                if 0.001 < p2 < 0.999:
                    cuota_2 = round(1.0 / p2, 4)
            except (ValueError, TypeError):
                pass

        # Solo conservar mercados que tengan al menos una o ambas puntas activas o bien documentadas
        if cuota_1 <= 1.0 and cuota_2 <= 1.0:
            continue

        liq_1_raw = o1.get("availableVolume") or o1.get("updatedAt") and o1.get("totalVolume") or o1.get("size") or 0
        liq_2_raw = o2.get("availableVolume") or o2.get("updatedAt") and o2.get("totalVolume") or o2.get("size") or 0

        try:
            liq_1_usd = round(float(liq_1_raw) / ESCALA_USDC_SX, 2)
        except (ValueError, TypeError):
            liq_1_usd = 0.0

        try:
            liq_2_usd = round(float(liq_2_raw) / ESCALA_USDC_SX, 2)
        except (ValueError, TypeError):
            liq_2_usd = 0.0

        equipo_1 = m.get("teamOneName") or m.get("outcomeOneName") or "Lado 1"
        equipo_2 = m.get("teamTwoName") or m.get("outcomeTwoName") or "Lado 2"
        evento_nombre = f"{equipo_1} vs {equipo_2}"

        ts_inicio = m.get("gameTime")
        inicio_utc = str(ts_inicio) if ts_inicio else ""

        filas_normalizadas.append(
            {
                "Plataforma": "SX Bet",
                "Deporte": str(m.get("sportLabel") or "Deportes"),
                "Liga": str(m.get("leagueLabel") or "General"),
                "Evento": evento_nombre,
                "Inicio_UTC": inicio_utc,
                "Tipo_Mercado": _mapear_tipo_mercado_sx(m.get("type")),
                "Linea": str(m.get("line", "N/A")),
                "Lado_1": str(m.get("outcomeOneName") or equipo_1),
                "Cuota_Taker_1": cuota_1,
                "Liquidez_1_USD": liq_1_usd,
                "Lado_2": str(m.get("outcomeTwoName") or equipo_2),
                "Cuota_Taker_2": cuota_2,
                "Liquidez_2_USD": liq_2_usd,
                "Overround_Libro_Pct": calcular_overround_pct(cuota_1, cuota_2),
                "ID_Mercado": m_hash,
            }
        )

    return filas_normalizadas


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    datos = extraer_sx_bet(tamano_pagina=50)
    print(f"Total mercados con liquidez extraídos de SX Bet: {len(datos)}")
    for muestra in datos[:5]:
        print(muestra)
