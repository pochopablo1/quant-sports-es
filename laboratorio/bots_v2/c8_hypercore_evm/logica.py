"""C8 · Cálculo de brechas HyperCore (libro) vs AMM de HyperEVM (sin red, testeable)."""
from __future__ import annotations

from comun.utiles import vwap


def niveles_l2(libro: dict):
    """Respuesta de l2Book → (bids, asks) como listas de (precio, cantidad)."""
    lv = libro.get("levels") or [[], []]
    bids = [(float(x["px"]), float(x["sz"])) for x in lv[0]]
    asks = [(float(x["px"]), float(x["sz"])) for x in lv[1]]
    return bids, asks


def brecha_core_a_evm(asks_core, tam_usd: float, fee_core: float, venta_evm_usd) -> dict | None:
    """Compro en Core con `tam_usd` USDC y vendo los tokens en el AMM.
    `venta_evm_usd(cantidad_tokens) -> USD recibidos` (ya con fee del pool)."""
    r = vwap(asks_core, tam_usd)
    if not r:
        return None
    tokens = r[1] * (1 - fee_core)
    usd = venta_evm_usd(tokens)
    if usd is None:
        return None
    return {"bruto_usd": usd - tam_usd, "precio_core": r[0], "tokens": tokens}


def brecha_evm_a_core(bids_core, tam_usd: float, fee_core: float, compra_evm_tokens) -> dict | None:
    """Compro en el AMM con `tam_usd` y vendo en el libro de Core.
    `compra_evm_tokens(usd) -> tokens recibidos`."""
    tokens = compra_evm_tokens(tam_usd)
    if not tokens:
        return None
    restante, cobro = tokens, 0.0
    for px, sz in bids_core:
        tomar = min(sz, restante)
        cobro += tomar * px
        restante -= tomar
        if restante <= 1e-12:
            break
    if restante > 1e-12:
        return None  # el libro no alcanza
    usd = cobro * (1 - fee_core)
    return {"bruto_usd": usd - tam_usd, "precio_core_bid": bids_core[0][0], "tokens": tokens}


def neto(bruto_usd: float, tam_usd: float, gas_usd: float, rebalanceo_usd: float) -> tuple[float, float]:
    n = bruto_usd - gas_usd - rebalanceo_usd
    return n, n / tam_usd


def excluir_top(tokens_vol: dict[str, float], n: int) -> set[str]:
    """Los `n` tokens con más volumen diario (se excluyen del universo)."""
    return set(sorted(tokens_vol, key=lambda k: -tokens_vol[k])[:n])
