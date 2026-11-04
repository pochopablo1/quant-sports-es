"""
Extractor de Mercados Cripto de Corto Plazo en Polymarket V2 (Gamma API + CLOB).
Identifica contratos de opciones digitales sobre BTC, ETH, SOL, XRP y POL:
1. `EUROPEAN_ABOVE`: "Will the price of Bitcoin be above $72,000 on November 5?" -> Opción Digital Europea P(S_T > K).
2. `BARRIER_REACH`: "Will Bitcoin reach $85,000 on November 4?" -> Opción One-Touch Superior P(max S_t >= K).
3. `BARRIER_DIP`: "Will Bitcoin dip to $68,000 on November 4?" -> Opción One-Touch Inferior P(min S_t <= K).
"""
from datetime import datetime, timezone
import json
import logging
import re
from typing import Dict, Any, List, Optional
import requests

logger = logging.getLogger("OraculoPolymarketCrypto")

URL_GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"

MAPA_NOMBRES_TICKER = {
    "bitcoin": "BTC",
    "btc": "BTC",
    "ethereum": "ETH",
    "ether": "ETH",
    "eth": "ETH",
    "solana": "SOL",
    "sol": "SOL",
    "ripple": "XRP",
    "xrp": "XRP",
    "polygon": "POL",
    "matic": "POL",
}


def _parsear_json_lista(val: Any) -> List[Any]:
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            res = json.loads(val)
            return res if isinstance(res, list) else []
        except Exception:
            return []
    return []


def _extraer_ticker_y_strike(pregunta: str, titulo_evento: str) -> Optional[Dict[str, Any]]:
    """
    Extrae (ticker, tipo_opcion, strike_usd) desde la pregunta de Polymarket.
    Ejemplos:
      - "Will the price of Bitcoin be above $72,000 on November 5?" -> ('BTC', 'EUROPEAN_ABOVE', 72000.0)
      - "Will Bitcoin reach $85,000 on November 4?" -> ('BTC', 'BARRIER_REACH', 85000.0)
      - "Will Ethereum dip to $2,200 November 2-8?" -> ('ETH', 'BARRIER_DIP', 2200.0)
    """
    texto = f"{titulo_evento} {pregunta}".lower()
    ticker_detectado = None
    for palabra, tk in MAPA_NOMBRES_TICKER.items():
        if re.search(rf"\b{palabra}\b", texto):
            ticker_detectado = tk
            break
    if not ticker_detectado:
        return None

    # Buscar monto en dólares ($72,000, $2,500.50, $100k)
    m_precio = re.search(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)\s*(k)?", pregunta, re.IGNORECASE)
    if not m_precio:
        return None

    try:
        valor_num = float(m_precio.group(1).replace(",", ""))
        if m_precio.group(2) and m_precio.group(2).lower() == "k":
            valor_num *= 1000.0
    except ValueError:
        return None

    if valor_num <= 0:
        return None

    q_low = pregunta.lower()
    if "be above" in q_low or "close above" in q_low or "above $" in q_low:
        tipo_op = "EUROPEAN_ABOVE"
    elif "dip to" in q_low or "drop to" in q_low or "fall to" in q_low or "below $" in q_low:
        tipo_op = "BARRIER_DIP"
    elif "reach" in q_low or "hit" in q_low:
        tipo_op = "BARRIER_REACH"
    else:
        return None

    return {
        "ticker": ticker_detectado,
        "tipo_opcion": tipo_op,
        "strike_usd": valor_num,
    }


