"""
Monitor de Arbitraje USDT/ARS (`monitor_usdt.py`) - SOLO MIDE, NO OPERA.
========================================================================
Cada 5 minutos lee de CriptoYa los precios de USDT en pesos de ~30 exchanges argentinos
(totalAsk / totalBid = precio final con comisiones de cada exchange) y registra:

  - AUTOMATIZABLE: la mejor diferencia entre exchanges CON API de trading
    (comprar barato en A por API, vender caro en B por API).
  - MANUAL: la mejor diferencia incluyendo P2P y apps sin API (solo como referencia).

Muestra el margen en dos escenarios:
  - con inventario: tenés USDT en B y pesos en A de antemano (sin transferir en cada vuelta)
  - con transferencia: se descuenta mover los USDT de A a B (COSTO_TRANSFER_USDT)

Salida:  usdt_precios.csv (cada lectura)  |  usdt_resumen.txt (cada hora y al final)
Uso:     python3 monitor_usdt.py           (24 h)
         python3 monitor_usdt.py --horas 48
"""
from __future__ import annotations

import argparse
import csv
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

ART = timezone(timedelta(hours=-3))
CARPETA = Path(__file__).resolve().parent
RUTA_CSV = CARPETA / "usdt_precios.csv"
RUTA_RESUMEN = CARPETA / "usdt_resumen.txt"

VOLUMEN_USDT = 100           # tamaño de la operación que se simula
COSTO_TRANSFER_USDT = 1.0    # mover USDT entre exchanges (red TRON/BSC aprox.)
INTERVALO_SEG = 300
URL = f"https://criptoya.com/api/usdt/ars/{VOLUMEN_USDT}"

# Exchanges con API pública de trading (órdenes por programa)
CON_API = {"binance", "bybit", "bitsoalpha", "ripioexchange", "cryptomktpro", "mexc"}
MAX_ANTIGUEDAD_SEG = 900     # ignorar cotizaciones viejas

COLUMNAS = ["Hora_ART", "Tipo", "Compra_en", "Precio_compra", "Vende_en", "Precio_venta",
            "Margen_inventario_pct", "Margen_con_transfer_pct"]


def log(msg: str) -> None:
    print(f"{datetime.now(ART):%Y-%m-%d %H:%M:%S} | {msg}", flush=True)


