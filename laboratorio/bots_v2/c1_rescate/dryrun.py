"""C1 · Dry-run del arbitraje de rescate (modo taker atómico). SOLO LECTURA: eth_call a
quoters de DEX y a los contratos de rescate. No necesita wallet ni fondos, solo RPCs.

Rutas (config.yaml → c1.rutas), por tipo:
  - liquity_v2: stable de un fork de Liquity V2 (feUSD, USND, …). Lee la tasa de canje del
    CollateralRegistry (getRedemptionRateWithDecay).
  - erc4626: vault share que se rescata al instante con redeem (lee previewRedeem).
  - psm3: PSM de Spark (lee previewSwapExactIn).

Limitación honesta: no simula el `redeemCollateral` completo (eso necesita el contrato
propio). Aproxima con la tasa de canje leída on-chain y un costo de venta de la garantía.

Uso (desde la carpeta bots_v2):
    python -m c1_rescate.dryrun --verificar  # chequea que cada dirección tenga código y muestra símbolos
    python -m c1_rescate.dryrun --probar     # una pasada mostrando precios y netos
    python -m c1_rescate.dryrun              # corre las horas de config
"""
from __future__ import annotations

import argparse
import json
import time

from web3 import Web3

from comun.evm import Cadena, es_direccion
from comun.registro import Registro
from comun.seguimiento import Seguidor, mejores
from comun.utiles import Parada, cargar_config, configurar_log, dormir_hasta, log, sesion_http
from c1_rescate.logica import neto_directo, neto_liquity, precio_marginal

ABI_REGISTRY = [{"name": "getRedemptionRateWithDecay", "inputs": [], "outputs": [{"type": "uint256"}],
                 "stateMutability": "view", "type": "function"}]
ABI_4626 = [{"name": "previewRedeem", "inputs": [{"type": "uint256"}], "outputs": [{"type": "uint256"}],
             "stateMutability": "view", "type": "function"}]
ABI_PSM3 = [{"name": "previewSwapExactIn", "inputs": [{"type": "address"}, {"type": "address"}, {"type": "uint256"}],
             "outputs": [{"type": "uint256"}], "stateMutability": "view", "type": "function"}]

URL_HL = "https://api.hyperliquid.xyz/info"


def precios_nativos(s) -> dict:
    """Precio de ETH y HYPE (para pasar gas a USD), del endpoint público de Hyperliquid."""
    mids = s.post(URL_HL, json={"type": "allMids"}, timeout=10).json()
    return {"ETH": float(mids.get("ETH", 0)), "HYPE": float(mids.get("HYPE", 0))}


def cotizar(cadena: Cadena, ruta: dict, token_in: str, token_out: str, monto: float) -> float | None:
    dex = ruta["dex"]
    if dex["tipo"] == "v3":
        return cadena.cotizar_v3(dex["quoter"], token_in, token_out, monto, dex["fee"])
    if dex["tipo"] == "curve":
        i, j = (dex["i"], dex["j"]) if token_in.lower() == ruta["usd"].lower() else (dex["j"], dex["i"])
        return cadena.cotizar_curve(dex["pool"], i, j, monto, cadena.decimales(token_in), cadena.decimales(token_out))
    raise ValueError(f"tipo de DEX desconocido: {dex['tipo']}")


def evaluar_ruta(cadena: Cadena, ruta: dict, gas_usd: float, cfg) -> tuple[list[dict], dict]:
    """Devuelve (oportunidades con neto > 0, info para el registro de toques maker)."""
    usd, token = ruta["usd"], ruta["token"]
    ops, info = [], {}
    if ruta["tipo"] == "liquity_v2":
        tasa = cadena.c(ruta["collateral_registry"], ABI_REGISTRY).functions.getRedemptionRateWithDecay().call() / 1e18
        info["tasa_canje"] = tasa
        info["precio"] = precio_marginal(cotizar(cadena, ruta, usd, token, 1.0))
    for tam in cfg["tamanos_usd"]:
        recibido = cotizar(cadena, ruta, usd, token, tam)
        if not recibido:
            continue
        if ruta["tipo"] == "liquity_v2":
            n = neto_liquity(tam, recibido, info["tasa_canje"], ruta.get("costo_venta_garantia", 0.003), gas_usd)
        elif ruta["tipo"] == "erc4626":
            crudo = int(recibido * 10 ** cadena.decimales(token))
            assets = cadena.c(token, ABI_4626).functions.previewRedeem(crudo).call()
            n = neto_directo(tam, assets / 10 ** cadena.decimales(ruta["subyacente"]) * ruta.get("precio_subyacente_usd", 1.0), gas_usd)
        elif ruta["tipo"] == "psm3":
            crudo = int(recibido * 10 ** cadena.decimales(token))
            out = cadena.c(ruta["psm"], ABI_PSM3).functions.previewSwapExactIn(
                Web3.to_checksum_address(token), Web3.to_checksum_address(usd), crudo).call()
            n = neto_directo(tam, out / 10 ** cadena.decimales(usd), gas_usd)
        else:
            raise ValueError(f"tipo de ruta desconocido: {ruta['tipo']}")
        if n > 0:
            ops.append({"clave": ruta["nombre"], "grupo": ruta["nombre"], "direccion": "taker",
                        "con_api": True, "tam_usd": tam, "neto_usd": n, "neto_pct": n / tam,
                        "detalle": {"recibido": recibido, "gas_usd": gas_usd, **info}})
    return ops, info


