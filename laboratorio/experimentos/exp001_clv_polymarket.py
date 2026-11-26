"""
Experimento 001 – Deriva de precio pre-partido en Polymarket (moneylines de EE. UU.)

Hipótesis: el precio del favorito se mueve de forma sistemática entre ~24 h antes del
partido y el inicio (sesgo favorito/longshot que el mercado corrige). Si es así, comprar
temprano al lado que sube y vender al inicio daría ganancia neta.

Medición (solo papel): para mercados cuyo partido empezó en las últimas 72 h, se baja el
historial de precios del CLOB y se compara el precio a T-24h (o el más viejo disponible
>= T-6h) contra el precio a T-10min. Costo asumido: 1 centavo por lado (spread).
Se prueban dos estrategias: comprar favorito y comprar underdog.

Los casos se acumulan en laboratorio/datos/exp001_casos.csv entre corridas.
"""
from __future__ import annotations

import csv
import json
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

EXPERIMENTO = "exp001_clv_polymarket"
VERSION = "v1"
FECHA_CONGELADO = datetime(2026, 11, 26, 4, 0, tzinfo=timezone.utc)
UMBRAL = 0.01          # ganancia media neta mínima por dólar invertido (1%)
N_MINIMO = 30
COSTO_POR_LADO = 0.01  # spread asumido, en precio (0-1)

TAGS = ["nba", "nhl", "nfl", "cfb", "cbb", "ncaab", "mlb"]
URL_EVENTS = "https://gamma-api.polymarket.com/events"
URL_HIST = "https://clob.polymarket.com/prices-history"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

DATOS = Path(__file__).resolve().parent.parent / "datos"
RUTA_CASOS = DATOS / "exp001_casos.csv"
COLS = ["market_id", "titulo", "inicio_utc", "token_fav", "outcome_fav",
        "p_temprano", "horas_antes", "p_cierre", "deriva_fav"]


def get_json(url, params=None, timeout=20):
    for _ in range(2):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(1)
    return None


def lista(v):
    if isinstance(v, list):
        return v
    try:
        x = json.loads(v)
        return x if isinstance(x, list) else []
    except Exception:
        return []


