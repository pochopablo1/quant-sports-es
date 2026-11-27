"""C1 · Cálculo del arbitraje de rescate en modo taker atómico (sin red, testeable).

Para cada ruta: con `tam` USD compro el token en el DEX y lo rescato en el protocolo.
  neto = valor_rescatado − tam − gas
"""
from __future__ import annotations


def neto_liquity(tam_usd: float, stables_recibidos: float, tasa_canje: float,
                 costo_venta_garantia: float, gas_usd: float) -> float:
    """Liquity V2 y forks: canjear 1 stable da 1 USD de garantía menos la tasa de canje.
    La garantía (ETH, HYPE, BTC…) se vende después: `costo_venta_garantia` (fracción)."""
    valor = stables_recibidos * (1 - tasa_canje) * (1 - costo_venta_garantia)
    return valor - tam_usd - gas_usd


def neto_directo(tam_usd: float, recibido_usd: float, gas_usd: float) -> float:
    """ERC-4626 (`previewRedeem`) o PSM (`previewSwapExactIn`): el rescate ya devuelve USD."""
    return recibido_usd - tam_usd - gas_usd


def precio_marginal(stables_por_1usd: float | None) -> float | None:
    """Precio del token en USD con un ticket chiquito (para registrar toques del modo maker)."""
    if not stables_por_1usd:
        return None
    return 1.0 / stables_por_1usd