def direcciones_de(ruta: dict) -> list[tuple[str, str]]:
    claves = ["usd", "token", "collateral_registry", "psm", "subyacente"]
    out = [(k, ruta[k]) for k in claves if k in ruta]
    out += [(f"dex.{k}", ruta["dex"][k]) for k in ("quoter", "pool") if k in ruta["dex"]]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probar", action="store_true")
    ap.add_argument("--verificar", action="store_true")
    args = ap.parse_args()
    configurar_log("c1")
    cfg = cargar_config()["c1"]
    s = sesion_http()
    cadenas = {n: Cadena(n, c["rpc"], c.get("op_stack", False)) for n, c in cfg["cadenas"].items()}

    rutas = []
    for r in cfg["rutas"]:
        if not r.get("activa", True):
            continue
        cad = cadenas[r["cadena"]]
        malas = [k for k, d in direcciones_de(r) if not es_direccion(d)]
        if malas:
            log.warning("Ruta %s desactivada: faltan direcciones %s (completalas desde la doc oficial).", r["nombre"], malas)
            continue
        if args.verificar:
            for k, d in direcciones_de(r):
                cod = cad.tiene_codigo(d)
                print(f"{r['nombre']:<22} {k:<20} {d}  código={'sí' if cod else 'NO'}  símbolo={cad.simbolo(d)}")
        rutas.append(r)
    if args.verificar:
        return
    log.info("Rutas activas: %s", ", ".join(r["nombre"] for r in rutas) or "ninguna")
    if not rutas:
        return

    def pasada():
        px = precios_nativos(s)
        ops, toques = [], []
        for r in rutas:
            cad = cadenas[r["cadena"]]
            nativo = cfg["cadenas"][r["cadena"]]["nativo"]
            try:
                gas_usd = cad.gas_nativo(r.get("gas_unidades", 600_000)) * px[nativo] \
                    * cfg["cadenas"][r["cadena"]].get("multiplicador_gas", 1.0)
                o, info = evaluar_ruta(cad, r, gas_usd, cfg)
                ops += o
                p = info.get("precio")
                if p is not None and p <= cfg["maker_rango_max"]:
                    toques.append({"ruta": r["nombre"], "precio": p, "tasa_canje": info.get("tasa_canje")})
            except Exception as e:
                log.debug("%s: %s", r["nombre"], e)
        return ops, toques

    if args.probar:
        ops, toques = pasada()
        print(f"Oportunidades netas > 0: {len(ops)}")
        for o in ops:
            print(f"  {o['clave']:<28} neto US${o['neto_usd']:.3f} ({o['neto_pct']*100:.3f}%)  {o['detalle']}")
        print("Toques del rango maker:", toques or "ninguno")
        return

    reg = Registro("c1")
    seg = Seguidor(reg, cfg["min_duracion_s"], min_neto_usd=cfg["min_neto_usd"])
    parada = Parada(cfg["horas"])
    while parada.seguir():
        t0 = time.time()
        try:
            ops, toques = pasada()
            seg.observar(t0, mejores(ops))
            for t in toques:
                reg.evento("maker_toque", t)
            reg.latido(True, json.dumps({"ops": len(ops), "toques": len(toques)}))
        except Exception as e:
            reg.latido(False, str(e))
            log.warning("Pasada fallida: %s", e)
        dormir_hasta(t0 + cfg["intervalo_s"], parada)
    seg.cerrar_todo()
    log.info("C1 terminado. Reporte: python reporte.py c1")


if __name__ == "__main__":
    main()
