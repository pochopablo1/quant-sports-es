"""C15 · Cálculo del ciclo de MEP entre dos bonos (sin red, testeable).

Precios por 100 de valor nominal (VN), como cotizan en BYMA. Ciclo con X barato e Y caro:
  1) compra X en pesos (ask_X$)    2) vende X en dólares (bid_XD)   -> pesos a dólares
  3) compra Y en dólares (ask_YD)  4) vende Y en pesos (bid_Y$)     -> dólares a pesos
Cada pata paga `costo_pata` (comisión + derechos de mercado, con IVA) y 1 tick de slippage.
"""
from __future__ import annotations


def costo_pata(comision: float, derechos: float, iva: float) -> float:
    return (comision + derechos) * (1 + iva)


def costo_ciclo(c: float) -> float:
    """Costo total aproximado de las 4 patas (sin slippage)."""
    return 1 - ((1 - c) / (1 + c)) ** 2


def ciclo(px: dict, x: str, y: str, c: float, tick_ars: float, tick_usd: float,
          tam_max_usd: float) -> dict | None:
    """`px[sim] = {'bid','bid_q','ask','ask_q'}` (cantidades en VN). Devuelve el resultado
    del ciclo X→Y o None si falta alguna punta."""
    try:
        ax, bxd = px[x]["ask"] + tick_ars, px[x + "D"]["bid"] - tick_usd
        ayd, by = px[y + "D"]["ask"] + tick_usd, px[y]["bid"] - tick_ars
    except KeyError:
        return None
    if min(ax, bxd, ayd, by) <= 0:
        return None
    usd_por_ars = bxd * (1 - c) / (ax * (1 + c))
    ars_por_usd = by * (1 - c) / (ayd * (1 + c))
    neto_pct = usd_por_ars * ars_por_usd - 1
    mep_compra = ax / bxd     # pesos por dólar al comprar MEP con X
    mep_venta = by / ayd      # pesos por dólar al vender MEP con Y
    # Profundidad en USD de cada punta (VN × precio / 100; las de pesos, divididas por el MEP)
    prof = min(
        px[x]["ask_q"] * ax / 100 / mep_compra,
        px[x + "D"]["bid_q"] * bxd / 100,
        px[y + "D"]["ask_q"] * ayd / 100,
        px[y]["bid_q"] * by / 100 / mep_venta,
    )
    tam = min(prof, tam_max_usd)
    return {"neto_pct": neto_pct, "tam_usd": tam, "profundidad_usd": prof,
            "neto_usd": neto_pct * tam, "mep_compra": mep_compra, "mep_venta": mep_venta}


def cruces(px: dict, bonos: list[str], c: float, tick_ars: float, tick_usd: float,
           tam_max_usd: float, min_prof_usd: float) -> list[dict]:
    res = []
    for x in bonos:
        for y in bonos:
            if x == y:
                continue
            r = ciclo(px, x, y, c, tick_ars, tick_usd, tam_max_usd)
            if not r or r["neto_pct"] <= 0 or r["profundidad_usd"] < min_prof_usd:
                continue
            res.append({"clave": f"{x}->{y}", "grupo": "-".join(sorted((x, y))),
                        "direccion": f"{x}->{y}", "con_api": True, **r,
                        "detalle": {k: round(v, 4) for k, v in r.items()}})
    return res