def fecha(v):
    if not v:
        return None
    s = str(v).strip().replace("Z", "+00:00").replace(" ", "T", 1)
    if len(s) >= 3 and (s[-3] in "+-") and ":" not in s[-3:]:
        s = s + ":00"   # "+00" -> "+00:00"
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def mercados_recientes(ahora):
    salida, vistos = [], set()
    desde = (ahora - timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for tag in TAGS:
        for cerrado in ("true", "false"):
            for pag in range(6):
                lote = get_json(URL_EVENTS, {"tag_slug": tag, "closed": cerrado, "end_date_min": desde,
                                             "order": "endDate", "ascending": "true",
                                             "limit": "50", "offset": str(pag * 50)}, timeout=30)
                if not isinstance(lote, list) or not lote:
                    break
                for ev in lote:
                    for m in ev.get("markets") or []:
                        mid = str(m.get("id"))
                        if mid in vistos or str(m.get("sportsMarketType") or "").lower() != "moneyline":
                            continue
                        outs, toks = lista(m.get("outcomes")), lista(m.get("clobTokenIds"))
                        if len(outs) != 2 or len(toks) != 2 or [str(o).lower() for o in outs] == ["yes", "no"]:
                            continue
                        ini = fecha(m.get("gameStartTime") or ev.get("startTime"))
                        if ini is None:
                            continue
                        h = (ahora - ini).total_seconds() / 3600
                        if not (1 <= h <= 72):
                            continue
                        vistos.add(mid)
                        salida.append({"id": mid, "titulo": str(ev.get("title") or m.get("question") or ""),
                                       "inicio": ini, "outcomes": [str(o) for o in outs],
                                       "tokens": [str(t) for t in toks]})
                if len(lote) < 50:
                    break
    return salida


def historial(token, ini):
    d = get_json(URL_HIST, {"market": token, "startTs": int((ini - timedelta(hours=30)).timestamp()),
                            "endTs": int(ini.timestamp()), "fidelity": 10})
    pts = (d or {}).get("history") if isinstance(d, dict) else None
    if not pts:
        return []
    out = []
    for p in pts:
        try:
            out.append((int(p["t"]), float(p["p"])))
        except Exception:
            continue
    return sorted(out)


def precio_en(pts, ts):
    """Último precio con timestamp <= ts."""
    previo = None
    for t, p in pts:
        if t <= ts:
            previo = (t, p)
        else:
            break
    return previo


def medir(m):
    ini = m["inicio"]
    pts = historial(m["tokens"][0], ini)
    if len(pts) < 3:
        return None
    cierre = precio_en(pts, int((ini - timedelta(minutes=10)).timestamp()))
    temprano = precio_en(pts, int((ini - timedelta(hours=24)).timestamp())) or pts[0]
    if not cierre or not temprano:
        return None
    horas_antes = (ini.timestamp() - temprano[0]) / 3600
    if horas_antes < 6 or temprano[1] in (0, 1) or not (0.03 <= temprano[1] <= 0.97):
        return None
    p0_temp, p0_cierre = temprano[1], cierre[1]
    if p0_temp >= 0.5:   # outcome 0 es favorito
        fav, pt, pc = 0, p0_temp, p0_cierre
    else:                # outcome 1 es favorito (precio complementario)
        fav, pt, pc = 1, 1 - p0_temp, 1 - p0_cierre
    return {"market_id": m["id"], "titulo": m["titulo"][:80], "inicio_utc": ini.isoformat(),
            "token_fav": m["tokens"][fav], "outcome_fav": m["outcomes"][fav],
            "p_temprano": round(pt, 4), "horas_antes": round(horas_antes, 1),
            "p_cierre": round(pc, 4), "deriva_fav": round(pc - pt, 4)}


def cargar_casos():
    if not RUTA_CASOS.exists():
        return {}
    with RUTA_CASOS.open(newline="", encoding="utf-8") as f:
        return {r["market_id"]: r for r in csv.DictReader(f)}


def guardar_casos(casos):
    DATOS.mkdir(parents=True, exist_ok=True)
    with RUTA_CASOS.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in sorted(casos.values(), key=lambda r: r["inicio_utc"]):
            w.writerow({k: r.get(k, "") for k in COLS})


def estadistica(retornos):
    n = len(retornos)
    if n < 2:
        return n, (retornos[0] if n else 0.0), 0.0
    media = sum(retornos) / n
    var = sum((x - media) ** 2 for x in retornos) / (n - 1)
    t = media / math.sqrt(var / n) if var > 0 else 0.0
    return n, media, t


def retornos(casos, lado):
    """Retorno neto por dólar: comprar a p_temprano(+costo), vender a p_cierre(-costo)."""
    out = []
    for r in casos:
        pt, pc = float(r["p_temprano"]), float(r["p_cierre"])
        if lado == "underdog":
            pt, pc = 1 - pt, 1 - pc
        compra, venta = pt + COSTO_POR_LADO, max(pc - COSTO_POR_LADO, 0.0)
        if compra > 0:
            out.append((venta - compra) / compra)
    return out


def main():
    ahora = datetime.now(timezone.utc)
    casos = cargar_casos()
    previos = len(casos)
    mercados = [m for m in mercados_recientes(ahora) if m["id"] not in casos]
    nuevos, fallidos = 0, 0
    for m in mercados[:300]:
        r = medir(m)
        if r:
            casos[m["id"]] = r
            nuevos += 1
        else:
            fallidos += 1
        time.sleep(0.15)
    guardar_casos(casos)

    todos = list(casos.values())
    fuera = [r for r in todos if fecha(r["inicio_utc"]) and fecha(r["inicio_utc"]) > FECHA_CONGELADO]
    res = {}
    for lado in ("favorito", "underdog"):
        n_all, m_all, t_all = estadistica(retornos(todos, lado))
        n_out, m_out, t_out = estadistica(retornos(fuera, lado))
        res[lado] = {"n_total": n_all, "media_total": round(m_all, 4), "t_total": round(t_all, 2),
                     "n_fuera": n_out, "media_fuera": round(m_out, 4), "t_fuera": round(t_out, 2),
                     "pasa": n_out >= N_MINIMO and m_out >= UMBRAL and t_out >= 2}
    mejor = max(res, key=lambda k: res[k]["media_fuera"])
    derivas = [float(r["deriva_fav"]) for r in todos]
    print(json.dumps({
        "experimento": EXPERIMENTO, "version": VERSION,
        "hipotesis": "El favorito deriva de forma sistemática entre T-24h y el inicio",
        "n_total": len(todos), "n_fuera_muestra": len(fuera),
        "ganancia_media_neta": res[mejor]["media_fuera"], "t": res[mejor]["t_fuera"],
        "pasa_umbral": any(v["pasa"] for v in res.values()),
        "detalle": {"estrategias": res, "mejor_lado": mejor, "casos_previos": previos,
                    "casos_nuevos": nuevos, "mercados_sin_datos": fallidos,
                    "mercados_candidatos": len(mercados),
                    "deriva_media_fav": round(sum(derivas) / len(derivas), 4) if derivas else None,
                    "umbral": UMBRAL, "n_minimo": N_MINIMO, "costo_por_lado": COSTO_POR_LADO},
    }, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # el runner necesita siempre un JSON
        print(json.dumps({"experimento": EXPERIMENTO, "version": VERSION, "error": repr(e),
                          "n_total": 0, "n_fuera_muestra": 0, "ganancia_media_neta": 0.0,
                          "t": 0.0, "pasa_umbral": False, "detalle": {}}))
        sys.exit(1)
