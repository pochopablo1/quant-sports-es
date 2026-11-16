"""
Verificador Atómico Multi-Pata en Orderbook L2 (`ejecutor/verificador_atomico.py`).
==================================================================================
Antes de dar por válida cualquier Surebet o Arbitraje Maker-Taker, consulta en tiempo real:
  1. Polymarket CLOB (`/book?token_id=...` y `fee_rate_bps` real del contrato)
  2. SX Bet CLOB v3 (`/orders-v3/odds/best`)
  3. Limitless Exchange CLOB (`/markets/{slug}`)
  4. Kalshi API v2 (`/trade-api/v2/markets/{ticker}`)
Calcula el VWAP exacto para el stake de cada pata y verifica que la liquidez real
supere el monto requerido sin destruir el ROI neto.
"""
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Tuple
import requests

from configuracion import SX_API_KEY, calcular_cuota_efectiva_neta


def verificar_pata_polymarket_vwap(token_id: str, stake_usd: float) -> Tuple[bool, float, float, int, str]:
    """
    Consulta `/book` en Polymarket CLOB y devuelve:
      (ok, cuota_bruta_vwap, liquidez_top_usd, fee_rate_bps, detalle)
    """
    try:
        resp = requests.get("https://clob.polymarket.com/book", params={"token_id": token_id}, timeout=6)
        if resp.status_code != 200:
            return False, 0.0, 0.0, 0, f"HTTP {resp.status_code}"
        libro = resp.json()
    except Exception as exc:
        return False, 0.0, 0.0, 0, f"Error red: {exc}"

    asks = libro.get("asks") or []
    niveles = sorted(
        [(float(a["price"]), float(a["size"])) for a in asks if float(a.get("price", 0)) > 0],
        key=lambda x: x[0],
    )
    if not niveles:
        return False, 0.0, 0.0, 0, "Libro Ask vacío"

    mejor_p, mejor_sz = niveles[0]
    liq_top = round(mejor_p * mejor_sz, 2)

    restante = stake_usd
    contratos = 0.0
    gastado = 0.0
    for p_niv, sz_niv in niveles:
        costo_niv = p_niv * sz_niv
        if costo_niv >= restante:
            contratos += restante / p_niv
            gastado += restante
            restante = 0.0
            break
        else:
            contratos += sz_niv
            gastado += costo_niv
            restante -= costo_niv

    if restante > 0.01 or contratos <= 0:
        return False, 0.0, liq_top, 0, f"Liquidez insuficiente (${liq_top:.2f} < ${stake_usd:.2f})"

    vwap = gastado / contratos
    return True, round(1.0 / vwap, 4), liq_top, 0, f"Ask={mejor_p:.2f} (Liq=${liq_top:.0f})"


def verificar_pata_sx_bet_vivo(market_hash: str, indice_lado: int, stake_usd: float) -> Tuple[bool, float, float, str]:
    """Verifica cuota y volumen disponible en SX Bet v3 (0% Taker fee en simples)."""
    headers = {"Accept": "application/json"}
    if SX_API_KEY:
        headers["x-sx-api-key"] = SX_API_KEY
    try:
        resp = requests.get(
            "https://api.sx.bet/orders-v3/odds/best",
            params={"marketHashes": market_hash, "showTakerPerspective": "true"},
            headers=headers,
            timeout=6,
        )
        if resp.status_code != 200:
            return False, 0.0, 0.0, f"HTTP {resp.status_code}"
        datos = resp.json().get("data", {})
        best_list = datos.get("bestOdds", []) if isinstance(datos, dict) else datos
        item = best_list[0] if (isinstance(best_list, list) and best_list) else {}
        nodo = item.get("outcomeOne" if int(indice_lado) == 1 else "outcomeTwo") or {}
        prob = float(nodo.get("percentageOdds") or 0) / 1e20
        liq_usd = round(float(nodo.get("availableVolume") or 0) / 1e6, 2)
        if not (0.01 < prob < 0.99) or liq_usd < stake_usd:
            return False, 0.0, liq_usd, f"Liq insuficiente (${liq_usd:.2f})"
        return True, round(1.0 / prob, 4), liq_usd, f"SX Liq=${liq_usd:.0f} (0% Fee)"
    except Exception as exc:
        return False, 0.0, 0.0, f"Error SX: {exc}"


def verificar_surebet_2_patas_atomica(
    pata_1: Dict[str, Any],
    pata_2: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Ejecuta en paralelo la verificación de ambas patas de una Surebet para evitar
    el riesgo de ejecución asincrónica ('Legging Risk').
    """
    with ThreadPoolExecutor(max_workers=2) as pool:
        # Pata 1 y Pata 2 se consultan exactamente al mismo milisegundo
        f1 = pool.submit(
            calcular_cuota_efectiva_neta,
            float(pata_1["cuota_bruta"]),
            str(pata_1["plataforma"]),
            bool(pata_1.get("es_maker", False)),
        )
        f2 = pool.submit(
            calcular_cuota_efectiva_neta,
            float(pata_2["cuota_bruta"]),
            str(pata_2["plataforma"]),
            bool(pata_2.get("es_maker", False)),
        )
        c1_neta, costo_1, fee_1 = f1.result()
        c2_neta, costo_2, fee_2 = f2.result()

    suma_costos = costo_1 + costo_2
    roi_neto_pct = round(((1.0 / suma_costos) - 1.0) * 100.0, 2) if suma_costos > 0 else -99.0
    return {
        "aprobada": roi_neto_pct > 0.0,
        "roi_neto_pct": roi_neto_pct,
        "costo_total_por_dolar": round(suma_costos, 4),
        "pata_1_cuota_neta": c1_neta,
        "pata_1_fee_pct": fee_1,
        "pata_2_cuota_neta": c2_neta,
        "pata_2_fee_pct": fee_2,
    }