def leer_precios() -> Dict[str, Tuple[float, float]]:
    try:
        r = requests.get(URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        data = r.json() if r.status_code == 200 else {}
    except Exception:
        data = {}
    ahora = time.time()
    precios = {}
    for nombre, d in (data or {}).items():
        if not isinstance(d, dict):
            continue
        ask, bid, t = d.get("totalAsk") or 0, d.get("totalBid") or 0, d.get("time") or 0
        try:
            ask, bid, t = float(ask), float(bid), float(t)
        except (TypeError, ValueError):
            continue
        if ask <= 0 or bid <= 0 or (t and ahora - t > MAX_ANTIGUEDAD_SEG):
            continue
        precios[nombre] = (ask, bid)
    return precios


def mejor_cruce(precios: Dict[str, Tuple[float, float]], permitidos: Optional[set]) -> Optional[Dict[str, Any]]:
    cand = {k: v for k, v in precios.items() if permitidos is None or k in permitidos}
    mejor = None
    for a, (ask_a, _) in cand.items():
        for b, (_, bid_b) in cand.items():
            if a == b:
                continue
            m = bid_b / ask_a - 1
            if mejor is None or m > mejor["m"]:
                mejor = {"a": a, "ask": ask_a, "b": b, "bid": bid_b, "m": m}
    if not mejor:
        return None
    usdt_netos = VOLUMEN_USDT - COSTO_TRANSFER_USDT
    mejor["m_tr"] = (usdt_netos * mejor["bid"]) / (VOLUMEN_USDT * mejor["ask"]) - 1
    return mejor


def escribir_resumen(hist: Dict[str, List[Dict[str, Any]]], inicio: datetime) -> None:
    lineas = [f"MONITOR USDT/ARS ({inicio:%d/%m %H:%M} -> {datetime.now(ART):%d/%m %H:%M} hora ARG)",
              f"Volumen simulado: {VOLUMEN_USDT} USDT | costo de transferencia: {COSTO_TRANSFER_USDT} USDT", "=" * 70]
    for tipo, titulo in (("AUTOMATIZABLE", "Entre exchanges CON API (se puede automatizar)"),
                         ("MANUAL", "Incluyendo P2P y apps sin API (referencia)")):
        filas = hist.get(tipo, [])
        lineas += ["", titulo, "-" * len(titulo)]
        if not filas:
            lineas.append("  sin datos")
            continue
        inv = sorted(f["m"] * 100 for f in filas)
        tr = [f["m_tr"] * 100 for f in filas]
        n = len(filas)
        lineas += [
            f"  Lecturas: {n}",
            f"  Margen con inventario: mediana {inv[n // 2]:.2f}% | máximo {max(inv):.2f}%",
            f"  Lecturas con margen >= 0.5%: {sum(1 for x in inv if x >= 0.5)} | >= 1%: {sum(1 for x in inv if x >= 1)}",
            f"  Con transferencia en cada vuelta: máximo {max(tr):.2f}% | lecturas >= 0.5%: {sum(1 for x in tr if x >= 0.5)}",
        ]
        pares: Dict[str, int] = {}
        for f in filas:
            if f["m"] >= 0.003:
                k = f"{f['a']} -> {f['b']}"
                pares[k] = pares.get(k, 0) + 1
        top = sorted(pares.items(), key=lambda x: -x[1])[:5]
        if top:
            lineas.append("  Rutas más frecuentes con margen >= 0.3%: " + ", ".join(f"{k} ({v} veces)" for k, v in top))
        mejor = max(filas, key=lambda f: f["m"])
        lineas.append(f"  Mejor momento: {mejor['hora']} comprar en {mejor['a']} a {mejor['ask']:.2f}, "
                      f"vender en {mejor['b']} a {mejor['bid']:.2f} ({mejor['m']*100:.2f}%)")
    lineas += ["", "Ganancia estimada por vuelta de 100 USDT al margen mediano automatizable, con inventario:"]
    auto = hist.get("AUTOMATIZABLE", [])
    if auto:
        med = sorted(f["m"] for f in auto)[len(auto) // 2]
        lineas.append(f"  ~{VOLUMEN_USDT * med:.2f} USDT por vuelta")
    RUTA_RESUMEN.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horas", type=float, default=24.0)
    args = ap.parse_args()
    inicio = datetime.now(ART)
    fin = inicio + timedelta(hours=args.horas)
    log(f"Monitor USDT iniciado hasta {fin:%d/%m %H:%M} (hora ARG). No opera.")
    if not RUTA_CSV.exists():
        with open(RUTA_CSV, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(COLUMNAS)

    hist: Dict[str, List[Dict[str, Any]]] = {"AUTOMATIZABLE": [], "MANUAL": []}
    ultimo_resumen = 0.0
    while datetime.now(ART) < fin:
        t0 = time.time()
        precios = leer_precios()
        hora = f"{datetime.now(ART):%Y-%m-%d %H:%M}"
        partes = []
        for tipo, permitidos in (("AUTOMATIZABLE", CON_API), ("MANUAL", None)):
            c = mejor_cruce(precios, permitidos)
            if not c:
                continue
            c["hora"] = hora
            hist[tipo].append(c)
            with open(RUTA_CSV, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([hora, tipo, c["a"], round(c["ask"], 2), c["b"], round(c["bid"], 2),
                                        round(c["m"] * 100, 3), round(c["m_tr"] * 100, 3)])
            partes.append(f"{tipo}: {c['a']}->{c['b']} {c['m']*100:.2f}%")
        log(f"{len(precios)} exchanges | " + (" | ".join(partes) if partes else "sin datos"))
        if time.time() - ultimo_resumen > 3600:
            escribir_resumen(hist, inicio)
            ultimo_resumen = time.time()
        time.sleep(max(1.0, INTERVALO_SEG - (time.time() - t0)))
    escribir_resumen(hist, inicio)
    log("Terminado. Mirá usdt_resumen.txt")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
