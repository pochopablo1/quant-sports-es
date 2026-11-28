"""
Mega Monitor de Desfasajes (`monitor_mega.py`) - SOLO MIDE, NO OPERA.
=====================================================================
Cada 5 minutos registra cinco familias de oportunidades (todas con comisiones de CriptoYa incluidas):

 1. TRIANGULAR (mismo exchange, sin transferir): ARS -> USDT -> BTC/ETH -> ARS y al revés,
    usando el precio mundial de BTC/ETH en dólares (Binance/Coinbase) + 0.1% de comisión.
 2. ESTABLES (mismo exchange): comprar USDC y vender USDT (o al revés); USDC<->USDT ~1:1.
 3. ESTABLES ENTRE EXCHANGES: comprar USDT/USDC donde está barato, vender donde está caro.
 4. BRECHAS: dólar cripto vs MEP, CCL, oficial y blue (y el "rulo" MEP -> USDT).
 5. FUNDING (Hyperliquid): tasa que cobran los apalancados; cobrable con spot + corto (delta neutral).

Salida: mega_datos.csv (cada lectura) y mega_resumen.txt (cada hora y al final).
Uso:    python3 monitor_mega.py                        (hasta el jueves 26/11 14:00)
        python3 monitor_mega.py --hasta "2026-11-27 12:00"
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
RUTA_CSV = CARPETA / "mega_datos.csv"
RUTA_RESUMEN = CARPETA / "mega_resumen.txt"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
INTERVALO_SEG = 300
FEE_CRIPTO_USDT = 0.001     # comisión del tramo BTC/USDT o USDC/USDT dentro del exchange
CON_API = {"binance", "bybit", "bitsoalpha", "ripioexchange", "cryptomktpro", "mexc"}
COLUMNAS = ["Hora_ART", "Familia", "Detalle", "Margen_pct", "Automatizable"]


def log(msg: str) -> None:
    print(f"{datetime.now(ART):%Y-%m-%d %H:%M:%S} | {msg}", flush=True)


def get_json(url: str, metodo: str = "GET", body: Optional[dict] = None, timeout: int = 20) -> Any:
    try:
        if metodo == "POST":
            r = requests.post(url, json=body, headers=HEADERS, timeout=timeout)
        else:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def libro_criptoya(moneda: str, volumen: str) -> Dict[str, Tuple[float, float]]:
    data = get_json(f"https://criptoya.com/api/{moneda}/ars/{volumen}") or {}
    ahora, out = time.time(), {}
    for k, d in data.items() if isinstance(data, dict) else []:
        try:
            a, b, t = float(d.get("totalAsk") or 0), float(d.get("totalBid") or 0), float(d.get("time") or 0)
        except (TypeError, ValueError, AttributeError):
            continue
        if a > 0 and b > 0 and not (t and ahora - t > 900):
            out[k] = (a, b)
    return out


def precio_mundial(simbolo: str) -> Optional[Tuple[float, float]]:
    """(ask, bid) en USDT. Binance (espejo de datos) y si falla Coinbase."""
    d = get_json(f"https://data-api.binance.vision/api/v3/ticker/bookTicker?symbol={simbolo}USDT")
    if isinstance(d, dict) and d.get("askPrice"):
        return float(d["askPrice"]), float(d["bidPrice"])
    d = get_json(f"https://api.exchange.coinbase.com/products/{simbolo}-USD/ticker")
    if isinstance(d, dict) and d.get("ask"):
        return float(d["ask"]), float(d["bid"])
    return None


# ── 1. Triangular ────────────────────────────────────────────────────────────
def triangular(usdt: Dict, cripto: Dict, mundial: Tuple[float, float], sim: str) -> List[Dict[str, Any]]:
    out = []
    ask_m, bid_m = mundial
    f = 1 - FEE_CRIPTO_USDT
    for ex in set(usdt) & set(cripto):
        ua, ub = usdt[ex]
        ca, cb = cripto[ex]
        # A: pesos -> USDT -> cripto (mundial) -> pesos
        a = cb * f / (ua * ask_m) - 1
        # B: pesos -> cripto -> USDT (mundial) -> pesos
        b = bid_m * f * ub / ca - 1
        for m, ruta in ((a, f"ARS->USDT->{sim}->ARS"), (b, f"ARS->{sim}->USDT->ARS")):
            out.append({"Familia": "TRIANGULAR", "Detalle": f"{ex}: {ruta}", "m": m, "auto": ex in CON_API})
    return out


# ── 2 y 3. Estables ──────────────────────────────────────────────────────────
def estables(usdt: Dict, usdc: Dict) -> List[Dict[str, Any]]:
    out = []
    f = 1 - FEE_CRIPTO_USDT
    for ex in set(usdt) & set(usdc):
        (ta, tb), (ca, cb) = usdt[ex], usdc[ex]
        out.append({"Familia": "ESTABLES_MISMO", "Detalle": f"{ex}: compra USDT vende USDC", "m": cb * f / ta - 1, "auto": ex in CON_API})
        out.append({"Familia": "ESTABLES_MISMO", "Detalle": f"{ex}: compra USDC vende USDT", "m": tb * f / ca - 1, "auto": ex in CON_API})
    for moneda, libro in (("USDT", usdt), ("USDC", usdc)):
        for solo_api in (True, False):
            cand = {k: v for k, v in libro.items() if k in CON_API or not solo_api}
            mejor = None
            for a, (aa, _) in cand.items():
                for b, (_, bb) in cand.items():
                    if a != b and (mejor is None or bb / aa - 1 > mejor[2]):
                        mejor = (a, b, bb / aa - 1)
            if mejor:
                out.append({"Familia": "ESTABLES_ENTRE" + ("_API" if solo_api else "_TODOS"),
                            "Detalle": f"{moneda}: compra {mejor[0]} vende {mejor[1]}", "m": mejor[2], "auto": solo_api})
    return out


# ── 4. Brechas ───────────────────────────────────────────────────────────────
def brechas(usdt: Dict) -> List[Dict[str, Any]]:
    d = get_json("https://criptoya.com/api/dolar")
    if not isinstance(d, dict):
        return []
    out = []
    try:
        mep = float(d["mep"]["al30"]["ci"]["price"])
        ccl = float(d["ccl"]["al30"]["ci"]["price"])
        oficial = float(d["oficial"].get("ask") or d["oficial"]["price"])
        blue = float(d["blue"]["ask"])
    except (KeyError, TypeError, ValueError):
        return out
    mejor_bid_api = max((v[1] for k, v in usdt.items() if k in CON_API), default=0)
    mejor_ask_api = min((v[0] for k, v in usdt.items() if k in CON_API), default=0)
    if mejor_bid_api:
        out.append({"Familia": "BRECHA", "Detalle": "rulo: compra MEP (AL30) -> vende USDT", "m": mejor_bid_api / mep - 1, "auto": False})
        out.append({"Familia": "BRECHA", "Detalle": "USDT vs CCL", "m": mejor_bid_api / ccl - 1, "auto": False})
        out.append({"Familia": "BRECHA", "Detalle": "USDT vs oficial", "m": mejor_bid_api / oficial - 1, "auto": False})
        out.append({"Familia": "BRECHA", "Detalle": "USDT vs blue", "m": mejor_bid_api / blue - 1, "auto": False})
    if mejor_ask_api:
        out.append({"Familia": "BRECHA", "Detalle": "rulo inverso: compra USDT -> vende MEP", "m": mep / mejor_ask_api - 1, "auto": False})
    return out


# ── 5. Funding ───────────────────────────────────────────────────────────────
def funding() -> List[Dict[str, Any]]:
    d = get_json("https://api.hyperliquid.xyz/info", "POST", {"type": "metaAndAssetCtxs"})
    if not (isinstance(d, list) and len(d) == 2):
        return []
    univ, ctxs = d[0].get("universe", []), d[1]
    filas = []
    for u, c in zip(univ, ctxs):
        try:
            fr = float(c.get("funding") or 0)          # por hora
            vol = float(c.get("dayNtlVlm") or 0)
        except (TypeError, ValueError):
            continue
        if vol < 5_000_000 or u.get("isDelisted"):
            continue
        filas.append((u.get("name"), fr))
    filas.sort(key=lambda x: -x[1])
    return [{"Familia": "FUNDING", "Detalle": f"{n}: {fr*100:.4f}%/h (~{fr*24*365*100:.0f}% anual)",
             "m": fr * 24, "auto": True} for n, fr in filas[:3]]


# ── Resumen ──────────────────────────────────────────────────────────────────
TITULOS = {
    "TRIANGULAR": "1. Triangular dentro de un exchange (sin transferir)",
    "ESTABLES_MISMO": "2. USDT <-> USDC dentro de un exchange",
    "ESTABLES_ENTRE_API": "3a. Estables entre exchanges CON API",
    "ESTABLES_ENTRE_TODOS": "3b. Estables entre todos (incluye P2P/apps, referencia)",
    "BRECHA": "4. Brechas cripto vs MEP/CCL/oficial/blue",
    "FUNDING": "5. Funding Hyperliquid (margen = por día)",
}


def escribir_resumen(hist: List[Dict[str, Any]], inicio: datetime, lecturas: int) -> None:
    lineas = [f"MEGA MONITOR ({inicio:%d/%m %H:%M} -> {datetime.now(ART):%d/%m %H:%M} hora ARG) | lecturas: {lecturas}", "=" * 72]
    for fam, titulo in TITULOS.items():
        filas = [h for h in hist if h["Familia"] == fam]
        lineas += ["", titulo, "-" * len(titulo)]
        if not filas:
            lineas.append("  sin datos")
            continue
        por_det: Dict[str, List[float]] = {}
        for h in filas:
            clave = h["Detalle"].split(":")[0] if fam == "FUNDING" else h["Detalle"]
            if h["auto"] and fam not in ("FUNDING", "ESTABLES_ENTRE_API"):
                clave += " [API]"
            por_det.setdefault(clave, []).append(h["m"] * 100)
        ranking = sorted(por_det.items(), key=lambda kv: -max(kv[1]))[:6]
        for det, ms in ranking:
            s = sorted(ms)
            pos = sum(1 for x in ms if x >= 0.5)
            lineas.append(f"  {det}: máx {s[-1]:.2f}% | mediana {s[len(s)//2]:.2f}% | veces >= 0.5%: {pos}/{len(ms)}")
    RUTA_RESUMEN.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hasta", default="2026-11-26 14:00")
    args = ap.parse_args()
    inicio = datetime.now(ART)
    fin = datetime.strptime(args.hasta, "%Y-%m-%d %H:%M").replace(tzinfo=ART)
    log(f"Mega monitor iniciado hasta {fin:%d/%m %H:%M}. No opera.")
    if not RUTA_CSV.exists():
        with open(RUTA_CSV, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(COLUMNAS)
    hist: List[Dict[str, Any]] = []
    lecturas, ultimo_resumen = 0, 0.0
    while datetime.now(ART) < fin:
        t0 = time.time()
        try:
            usdt = libro_criptoya("usdt", "100")
            usdc = libro_criptoya("usdc", "100")
            filas: List[Dict[str, Any]] = []
            for sim, vol in (("BTC", "0.001"), ("ETH", "0.03")):
                m = precio_mundial(sim)
                c = libro_criptoya(sim.lower(), vol)
                if m and c and usdt:
                    filas += triangular(usdt, c, m, sim)
            if usdt and usdc:
                filas += estables(usdt, usdc)
            if usdt:
                filas += brechas(usdt)
            filas += funding()
            lecturas += 1
            hora = f"{datetime.now(ART):%Y-%m-%d %H:%M}"
            with open(RUTA_CSV, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                for h in filas:
                    w.writerow([hora, h["Familia"], h["Detalle"], round(h["m"] * 100, 3), "SI" if h["auto"] else "NO"])
            hist += filas
            top = sorted((h for h in filas if h["Familia"] != "FUNDING" and h["Familia"] != "BRECHA"),
                         key=lambda h: -h["m"])[:2]
            log(f"Lectura {lecturas}: {len(filas)} datos | mejores: " +
                " | ".join(f"{h['Detalle']} {h['m']*100:.2f}%" for h in top))
        except Exception as exc:
            log(f"Error: {exc}")
        if time.time() - ultimo_resumen > 3600:
            escribir_resumen(hist, inicio, lecturas)
            ultimo_resumen = time.time()
        time.sleep(max(1.0, INTERVALO_SEG - (time.time() - t0)))
    escribir_resumen(hist, inicio, lecturas)
    log("Terminado. Mirá mega_resumen.txt")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
