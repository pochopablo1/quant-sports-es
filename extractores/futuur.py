"""
Extractor de Futuur (API v1 - Mercados de Predicción en USDC).
Consulta `https://api.futuur.com/api/v1/markets/` buscando enfrentamientos deportivos activos (`vs.`),
extrayendo precios en moneda real (`USDC`) y liquidez real en dólares (`liquidity_real_money`).
Soporta tanto mercados de 2 vías (Moneyline NBA/NFL/Tenis/MMA/eSports) como 3 vías (Fútbol 1X2).
"""
import logging
import re
from typing import List, Dict, Any, Tuple
import requests
from configuracion import calcular_overround_pct

logger = logging.getLogger(__name__)

URL_FUTUUR_MARKETS = "https://api.futuur.com/api/v1/markets/"


def _inferir_deporte_y_liga_futuur(m: Dict[str, Any]) -> Tuple[str, str]:
    cat_info = m.get("category") or {}
    cat_titulo = str(cat_info.get("title") or "Deportes").strip()
    # Limpiar emojis de banderas al inicio del nombre de la liga
    liga_limpia = re.sub(r"^[^\w\s]+\s*", "", cat_titulo).strip() or cat_titulo

    tags = [str(t.get("name", "")).lower() for t in (m.get("tags") or []) if isinstance(t, dict)]
    texto = " ".join(tags + [cat_titulo.lower(), str(m.get("title", "")).lower()])

    if any(k in texto for k in ("nba", "basketball", "wnba", "euroleague")):
        return "Básquetbol", liga_limpia
    if any(k in texto for k in ("nfl", "american football")):
        return "Fútbol Americano", liga_limpia
    if any(k in texto for k in ("mlb", "baseball")):
        return "Béisbol", liga_limpia
    if any(k in texto for k in ("nhl", "hockey")):
        return "Hockey sobre Hielo", liga_limpia
    if any(k in texto for k in ("ufc", "mma", "boxing", "bellator")):
        return "MMA / Boxeo", liga_limpia
    if any(k in texto for k in ("tennis", "atp", "wta")):
        return "Tenis", liga_limpia
    if any(k in texto for k in ("esports", "counter-strike", "dota", "valorant", "league of legends")):
        return "eSports", liga_limpia
    return "Fútbol", liga_limpia


