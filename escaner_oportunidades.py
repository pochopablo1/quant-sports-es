"""
Escáner de Oportunidades Olvidadas en Polymarket (`escaner_oportunidades.py`) - SOLO MIDE, NO COMPRA.
===================================================================================================
Busca "migajas" en mercados chicos que los bots grandes ignoran. Dos tipos:

 A) VENCIDOS CON MARGEN: mercados cuya fecha límite YA PASÓ, siguen abiertos y el favorito
    todavía se vende entre 0.80 y 0.97. Si leyendo la regla el resultado ya está decidido,
    comprar el favorito deja 3-25%. ATENCIÓN: fecha vencida NO siempre = decidido
    (ej. "próximo primer ministro" depende de cuándo se forme el gobierno). Hay que LEER LA REGLA.

 B) SUMAS QUE NO CIERRAN: eventos de varios resultados donde gana exactamente uno (negRisk).
    - Si la suma de los precios de compra de todos los SÍ es < 0.97 -> comprar todos los SÍ paga $1 seguro.
    - Si la suma de los mejores bids de los SÍ es > 1.03 -> comprar todos los NO paga más de lo que cuesta.

Cada hora reescribe `escaner_reporte.txt` (lo más reciente) y agrega a `escaner_historial.csv`.
Solo depende de `requests`. No usa claves ni wallets.

Uso:  python3 escaner_oportunidades.py            (hasta mañana 12:00 hora ARG)
      python3 escaner_oportunidades.py --una-vez
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

ART = timezone(timedelta(hours=-3))
CARPETA = Path(__file__).resolve().parent
RUTA_REPORTE = CARPETA / "escaner_reporte.txt"
RUTA_HISTORIAL = CARPETA / "escaner_historial.csv"

URL_MARKETS = "https://gamma-api.polymarket.com/markets"
URL_EVENTS = "https://gamma-api.polymarket.com/events"
URL_BOOK = "https://clob.polymarket.com/book"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

PRECIO_MIN_A, PRECIO_MAX_A = 0.80, 0.97   # rango del favorito en mercados vencidos
MARGEN_MIN_B = 0.03                       # 3% mínimo en sumas que no cierran (cubre fees)
LIQUIDEZ_MIN = 10.0
INTERVALO_SEG = 3600

COLUMNAS = ["Hora_ART", "Tipo", "Evento", "Detalle", "Precio_o_suma", "Margen_pct",
            "Dias_vencido", "Liquidez_USD", "Vol_24h_USD", "Link"]


def log(msg: str) -> None:
    print(f"{datetime.now(ART):%Y-%m-%d %H:%M:%S} | {msg}", flush=True)


def get_json(url: str, params: Optional[dict] = None, timeout: int = 30) -> Any:
    for intento in range(2):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(2)
    return None


def lista(v: Any) -> List[Any]:
    if isinstance(v, list):
        return v
    try:
        x = json.loads(v)
        return x if isinstance(x, list) else []
    except Exception:
        return []


def num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fecha(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def link_de(m: Dict[str, Any]) -> str:
    evs = m.get("events") or []
    slug = (evs[0].get("slug") if evs and isinstance(evs[0], dict) else None) or m.get("slug") or ""
    return f"https://polymarket.com/event/{slug}"


def tamano_en_mejor_ask(token: str) -> float:
    """USD disponibles al mejor precio de venta (para saber si se puede ejecutar)."""
    libro = get_json(URL_BOOK, {"token_id": token}, timeout=8)
    if not isinstance(libro, dict):
        return 0.0
    asks = sorted((float(a["price"]), float(a["size"])) for a in libro.get("asks") or [] if float(a.get("price", 0)) > 0)
    return round(asks[0][0] * asks[0][1], 2) if asks else 0.0


# ── A) Mercados vencidos con margen ─────────────────────────────────────────
def escanear_vencidos() -> List[Dict[str, Any]]:
    ahora = datetime.now(timezone.utc)
    mercados, offset = [], 0
    while offset < 5000:
        lote = get_json(URL_MARKETS, {
            "closed": "false",
            "end_date_min": (ahora - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_date_max": (ahora - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "liquidity_num_min": str(LIQUIDEZ_MIN), "limit": "500", "offset": str(offset),
        })
        if not isinstance(lote, list) or not lote:
            break
        mercados.extend(lote)
        if len(lote) < 500:
            break
        offset += 500

    mejores_por_evento: Dict[str, Dict[str, Any]] = {}
    for m in mercados:
        if m.get("closed") or m.get("acceptingOrders") is False:
            continue
        if lista(m.get("umaResolutionStatuses")):
            continue  # ya está en proceso de resolución/disputa
        outs = [str(o) for o in lista(m.get("outcomes"))]
        ask, bid = num(m.get("bestAsk")), num(m.get("bestBid"))
        if len(outs) != 2 or ask is None or bid is None:
            continue
        # precio para comprar cada lado: lado 1 = ask; lado 2 = 1 - bid del lado 1
        opciones = [(outs[0], ask), (outs[1], round(1 - bid, 4))]
        lado, precio = max(opciones, key=lambda x: x[1])  # el favorito (el más caro)
        if not (PRECIO_MIN_A <= precio <= PRECIO_MAX_A):
            continue
        fin = fecha(m.get("endDate"))
        dias = round((ahora - fin).total_seconds() / 86400, 1) if fin else None
        cand = {
            "Tipo": "A_VENCIDO", "Evento": str(m.get("question") or ""),
            "Detalle": f"Favorito: {lado} | Regla: {str(m.get('description') or '')[:400].replace(chr(10), ' ')}",
            "Precio_o_suma": precio, "Margen_pct": round((1 / precio - 1) * 100, 1),
            "Dias_vencido": dias, "Liquidez_USD": round(num(m.get("liquidityNum")) or 0, 0),
            "Vol_24h_USD": round(num(m.get("volume24hr")) or 0, 0), "Link": link_de(m),
        }
        clave = link_de(m)
        # en eventos con muchos sub-mercados, quedarse con el de mayor margen
        if clave not in mejores_por_evento or cand["Margen_pct"] > mejores_por_evento[clave]["Margen_pct"]:
            mejores_por_evento[clave] = cand
    return sorted(mejores_por_evento.values(), key=lambda c: -c["Margen_pct"])


# ── B) Sumas que no cierran en eventos de varios resultados ──────────────────
def escanear_sumas(paginas: int = 12) -> List[Dict[str, Any]]:
    candidatos = []
    for pag in range(paginas):
        lote = get_json(URL_EVENTS, {"closed": "false", "order": "volume24hr", "ascending": "false",
                                     "limit": "50", "offset": str(pag * 50)})
        if not isinstance(lote, list) or not lote:
            break
        for ev in lote:
            if not (ev.get("negRisk") or ev.get("enableNegRisk")) or ev.get("negRiskAugmented"):
                continue  # solo conjuntos COMPLETOS de resultados (gana exactamente uno)
            mk = [m for m in ev.get("markets") or [] if not m.get("closed")]
            if len(mk) < 3 or len(mk) != len([m for m in ev.get("markets") or []]):
                continue
            if any(m.get("acceptingOrders") is False for m in mk):
                continue
            asks = [num(m.get("bestAsk")) for m in mk]
            bids = [num(m.get("bestBid")) for m in mk]
            link = f"https://polymarket.com/event/{ev.get('slug', '')}"
            titulo = str(ev.get("title") or "")
            n = len(mk)
            if all(a is not None and a > 0 for a in asks):
                suma = sum(asks)
                if suma <= 1 - MARGEN_MIN_B:
                    tokens = [lista(m.get("clobTokenIds"))[0] for m in mk if lista(m.get("clobTokenIds"))]
                    ejecutable = min((tamano_en_mejor_ask(t) for t in tokens), default=0.0)
                    candidatos.append({
                        "Tipo": "B_TODOS_SI", "Evento": titulo,
                        "Detalle": f"Comprar el SÍ de los {n} resultados cuesta {suma:.3f} y paga 1.00 | "
                                   f"USD ejecutables por pata al mejor precio (mín): {ejecutable}",
                        "Precio_o_suma": round(suma, 3), "Margen_pct": round((1 / suma - 1) * 100, 1),
                        "Dias_vencido": "", "Liquidez_USD": round(num(ev.get("liquidity")) or 0, 0),
                        "Vol_24h_USD": round(num(ev.get("volume24hr")) or 0, 0), "Link": link,
                    })
            if all(b is not None and b > 0 for b in bids):
                suma_bids = sum(bids)
                costo_nos = n - suma_bids          # comprar todos los NO
                pago_nos = n - 1
                if costo_nos <= pago_nos * (1 - MARGEN_MIN_B):
                    candidatos.append({
                        "Tipo": "B_TODOS_NO", "Evento": titulo,
                        "Detalle": f"Comprar el NO de los {n} resultados cuesta {costo_nos:.3f} y paga {pago_nos}",
                        "Precio_o_suma": round(costo_nos, 3), "Margen_pct": round((pago_nos / costo_nos - 1) * 100, 1),
                        "Dias_vencido": "", "Liquidez_USD": round(num(ev.get("liquidity")) or 0, 0),
                        "Vol_24h_USD": round(num(ev.get("volume24hr")) or 0, 0), "Link": link,
                    })
        if len(lote) < 50:
            break
    return sorted(candidatos, key=lambda c: -c["Margen_pct"])


# ── Reporte ──────────────────────────────────────────────────────────────────
def escribir(vencidos: List[Dict[str, Any]], sumas: List[Dict[str, Any]]) -> None:
    hora = f"{datetime.now(ART):%Y-%m-%d %H:%M}"
    lineas = [f"ESCÁNER DE OPORTUNIDADES - {hora} (hora ARG)", "=" * 70, "",
              f"A) VENCIDOS CON MARGEN: {len(vencidos)} candidatos (LEER LA REGLA antes de comprar)", ""]
    for c in vencidos[:40]:
        lineas += [f"* {c['Margen_pct']}% | {c['Evento']}",
                   f"  precio {c['Precio_o_suma']} | vencido hace {c['Dias_vencido']} días | "
                   f"liquidez ${c['Liquidez_USD']} | vol 24h ${c['Vol_24h_USD']}",
                   f"  {c['Detalle'][:300]}", f"  {c['Link']}", ""]
    lineas += ["", f"B) SUMAS QUE NO CIERRAN: {len(sumas)} candidatos", ""]
    for c in sumas[:20]:
        lineas += [f"* {c['Margen_pct']}% | {c['Tipo']} | {c['Evento']}", f"  {c['Detalle']}",
                   f"  liquidez ${c['Liquidez_USD']} | vol 24h ${c['Vol_24h_USD']}", f"  {c['Link']}", ""]
    RUTA_REPORTE.write_text("\n".join(lineas) + "\n", encoding="utf-8")

    nuevo = not RUTA_HISTORIAL.exists()
    with open(RUTA_HISTORIAL, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS)
        if nuevo:
            w.writeheader()
        for c in vencidos + sumas:
            w.writerow({"Hora_ART": hora, **{k: c.get(k, "") for k in COLUMNAS if k != "Hora_ART"}})


def escanear() -> None:
    log("Escaneando mercados vencidos...")
    vencidos = escanear_vencidos()
    log(f"  {len(vencidos)} vencidos con margen")
    log("Escaneando sumas de eventos multi-resultado...")
    sumas = escanear_sumas()
    log(f"  {len(sumas)} sumas que no cierran")
    escribir(vencidos, sumas)
    for c in (vencidos[:3] + sumas[:3]):
        log(f"  TOP: {c['Margen_pct']}% | {c['Tipo']} | {c['Evento'][:70]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    manana = (datetime.now(ART) + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    ap.add_argument("--hasta", default=manana.strftime("%Y-%m-%d %H:%M"))
    ap.add_argument("--una-vez", action="store_true")
    args = ap.parse_args()
    if args.una_vez:
        escanear()
        return
    fin = datetime.strptime(args.hasta, "%Y-%m-%d %H:%M").replace(tzinfo=ART)
    log(f"Escáner iniciado. Escanea cada hora hasta {fin:%d/%m %H:%M}. No compra nada.")
    while datetime.now(ART) < fin:
        try:
            escanear()
        except Exception as exc:
            log(f"Error en el escaneo: {exc}")
        time.sleep(INTERVALO_SEG)
    log("Escáner terminado. Mirá escaner_reporte.txt")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
