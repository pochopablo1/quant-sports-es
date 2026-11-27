"""C14 · Dry-run USDT/ARS entre exchanges argentinos. SOLO LECTURA: usa APIs públicas,
no necesita cuentas ni claves y no manda órdenes.

Uso (desde la carpeta bots_v2):
    python -m c14_usdt_ars.dryrun            # corre las horas de config (72 por defecto)
    python -m c14_usdt_ars.dryrun --probar   # una sola consulta, muestra lo que lee y sale
"""
from __future__ import annotations

import argparse
import json
import time

from comun.registro import Registro
from comun.seguimiento import Seguidor, mejores
from comun.utiles import Parada, cargar_config, configurar_log, dormir_hasta, log, sesion_http
from c14_usdt_ars.logica import cruces

URL_CRIPTOYA = "https://criptoya.com/api/usdt/ars/{monto}"
URL_BINANCE = "https://api.binance.com/api/v3/depth?symbol=USDTARS&limit=50"
URL_BITSO_LIBROS = "https://api.bitso.com/v3/available_books/"
URL_BITSO = "https://api.bitso.com/v3/order_book/?book=usdt_ars&aggregate=true"


def leer_criptoya(s, montos) -> dict:
    """{exchange: {'por_monto': {monto: (ask, bid)}}}. CriptoYa: ask/bid sin comisiones."""
    out: dict = {}
    for m in montos:
        r = s.get(URL_CRIPTOYA.format(monto=m), timeout=10)
        r.raise_for_status()
        for ex, d in r.json().items():
            if not isinstance(d, dict):
                continue
            ask, bid = float(d.get("ask") or 0), float(d.get("bid") or 0)
            out.setdefault(ex, {"por_monto": {}})["por_monto"][float(m)] = (ask, bid)
    return out


def leer_binance(s) -> dict:
    r = s.get(URL_BINANCE, timeout=10)
    r.raise_for_status()
    j = r.json()
    return {"asks": [(float(p), float(q)) for p, q in j["asks"]],
            "bids": [(float(p), float(q)) for p, q in j["bids"]]}


def bitso_tiene_par(s) -> bool:
    try:
        r = s.get(URL_BITSO_LIBROS, timeout=10)
        return any(b.get("book") == "usdt_ars" for b in r.json().get("payload", []))
    except Exception:
        return False


def leer_bitso(s) -> dict:
    r = s.get(URL_BITSO, timeout=10)
    r.raise_for_status()
    p = r.json()["payload"]
    return {"asks": [(float(x["price"]), float(x["amount"])) for x in p["asks"]],
            "bids": [(float(x["price"]), float(x["amount"])) for x in p["bids"]]}


def leer_todo(s, cfg, usar_bitso: bool) -> tuple[dict, list[str]]:
    errores = []
    libros: dict = {}
    try:
        libros.update(leer_criptoya(s, cfg["tamanos_usdt"]))
    except Exception as e:
        errores.append(f"criptoya: {e}")
    # Los libros propios reemplazan a CriptoYa para ese exchange (precio real por profundidad).
    try:
        libros["binance"] = leer_binance(s)
    except Exception as e:
        errores.append(f"binance: {e}")
    if usar_bitso:
        try:
            libros["bitso"] = leer_bitso(s)
        except Exception as e:
            errores.append(f"bitso: {e}")
    solo = cfg.get("solo_exchanges")
    if solo:
        libros = {k: v for k, v in libros.items() if k in solo}
    return libros, errores


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probar", action="store_true")
    args = ap.parse_args()
    configurar_log("c14")
    cfg = cargar_config()["c14"]
    s = sesion_http()
    usar_bitso = bitso_tiene_par(s)
    log.info("Bitso con libro usdt_ars por API: %s", "sí" if usar_bitso else "no (uso CriptoYa)")

    def calcular(libros):
        return cruces(libros, cfg["exchanges"], [float(t) for t in cfg["tamanos_usdt"]],
                      cfg["slippage_extra"], cfg["retiro_usdt"], cfg["fraccion_rebalanceo"])

    if args.probar:
        libros, errores = leer_todo(s, cfg, usar_bitso)
        print("Exchanges leídos:", ", ".join(sorted(libros)) or "ninguno")
        print("Con API de trading según config:",
              ", ".join(k for k, v in cfg["exchanges"].items() if v.get("api_trading")))
        print("Faltan en config (se toman con taker 1% y sin API):",
              ", ".join(sorted(set(libros) - set(cfg["exchanges"]))) or "ninguno")
        if errores:
            print("Errores:", errores)
        ops = sorted(calcular(libros), key=lambda o: -o["neto_pct"])[:10]
        print(f"Cruces con neto > 0 ahora: {len(calcular(libros))}. Mejores:")
        for o in ops:
            print(f"  {o['clave']:<35} neto {o['neto_pct']*100:6.3f}%  US${o['neto_usd']:.3f}  API={o['con_api']}")
        return

    reg = Registro("c14")
    seg = Seguidor(reg, cfg["min_duracion_s"], min_neto_pct=cfg["min_neto_pct"])
    parada = Parada(cfg["horas"])
    log.info("C14 arrancó: %s hs, cada %s s. Ctrl+C para cortar.", cfg["horas"], cfg["intervalo_s"])
    while parada.seguir():
        t0 = time.time()
        libros, errores = leer_todo(s, cfg, usar_bitso)
        ops = calcular(libros)
        seg.observar(t0, mejores(ops))
        reg.latido(ok=len(libros) >= 2, detalle=json.dumps({"ex": len(libros), "ops": len(ops), "err": errores}))
        if errores:
            log.warning("Errores: %s", errores)
        dormir_hasta(t0 + cfg["intervalo_s"], parada)
    seg.cerrar_todo()
    log.info("C14 terminado. Reporte: python reporte.py c14")


if __name__ == "__main__":
    main()
