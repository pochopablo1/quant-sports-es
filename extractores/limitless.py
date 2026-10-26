"""
Extractor de Limitless Exchange (CLOB Web3 sobre Base L2).
Obtiene mercados deportivos activos desde `https://api.limitless.exchange/markets/active`,
usando los precios reales de ejecución Taker (`tradePrices.buy.market`) en USDC y metadatos de inicio UTC.
"""
import logging
import re
from typing import List, Dict, Any, Tuple
import requests
from configuracion import calcular_overround_pct

logger = logging.getLogger(__name__)

URL_LIMITLESS_ACTIVE = "https://api.limitless.exchange/markets/active"


def _inferir_deporte_liga_limitless(m: Dict[str, Any]) -> Tuple[str, str]:
    tags = [str(t).lower() for t in (m.get("tags") or [])]
    cats = [str(c).lower() for c in (m.get("categories") or [])]
    props = m.get("properties") or []
    valores_prop = [
        str(v).lower()
        for p in props
        if isinstance(p, dict)
        for v in (p.get("value") or [])
    ]
    texto = " ".join(tags + cats + valores_prop + [str(m.get("title", "")).lower()])

    if "nfl" in texto:
        return "Fútbol Americano", "NFL"
    if "nba" in texto or "basketball" in texto:
        return "Básquetbol", "NBA"
    if "mlb" in texto or "baseball" in texto:
        return "Béisbol", "MLB"
    if "nhl" in texto or "hockey" in texto:
        return "Hockey sobre Hielo", "NHL"
    if "ufc" in texto or "mma" in texto:
        return "MMA / Boxeo", "UFC"
    if "esports" in texto or "map " in texto:
        return "eSports", "eSports"
    if "laliga" in texto or "epl" in texto or "serie a" in texto or "football" in texto:
        return "Fútbol", "Fútbol Internacional"
    return "Tenis", "ATP / WTA / Challenger"


def extraer_limitless(max_paginas: int = 8) -> List[Dict[str, Any]]:
    """
    Recorre las páginas de mercados activos en Limitless Exchange (máx 25 por página),
    filtra deportes y convierte precios Taker de compra (`tradePrices.buy.market` o `prices`)
    a cuotas decimales.
    """
    filas_normalizadas: List[Dict[str, Any]] = []

    for pagina in range(1, max_paginas + 1):
        try:
            resp = requests.get(
                URL_LIMITLESS_ACTIVE,
                params={"limit": "25", "page": str(pagina)},
                timeout=12,
            )
            if resp.status_code != 200:
                break
            mercados = resp.json().get("data") or []
            if not mercados:
                break
        except Exception as exc:
            logger.error("Error consultando Limitless Exchange pág %d: %s", pagina, exc)
            break

        for m in mercados:
            categorias = [str(c).lower() for c in (m.get("categories") or [])]
            titulo = str(m.get("title") or "").strip()

            es_deporte = (
                "sports" in categorias
                or "football matches" in categorias
                or " vs " in titulo.lower()
                or " vs. " in titulo.lower()
            )
            if not es_deporte:
                continue

            # Ignorar mercados multi-outcome sin precios binarios directos o props de mapas
            precios_base = m.get("prices")
            trade_buy = ((m.get("tradePrices") or {}).get("buy") or {}).get("market")
            precios_usar = trade_buy if (isinstance(trade_buy, list) and len(trade_buy) == 2) else precios_base

            if not isinstance(precios_usar, list) or len(precios_usar) != 2:
                continue

            try:
                p1 = float(precios_usar[0])
                p2 = float(precios_usar[1])
            except (ValueError, TypeError):
                continue

            if not (0.01 < p1 < 0.99 and 0.01 < p2 < 0.99):
                continue

            cuota_1 = round(1.0 / p1, 4)
            cuota_2 = round(1.0 / p2, 4)

            meta = m.get("metadata") or {}
            labels = meta.get("outcomeLabels") or {}
            partes_vs = re.split(r"\s+vs\.?\s+", titulo, flags=re.IGNORECASE)

            if labels.get("0") and labels.get("1"):
                lado_1 = str(labels["0"])
                lado_2 = str(labels["1"])
            elif len(partes_vs) == 2:
                lado_1 = partes_vs[0].strip()
                lado_2 = partes_vs[1].strip()
            else:
                continue

            # Descartar props secundarios como "Map 1 Winner" o "to win by 2 or more goals"
            if ":" in titulo or "to win by" in titulo.lower():
                tipo_mercado = "Prop (Especial)"
            else:
                tipo_mercado = "Ganador (Moneyline)"

            ts_inicio = (
                meta.get("startMatchTimestampInUTC")
                or m.get("startAt")
                or m.get("expirationTimestamp")
                or ""
            )
            deporte_es, liga_es = _inferir_deporte_liga_limitless(m)

            vol_usd = float(m.get("volumeFormatted") or 0.0)
            liq_estimada = max(round(vol_usd, 2), 250.0)

            filas_normalizadas.append(
                {
                    "Plataforma": "Limitless",
                    "Deporte": deporte_es,
                    "Liga": liga_es,
                    "Evento": titulo,
                    "Inicio_UTC": str(ts_inicio),
                    "Tipo_Mercado": tipo_mercado,
                    "Linea": "N/A",
                    "Lado_1": lado_1,
                    "Cuota_Taker_1": cuota_1,
                    "Liquidez_1_USD": liq_estimada,
                    "Lado_2": lado_2,
                    "Cuota_Taker_2": cuota_2,
                    "Liquidez_2_USD": liq_estimada,
                    "Overround_Libro_Pct": calcular_overround_pct(cuota_1, cuota_2),
                    "ID_Mercado": str(m.get("slug") or m.get("conditionId") or m.get("id")),
                }
            )

    return filas_normalizadas


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    datos = extraer_limitless(max_paginas=6)
    print(f"Total mercados deportivos extraídos de Limitless Exchange: {len(datos)}")
    for muestra in datos[:8]:
        print(muestra)