def extraer_mercados_polymarket_cripto(max_horas_vencimiento: float = 144.0) -> List[Dict[str, Any]]:
    """
    Extrae todos los mercados de opciones digitales cripto en Polymarket que vencen dentro
    de las próximas `max_horas_vencimiento` (por defecto 6 días = rotación rápida de capital).
    """
    mercados_extraidos: List[Dict[str, Any]] = []
    ahora_utc = datetime.now(tz=timezone.utc)

    try:
        resp = requests.get(
            URL_GAMMA_EVENTS,
            params={
                "active": "true",
                "closed": "false",
                "tag_slug": "crypto",
                "order": "volume24hr",
                "ascending": "false",
                "limit": "80",
            },
            timeout=12,
        )
        eventos = resp.json() if resp.status_code == 200 else []
    except Exception as exc:
        logger.error("Error consultando Polymarket Cripto: %s", exc)
        return mercados_extraidos

    for ev in eventos:
        titulo_ev = str(ev.get("title", "")).strip()
        for mkt in ev.get("markets") or []:
            if not mkt.get("active", True) or mkt.get("closed", False):
                continue

            end_str = str(mkt.get("endDate") or ev.get("endDate") or "").strip()
            if not end_str:
                continue
            try:
                dt_end = datetime.fromisoformat(end_str.replace("Z", "+00:00")).astimezone(timezone.utc)
            except ValueError:
                continue

            horas_restantes = (dt_end - ahora_utc).total_seconds() / 3600.0
            # Filtrar mercados que vencen entre 20 minutos y `max_horas_vencimiento` horas
            if horas_restantes < 0.35 or horas_restantes > max_horas_vencimiento:
                continue

            pregunta = str(mkt.get("question") or titulo_ev).strip()
            meta = _extraer_ticker_y_strike(pregunta, titulo_ev)
            if not meta:
                continue

            outcomes = _parsear_json_lista(mkt.get("outcomes"))
            precios = _parsear_json_lista(mkt.get("outcomePrices"))
            tokens = _parsear_json_lista(mkt.get("clobTokenIds"))
            if len(outcomes) != 2 or len(precios) != 2 or len(tokens) != 2:
                continue

            best_ask_yes = float(mkt.get("bestAsk") or precios[0] or 0.0)
            best_bid_yes = float(mkt.get("bestBid") or precios[0] or 0.0)
            spread = float(mkt.get("spread") or 0.0)

            if best_ask_yes <= 0.02 or best_ask_yes >= 0.98 or spread > 0.10:
                continue

            precio_ask_yes = round(best_ask_yes, 4)
            precio_ask_no = round(1.0 - best_bid_yes, 4) if best_bid_yes > 0.01 else round(float(precios[1]), 4)
            if not (0.02 < precio_ask_no < 0.98):
                continue

            liq_total = float(mkt.get("liquidityNum") or mkt.get("liquidity") or 0.0)
            liq_lado = round(liq_total / 2.0, 2)
            cond_id = str(mkt.get("conditionId") or mkt.get("id") or "")

            mercados_extraidos.append(
                {
                    "Ticker": meta["ticker"],
                    "Evento": titulo_ev,
                    "Pregunta": pregunta,
                    "Tipo_Opcion": meta["tipo_opcion"],
                    "Strike_USD": meta["strike_usd"],
                    "Vencimiento_UTC": dt_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "Horas_Restantes": round(horas_restantes, 2),
                    "Precio_Ask_Yes": precio_ask_yes,
                    "Cuota_Yes": round(1.0 / precio_ask_yes, 4),
                    "Precio_Ask_No": precio_ask_no,
                    "Cuota_No": round(1.0 / precio_ask_no, 4),
                    "Liquidez_Lado_USD": liq_lado,
                    "ID_Mercado": f"{cond_id}::{tokens[0]}::{tokens[1]}",
                }
            )

    return mercados_extraidos


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mkts = extraer_mercados_polymarket_cripto()
    print(f"Total mercados cripto de corto plazo en Polymarket: {len(mkts)}")
    for m in mkts[:10]:
        print(f"  [{m['Ticker']}] {m['Pregunta']} | Tipo={m['Tipo_Opcion']} | Strike=${m['Strike_USD']} | Horas={m['Horas_Restantes']}h | Yes=${m['Precio_Ask_Yes']} | No=${m['Precio_Ask_No']}")