def extraer_futuur(max_paginas: int = 4) -> List[Dict[str, Any]]:
    """
    Recorre los mercados abiertos de enfrentamientos (`search=vs.`) en Futuur API v1
    y los convierte al esquema estándar en español usando precios en USDC.
    """
    filas_normalizadas: List[Dict[str, Any]] = []
    headers = {
        "Accept": "application/json",
        "User-Agent": "QuantSportsMarketAgent/1.0",
    }

    tamano_pagina = 50
    ids_vistos = set()

    for pagina in range(max_paginas):
        parametros = {
            "search": "vs.",
            "status": "open",
            "limit": str(tamano_pagina),
            "offset": str(pagina * tamano_pagina),
        }
        try:
            resp = requests.get(URL_FUTUUR_MARKETS, params=parametros, headers=headers, timeout=12)
            if resp.status_code != 200:
                logger.warning("Futuur API devolvió %s en pág %d", resp.status_code, pagina + 1)
                break
            payload = resp.json()
            mercados = payload.get("results") if isinstance(payload, dict) else payload
            if not isinstance(mercados, list) or not mercados:
                break
        except Exception as exc:
            logger.error("Error consultando Futuur API pág %d: %s", pagina + 1, exc)
            break

        for m in mercados:
            if m.get("status") != "open":
                continue

            mid = m.get("id")
            if mid in ids_vistos:
                continue
            ids_vistos.add(mid)

            titulo = str(m.get("title") or "").strip()
            if " vs. " not in titulo.lower() and " vs " not in titulo.lower():
                continue

            outcomes = [o for o in (m.get("outcomes") or []) if not o.get("disabled")]
            if len(outcomes) not in (2, 3):
                continue

            inicio_utc = (
                m.get("event_start_date")
                or m.get("bet_end_date")
                or m.get("resolve_date")
                or ""
            )
            deporte_es, liga_es = _inferir_deporte_y_liga_futuur(m)

            liq_real = float(m.get("liquidity_real_money") or 0.0)
            liq_lado = round(liq_real / 2.0, 2)

            # --- Caso 1: Mercado de 2 vías (Moneyline NBA, NFL, Tenis, MMA, eSports) ---
            if len(outcomes) == 2:
                o1, o2 = outcomes[0], outcomes[1]
                precios_1 = o1.get("price") or {}
                precios_2 = o2.get("price") or {}
                p1 = float(precios_1.get("USDC") or precios_1.get("OOM") or 0.0)
                p2 = float(precios_2.get("USDC") or precios_2.get("OOM") or 0.0)

                if not (0.01 < p1 < 0.99 and 0.01 < p2 < 0.99):
                    continue

                c1 = round(1.0 / p1, 4)
                c2 = round(1.0 / p2, 4)

                filas_normalizadas.append(
                    {
                        "Plataforma": "Futuur",
                        "Deporte": deporte_es,
                        "Liga": liga_es,
                        "Evento": titulo,
                        "Inicio_UTC": str(inicio_utc),
                        "Tipo_Mercado": "Ganador (Moneyline)",
                        "Linea": "N/A",
                        "Lado_1": str(o1.get("title", "Lado 1")),
                        "Cuota_Taker_1": c1,
                        "Liquidez_1_USD": liq_lado,
                        "Lado_2": str(o2.get("title", "Lado 2")),
                        "Cuota_Taker_2": c2,
                        "Liquidez_2_USD": liq_lado,
                        "Overround_Libro_Pct": calcular_overround_pct(c1, c2),
                        "ID_Mercado": f"fut_{mid}",
                    }
                )

            # --- Caso 2: Mercado de 3 vías (Fútbol 1X2 con 'Tie'/'Draw') ---
            elif len(outcomes) == 3:
                o_empate = next(
                    (o for o in outcomes if str(o.get("title", "")).lower() in ("tie", "draw", "empate")),
                    None,
                )
                o_equipos = [
                    o for o in outcomes if str(o.get("title", "")).lower() not in ("tie", "draw", "empate")
                ]
                if len(o_equipos) == 2 and o_empate:
                    o1, o2 = o_equipos[0], o_equipos[1]
                    p1 = float((o1.get("price") or {}).get("USDC") or 0.0)
                    p2 = float((o2.get("price") or {}).get("USDC") or 0.0)
                    p_tie = float((o_empate.get("price") or {}).get("USDC") or 0.0)

                    if not (0.01 < p1 < 0.99 and 0.01 < p2 < 0.99 and 0.01 < p_tie < 0.99):
                        continue

                    c1 = round(1.0 / p1, 4)
                    c2 = round(1.0 / p2, 4)
                    c_tie = round(1.0 / p_tie, 4)
                    overround_3way = round((p1 + p2 + p_tie - 1.0) * 100.0, 2)

                    filas_normalizadas.append(
                        {
                            "Plataforma": "Futuur",
                            "Deporte": "Fútbol",
                            "Liga": liga_es,
                            "Evento": titulo,
                            "Inicio_UTC": str(inicio_utc),
                            "Tipo_Mercado": "Ganador (1X2 - Sin Empate Ref)",
                            "Linea": f"Empate@{c_tie}",
                            "Lado_1": str(o1.get("title", "Local")),
                            "Cuota_Taker_1": c1,
                            "Liquidez_1_USD": liq_lado,
                            "Lado_2": str(o2.get("title", "Visitante")),
                            "Cuota_Taker_2": c2,
                            "Liquidez_2_USD": liq_lado,
                            "Overround_Libro_Pct": overround_3way,
                            "ID_Mercado": f"fut_{mid}",
                        }
                    )

        if isinstance(payload, dict) and not payload.get("next"):
            break

    return filas_normalizadas


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    datos = extraer_futuur(max_paginas=4)
    print(f"Total mercados extraídos de Futuur: {len(datos)}")
    for muestra in datos[:8]:
        print(muestra)
