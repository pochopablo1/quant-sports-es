"""C14 · Cálculo de cruces USDT/ARS entre exchanges (sin red, testeable)."""
from __future__ import annotations

import statistics

from comun.utiles import vwap


def precios_para_tamano(libros: dict, tam_usdt: float, mid_ars: float) -> dict:
    """Para cada exchange devuelve {'compra': ARS por USDT pagando, 'venta': ARS por USDT cobrando}
    para mover `tam_usdt`. `libros[ex]` puede ser:
      - {'asks': [(precio, cant)], 'bids': [(precio, cant)]}  (libro real por API), o
      - {'por_monto': {tam: (ask, bid)}}                       (CriptoYa, precio por monto)."""
    out = {}
    for ex, lb in libros.items():
        if "por_monto" in lb:
            par = lb["por_monto"].get(tam_usdt)
            if par and par[0] > 0 and par[1] > 0:
                out[ex] = {"compra": par[0], "venta": par[1]}
            continue
        a = vwap(lb.get("asks", []), tam_usdt, mid_ars)
        b = vwap(lb.get("bids", []), tam_usdt, mid_ars)
        if a and b:
            out[ex] = {"compra": a[0], "venta": b[0]}
    return out


def cruces(libros: dict, cfg_ex: dict, tamanos: list[float], slippage_extra: float,
           retiro_usdt: float, fraccion_rebalanceo: float) -> list[dict]:
    """Todos los cruces con neto > 0. Compra USDT en B (paga ask + taker_B) y vende en A
    (cobra bid − taker_A). Descuenta slippage extra y el retiro de USDT prorrateado."""
    medios = [v for lb in libros.values() for v in _mid(lb)]
    if not medios:
        return []
    mid = statistics.median(medios)
    res = []
    for tam in tamanos:
        precios = precios_para_tamano(libros, tam, mid)
        for b, pb in precios.items():          # donde compro
            for a, pa in precios.items():      # donde vendo
                if a == b:
                    continue
                fb = cfg_ex.get(b, {}).get("taker", 0.01)
                fa = cfg_ex.get(a, {}).get("taker", 0.01)
                costo = pb["compra"] * tam * (1 + fb)
                cobro = pa["venta"] * tam * (1 - fa) * (1 - slippage_extra)
                retiro_ars = retiro_usdt * fraccion_rebalanceo * mid
                neto_ars = cobro - costo - retiro_ars
                if neto_ars <= 0:
                    continue
                con_api = bool(cfg_ex.get(a, {}).get("api_trading")) and bool(cfg_ex.get(b, {}).get("api_trading"))
                res.append({
                    "clave": f"{b}->{a}", "grupo": "-".join(sorted((a, b))),
                    "direccion": f"{b}->{a}", "con_api": con_api, "tam_usd": tam,
                    "neto_usd": neto_ars / mid, "neto_pct": neto_ars / costo,
                    "detalle": {"compra_en": b, "precio_compra": pb["compra"],
                                "vende_en": a, "precio_venta": pa["venta"], "mid": mid},
                })
    return res


def _mid(lb: dict):
    if "por_monto" in lb:
        for ask, bid in lb["por_monto"].values():
            if ask > 0 and bid > 0:
                yield (ask + bid) / 2
                return
        return
    if lb.get("asks") and lb.get("bids"):
        yield (lb["asks"][0][0] + lb["bids"][0][0]) / 2
