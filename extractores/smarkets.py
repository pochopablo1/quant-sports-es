"""
Extractor de Smarkets Exchange (API v3).
Nota importante sobre acceso:
Smarkets aplica geo-bloqueo por IP (Cloudflare Turnstile 403) para conexiones fuera de UK/EU
a menos que se configure `SMARKETS_PROXIES` o `SMARKETS_SESSION_TOKEN` en el archivo `.env`.
El módulo incluye el parser completo de eventos, mercados y cotizaciones (bids/offers en escala 1/10000)
y se degrada limpiamente avisando si detecta bloqueo regional en la IP actual.
"""
import logging
import os
from typing import List, Dict, Any
from configuracion import calcular_overround_pct

logger = logging.getLogger(__name__)

URL_SMARKETS_BASE = "https://api.smarkets.com/v3"


def _obtener_sesion_http():
    """Usa curl_cffi con impersonación TLS de navegador si está disponible."""
    try:
        from curl_cffi import requests as creq
        return creq
    except ImportError:
        import requests
        return requests


def extraer_smarkets(limite_eventos: int = 40) -> List[Dict[str, Any]]:
    """
    Consulta Smarkets API v3 (`/v3/events/`, `/v3/events/{ids}/markets/`, `/v3/markets/{ids}/quotes/`).
    En Smarkets:
      - Para un Taker que quiere APOSTAR A FAVOR (Back), toma la mejor oferta de los Makers (`offers[0].price`),
        donde el precio viene en porcentaje implícito multiplicado por 100 (ej. 5000 = 50% = cuota 2.00).
      - `cuota_decimal = 10000.0 / offer_price_basis_points`.
    """
    filas_normalizadas: List[Dict[str, Any]] = []
    req = _obtener_sesion_http()

    proxy_url = os.getenv("SMARKETS_PROXY", "").strip()
    token_smarkets = os.getenv("SMARKETS_SESSION_TOKEN", "").strip()

    headers = {"Accept": "application/json"}
    if token_smarkets:
        headers["Authorization"] = f"Session-Token {token_smarkets}"

    kwargs_extra: Dict[str, Any] = {"timeout": 12, "headers": headers}
    if proxy_url:
        kwargs_extra["proxies"] = {"https": proxy_url, "http": proxy_url}
    if hasattr(req, "Session") and "curl_cffi" in getattr(req, "__name__", ""):
        kwargs_extra["impersonate"] = "chrome"

    parametros_ev = {
        "state": "upcoming",
        "type": ["basketball_match", "american_football_match", "football_match"],
        "limit": str(limite_eventos),
    }

    try:
        resp_ev = req.get(f"{URL_SMARKETS_BASE}/events/", params=parametros_ev, **kwargs_extra)
        if resp_ev.status_code == 403 and "Security Check" in resp_ev.text:
            logger.warning(
                "Smarkets API devolvió 403 (Geo-bloqueo UK/EU de Cloudflare en tu IP actual). "
                "Para activarlo desde Sudamérica, agrega SMARKETS_PROXY=http://... en tu .env."
            )
            return filas_normalizadas
        resp_ev.raise_for_status()
        eventos = resp_ev.json().get("events") or []
    except Exception as exc:
        logger.warning("No se pudo conectar a Smarkets API v3: %s", exc)
        return filas_normalizadas

    if not eventos:
        return filas_normalizadas

    mapa_eventos = {str(e["id"]): e for e in eventos if "id" in e}
    ids_eventos = ",".join( list(mapa_eventos.keys())[:30] )

    try:
        resp_mkts = req.get(
            f"{URL_SMARKETS_BASE}/events/{ids_eventos}/markets/", **kwargs_extra
        )
        mercados = resp_mkts.json().get("markets") or []
    except Exception as exc:
        logger.warning("Error consultando mercados de Smarkets: %s", exc)
        return filas_normalizadas

    # Filtrar mercados principales (winner / moneyline / to-win)
    mercados_principales = [
        m for m in mercados if m.get("market_type", {}).get("name") in ("winner", "to-win", "moneyline")
    ]
    if not mercados_principales:
        return filas_normalizadas

    ids_mercados = ",".join(str(m["id"]) for m in mercados_principales[:30])

    try:
        resp_contratos = req.get(
            f"{URL_SMARKETS_BASE}/markets/{ids_mercados}/contracts/", **kwargs_extra
        )
        contratos = resp_contratos.json().get("contracts") or []
        resp_quotes = req.get(
            f"{URL_SMARKETS_BASE}/markets/{ids_mercados}/quotes/", **kwargs_extra
        )
        quotes = resp_quotes.json() or {}
    except Exception as exc:
        logger.warning("Error consultando contratos/quotes de Smarkets: %s", exc)
        return filas_normalizadas

    contratos_por_mercado: Dict[str, List[Dict[str, Any]]] = {}
    for c in contratos:
        mid = str(c.get("market_id"))
        contratos_por_mercado.setdefault(mid, []).append(c)

    for m in mercados_principales:
        mid = str(m.get("id"))
        ev = mapa_eventos.get(str(m.get("event_id")), {})
        lista_c = contratos_por_mercado.get(mid, [])
        if len(lista_c) != 2:
            continue

        c1, c2 = lista_c[0], lista_c[1]
        q1 = quotes.get(str(c1.get("id")), {})
        q2 = quotes.get(str(c2.get("id")), {})

        offers_1 = q1.get("offers") or []
        offers_2 = q2.get("offers") or []
        if not offers_1 or not offers_2:
            continue

        precio_bp_1 = float(offers_1[0].get("price", 0))
        precio_bp_2 = float(offers_2[0].get("price", 0))
        if precio_bp_1 <= 100 or precio_bp_2 <= 100:
            continue

        cuota_1 = round(10000.0 / precio_bp_1, 4)
        cuota_2 = round(10000.0 / precio_bp_2, 4)
        liq_1 = round(float(offers_1[0].get("quantity", 0)) / 10000.0, 2)
        liq_2 = round(float(offers_2[0].get("quantity", 0)) / 10000.0, 2)

        filas_normalizadas.append(
            {
                "Plataforma": "Smarkets",
                "Deporte": str(ev.get("type", "Deportes")),
                "Liga": "Smarkets Exchange",
                "Evento": str(ev.get("name", f"{c1.get('name')} vs {c2.get('name')}")),
                "Inicio_UTC": str(ev.get("start_datetime", "")),
                "Tipo_Mercado": "Ganador (Moneyline)",
                "Linea": "N/A",
                "Lado_1": str(c1.get("name", "Lado 1")),
                "Cuota_Taker_1": cuota_1,
                "Liquidez_1_USD": liq_1,
                "Lado_2": str(c2.get("name", "Lado 2")),
                "Cuota_Taker_2": cuota_2,
                "Liquidez_2_USD": liq_2,
                "Overround_Libro_Pct": calcular_overround_pct(cuota_1, cuota_2),
                "ID_Mercado": f"smk_{mid}",
            }
        )

    return filas_normalizadas


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    datos = extraer_smarkets()
    print(f"Total mercados extraídos de Smarkets: {len(datos)}")
