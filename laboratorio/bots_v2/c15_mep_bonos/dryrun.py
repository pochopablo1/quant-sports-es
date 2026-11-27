"""C15 · Dry-run de "dólar MEP" entre bonos soberanos. SOLO LECTURA: lee puntas por la
API de InvertirOnline; no manda órdenes. Necesita usuario y clave de IOL con la API
habilitada (en variables de entorno IOL_USUARIO e IOL_CLAVE, no en archivos).

Uso (desde la carpeta bots_v2):
    python -m c15_mep_bonos.dryrun --probar   # muestra la respuesta cruda de AL30 y AL30D
    python -m c15_mep_bonos.dryrun            # corre en horario de mercado (11 a 17 AR)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from comun.registro import Registro
from comun.seguimiento import Seguidor, mejores
from comun.utiles import Parada, cargar_config, configurar_log, dormir_hasta, log, sesion_http
from c15_mep_bonos.iol import IOL
from c15_mep_bonos.logica import costo_ciclo, costo_pata, cruces

AR = timezone(timedelta(hours=-3))


def en_horario(cfg) -> bool:
    ahora = datetime.now(AR)
    if ahora.weekday() >= 5:
        return False
    return cfg["hora_desde"] <= ahora.hour + ahora.minute / 60 < cfg["hora_hasta"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probar", action="store_true")
    args = ap.parse_args()
    configurar_log("c15")
    cfg = cargar_config()["c15"]

    c = costo_pata(cfg["comision_por_pata"], cfg["derechos_mercado"], cfg["iva"])
    cc = costo_ciclo(c)
    log.info("Costo por pata %.4f%% → ciclo de 4 patas %.3f%% (compuerta: ≤ %.2f%%)",
             c * 100, cc * 100, cfg["compuerta_costo_ciclo"] * 100)
    if cc > cfg["compuerta_costo_ciclo"]:
        log.error("MUERE EN LA COMPUERTA: el ciclo cuesta más de lo permitido. "
                  "Revisá el tarifario de tu broker en config.yaml (c15.comision_por_pata).")
        if not args.probar:
            sys.exit(1)

    usuario, clave = os.environ.get("IOL_USUARIO"), os.environ.get("IOL_CLAVE")
    if not usuario or not clave:
        sys.exit("Faltan IOL_USUARIO e IOL_CLAVE como variables de entorno (ver README).")
    iol = IOL(sesion_http(), usuario, clave, cfg["mercado"], cfg["plazo"])
    simbolos = [b for b in cfg["bonos"]] + [b + "D" for b in cfg["bonos"]]

    if args.probar:
        for sim in (cfg["bonos"][0], cfg["bonos"][0] + "D"):
            crudo = iol.cotizacion_cruda(sim)
            print(f"--- {sim} (respuesta cruda) ---")
            print(json.dumps(crudo, indent=2, ensure_ascii=False)[:3000])
            print("Puntas interpretadas:", iol.puntas(sim))
        return

    reg = Registro("c15")
    seg = Seguidor(reg, cfg["min_duracion_s"], min_neto_pct=cfg["min_neto_pct"])
    parada = Parada(cfg["horas"])
    log.info("C15 arrancó: %s hs corridas (solo cuenta horario de mercado).", cfg["horas"])
    while parada.seguir():
        t0 = time.time()
        if not en_horario(cfg):
            seg.cerrar_todo()
            dormir_hasta(t0 + 60, parada)
            continue
        px, errores = {}, []
        for sim in simbolos:
            try:
                p = iol.puntas(sim)
                if p:
                    px[sim] = p
            except Exception as e:
                errores.append(f"{sim}: {e}")
        ops = cruces(px, cfg["bonos"], c, cfg["tick_ars"], cfg["tick_usd"],
                     cfg["tam_max_usd"], cfg["min_profundidad_usd"])
        seg.observar(t0, mejores(ops))
        reg.latido(ok=len(px) >= 4, detalle=json.dumps({"puntas": len(px), "ops": len(ops), "err": errores[:3]}))
        if errores:
            log.warning("Errores: %s", errores[:3])
        dormir_hasta(t0 + cfg["intervalo_s"], parada)
    seg.cerrar_todo()
    log.info("C15 terminado. Reporte: python reporte.py c15")


if __name__ == "__main__":
    main()
