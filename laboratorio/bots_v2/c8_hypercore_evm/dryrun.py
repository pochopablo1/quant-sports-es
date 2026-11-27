"""C8 · Dry-run HyperCore spot vs AMMs de HyperEVM. SOLO LECTURA: API pública `info`
de Hyperliquid + eth_call al quoter del DEX. No necesita wallet ni fondos.

Uso (desde la carpeta bots_v2):
    python -m c8_hypercore_evm.dryrun --descubrir   # lista tokens con contrato en HyperEVM y pools
    python -m c8_hypercore_evm.dryrun --probar      # una pasada mostrando brechas
    python -m c8_hypercore_evm.dryrun               # corre las horas de config
"""
from __future__ import annotations

import argparse
import json
import time

from comun.evm import Cadena, es_direccion
from comun.registro import Registro
from comun.seguimiento import Seguidor, mejores
from comun.utiles import Parada, cargar_config, configurar_log, dormir_hasta, log, sesion_http
from c8_hypercore_evm.logica import brecha_core_a_evm, brecha_evm_a_core, excluir_top, neto, niveles_l2

URL_INFO = "https://api.hyperliquid.xyz/info"


def info(s, cuerpo: dict):
    r = s.post(URL_INFO, json=cuerpo, timeout=10)
    r.raise_for_status()
    return r.json()


def universo(s, cfg, cadena: Cadena) -> list[dict]:
    """Pares spot de Core cuyo token base tiene contrato en HyperEVM y pool en el DEX."""
    meta, ctxs = info(s, {"type": "spotMetaAndAssetCtxs"})
    tokens = {t["index"]: t for t in meta["tokens"]}
    pares = []
    vol = {}
    for par, ctx in zip(meta["universe"], ctxs):
        base, quote = (tokens[i] for i in par["tokens"])
        if quote["name"] not in ("USDC",):
            continue
        vol[base["name"]] = float(ctx.get("dayNtlVlm") or 0)
        evm = base.get("evmContract")
        if not evm or not es_direccion(evm.get("address")):
            continue
        coin = par["name"] if par["name"].startswith("@") or "/" in par["name"] else f"@{par['index']}"
        pares.append({"token": base["name"], "coin": coin, "evm": evm["address"],
                      "vol_usd": vol[base["name"]]})
    fuera = excluir_top(vol, cfg["excluir_top"]) | set(cfg.get("excluir", []))
    pares = [p for p in pares if p["token"] not in fuera and p["vol_usd"] >= cfg["vol_min_usd"]]
    pares = sorted(pares, key=lambda p: -p["vol_usd"])[:cfg["max_tokens"]]
    dex = cfg["dex"]
    elegidos = []
    for p in pares:
        for quote_evm in dex["tokens_quote"]:
            for fee in dex["fees"]:
                pool = cadena.pool_v3(dex["factory"], p["evm"], quote_evm["direccion"], fee) \
                    if es_direccion(dex.get("factory")) else None
                if pool:
                    elegidos.append(dict(p, pool=pool, fee=fee, quote=quote_evm))
    return elegidos


def evaluar(s, cfg, cadena: Cadena, par: dict, precio_hype: float, gas_usd: float) -> list[dict]:
    libro = info(s, {"type": "l2Book", "coin": par["coin"]})
    bids, asks = niveles_l2(libro)
    if not bids or not asks:
        return []
    q = par["quote"]
    usd_por_quote = precio_hype if q["tipo"] == "hype" else 1.0
    quoter, fee = cfg["dex"]["quoter"], par["fee"]

    def venta_evm(tokens):
        out = cadena.cotizar_v3(quoter, par["evm"], q["direccion"], tokens, fee)
        return None if out is None else out * usd_por_quote

    def compra_evm(usd):
        return cadena.cotizar_v3(quoter, q["direccion"], par["evm"], usd / usd_por_quote, fee)

    res = []
    for tam in cfg["tamanos_usd"]:
        for direccion, r in (("core->evm", brecha_core_a_evm(asks, tam, cfg["fee_core_taker"], venta_evm)),
                             ("evm->core", brecha_evm_a_core(bids, tam, cfg["fee_core_taker"], compra_evm))):
            if not r:
                continue
            n, pct = neto(r["bruto_usd"], tam, gas_usd, cfg["rebalanceo_usd"] * cfg["fraccion_rebalanceo"])
            if n > 0:
                res.append({"clave": f"{par['token']}:{direccion}:{fee}", "grupo": par["token"],
                            "direccion": direccion, "con_api": True, "tam_usd": tam,
                            "neto_usd": n, "neto_pct": pct,
                            "detalle": {k: round(v, 6) for k, v in r.items()}})
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probar", action="store_true")
    ap.add_argument("--descubrir", action="store_true")
    args = ap.parse_args()
    configurar_log("c8")
    cfg = cargar_config()["c8"]
    s = sesion_http()
    cadena = Cadena("hyperevm", cfg["rpc_hyperevm"])
    for k in ("factory", "quoter"):
        if not es_direccion(cfg["dex"].get(k)) or not cadena.tiene_codigo(cfg["dex"][k]):
            log.error("c8.dex.%s no es un contrato válido en HyperEVM: completalo en config.yaml "
                      "con la dirección de la documentación oficial del DEX.", k)
            return
    pares = universo(s, cfg, cadena)
    log.info("Universo: %d pares token×pool (sin los %d tokens más líquidos).", len(pares), cfg["excluir_top"])
    if args.descubrir:
        for p in pares:
            print(f"{p['token']:<10} coin={p['coin']:<8} vol24h=US${p['vol_usd']:>12,.0f} "
                  f"pool={p['pool']} fee={p['fee']} quote={p['quote']['nombre']}")
        return

    def pasada():
        mids = info(s, {"type": "allMids"})
        precio_hype = float(mids.get("HYPE", 0)) or 1.0
        gas_usd = cadena.gas_nativo(cfg["gas_unidades"]) * precio_hype
        ops = []
        for p in pares:
            try:
                ops += evaluar(s, cfg, cadena, p, precio_hype, gas_usd)
            except Exception as e:
                log.debug("%s: %s", p["token"], e)
        return ops, gas_usd

    if args.probar:
        ops, gas_usd = pasada()
        print(f"Gas por arbitraje ≈ US${gas_usd:.4f}. Brechas netas > 0: {len(ops)}")
        for o in sorted(ops, key=lambda o: -o["neto_pct"])[:15]:
            print(f"  {o['clave']:<40} {o['neto_pct']*100:6.3f}%  US${o['neto_usd']:.3f}")
        return

    reg = Registro("c8")
    seg = Seguidor(reg, cfg["min_duracion_s"], min_neto_pct=cfg["min_neto_pct"])
    parada = Parada(cfg["horas"])
    ultimo_universo = time.time()
    while parada.seguir():
        t0 = time.time()
        if t0 - ultimo_universo > 3600:  # refresca el universo cada hora
            try:
                pares = universo(s, cfg, cadena)
                ultimo_universo = t0
            except Exception as e:
                log.warning("No pude refrescar el universo: %s", e)
        try:
            ops, gas_usd = pasada()
            seg.observar(t0, mejores(ops))
            reg.latido(True, json.dumps({"pares": len(pares), "ops": len(ops), "gas_usd": round(gas_usd, 4)}))
        except Exception as e:
            reg.latido(False, str(e))
            log.warning("Pasada fallida: %s", e)
        dormir_hasta(t0 + cfg["intervalo_s"], parada)
    seg.cerrar_todo()
    log.info("C8 terminado. Reporte: python reporte.py c8")


if __name__ == "__main__":
    main()
