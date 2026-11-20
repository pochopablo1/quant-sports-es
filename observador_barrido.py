"""
Observador del Barrido (`observador_barrido.py`) - SOLO MIDE, NO COMPRA NADA.
===============================================================================
Pregunta que responde: cuando termina un partido, ¿el ganador se sigue vendiendo
por debajo de $1 en Polymarket? ¿A qué precio, con cuánta plata disponible y por cuánto tiempo?

Cómo funciona (cada 30 s):
  1. Lee en ESPN los partidos EN JUEGO y FINALIZADOS (NBA, NCAAB, NFL, NCAAF, NHL, MLB).
  2. Los cruza con los moneylines de Polymarket (cruce exacto por nombre de equipo).
  3. Desde que ESPN marca un partido como FINAL, anota cada 30 s el mejor precio de venta (ask)
     del ganador, cuántos USD hay disponibles a <= 0.98 y si el mercado sigue abierto.
  4. Cada hora (y al final) escribe un resumen.

No usa claves ni wallets. Solo depende de `requests`.

Uso (PythonAnywhere -> Tasks -> Always-on task):
    python3 /home/TU_USUARIO/observador_barrido.py
Opcional:  --hasta "2026-11-21 12:00"   (hora Argentina; por defecto mañana 12:00)

Salida (en la misma carpeta del script):
    observador_precios.csv   -> una fila por partido y por medición
    observador_resumen.txt   -> resumen legible
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

ART = timezone(timedelta(hours=-3))
CARPETA = Path(__file__).resolve().parent
RUTA_CSV = CARPETA / "observador_precios.csv"
RUTA_RESUMEN = CARPETA / "observador_resumen.txt"

PRECIO_UMBRAL = 0.98          # precio máximo que nos interesaría pagar
INTERVALO_SEG = 30            # medición cada 30 segundos
REFRESCO_POLY_SEG = 300       # refrescar la lista de mercados de Polymarket cada 5 min
SEGUIR_TRAS_FINAL_MIN = 180   # seguir midiendo hasta 3 h después del final (o hasta que cierre)

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
URL_ESPN = "https://site.api.espn.com/apis/site/v2/sports/{ruta}/scoreboard"
URL_GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"
URL_GAMMA_MARKET = "https://gamma-api.polymarket.com/markets/{id}"
URL_BOOK = "https://clob.polymarket.com/book"

LIGAS = [
    ("basketball/nba", ["nba"]),
    ("basketball/mens-college-basketball", ["ncaab", "cbb"]),
    ("football/nfl", ["nfl"]),
    ("football/college-football", ["cfb", "ncaaf"]),
    ("hockey/nhl", ["nhl"]),
    ("baseball/mlb", ["mlb"]),
]

COLUMNAS = [
    "Hora_ART", "Liga", "Partido", "Ganador", "Min_desde_final", "Mercado_abierto",
    "Mejor_ask", "Mejor_bid", "USD_disponibles_a_<=0.98", "Ganancia_posible_USD",
]


def log(msg: str) -> None:
    print(f"{datetime.now(ART):%Y-%m-%d %H:%M:%S} | {msg}", flush=True)


def norm(texto: Any) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    t = "".join(c if c.isalnum() or c == " " else " " for c in t)
    return " ".join(t.split())


def get_json(url: str, params: Optional[dict] = None, timeout: int = 10) -> Any:
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def parsear_lista(valor: Any) -> List[Any]:
    if isinstance(valor, list):
        return valor
    try:
        v = json.loads(valor)
        return v if isinstance(v, list) else []
    except Exception:
        return []


def parsear_fecha(valor: Any) -> Optional[datetime]:
    if not valor:
        return None
    try:
        s = str(valor).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        try:
            return datetime.strptime(str(valor)[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
        except Exception:
            return None


# ── ESPN ─────────────────────────────────────────────────────────────────────
def nombres(team: Dict[str, Any]) -> set:
    vs = [team.get("displayName"), team.get("shortDisplayName"), team.get("name"),
          team.get("location"), team.get("abbreviation"),
          f"{team.get('location', '')} {team.get('name', '')}"]
    return {norm(v) for v in vs if v and norm(v)}


def leer_espn(ruta: str) -> List[Dict[str, Any]]:
    """Partidos en juego o finalizados (hoy y ayer UTC)."""
    ahora = datetime.now(timezone.utc)
    salida: Dict[str, Dict[str, Any]] = {}
    for d in (0, 1):
        params = {"dates": (ahora - timedelta(days=d)).strftime("%Y%m%d"), "limit": "300"}
        if "college" in ruta:
            params["groups"] = "50" if "basketball" in ruta else "80"
        data = get_json(URL_ESPN.format(ruta=ruta), params) or {}
        for ev in data.get("events") or []:
            comp = (ev.get("competitions") or [{}])[0]
            tipo = (comp.get("status") or ev.get("status") or {}).get("type") or {}
            estado = str(tipo.get("state", "")).lower()
            if estado not in ("in", "post"):
                continue
            eq = comp.get("competitors") or []
            if len(eq) != 2:
                continue
            ganador = None
            if tipo.get("completed"):
                w = [c for c in eq if c.get("winner") is True]
                if len(w) == 1 and str(eq[0].get("score")) != str(eq[1].get("score")):
                    ganador = w[0]
            salida[str(ev.get("id"))] = {
                "id": str(ev.get("id")),
                "liga": ruta.split("/")[-1],
                "inicio": parsear_fecha(ev.get("date")),
                "finalizado": bool(tipo.get("completed")),
                "equipos": [nombres(c.get("team") or {}) for c in eq],
                "nombre_corto": [str((c.get("team") or {}).get("shortDisplayName") or "") for c in eq],
                "ganador_idx": eq.index(ganador) if ganador else None,
                "marcador": " - ".join(f"{(c.get('team') or {}).get('shortDisplayName')} {c.get('score')}" for c in eq),
            }
    return list(salida.values())


# ── Polymarket ───────────────────────────────────────────────────────────────
def leer_moneylines(tags: List[str]) -> List[Dict[str, Any]]:
    ahora = datetime.now(timezone.utc)
    mercados, vistos = [], set()
    for tag in tags:
        for pag in range(4):
            lote = get_json(URL_GAMMA_EVENTS, {
                "active": "true", "closed": "false", "tag_slug": tag, "order": "startDate",
                "ascending": "false", "limit": "100", "offset": str(pag * 100)}, timeout=15)
            if not isinstance(lote, list) or not lote:
                break
            for ev in lote:
                for m in ev.get("markets") or []:
                    if m.get("id") in vistos or m.get("closed"):
                        continue
                    if str(m.get("sportsMarketType") or "").lower() != "moneyline":
                        continue
                    outs = [str(o) for o in parsear_lista(m.get("outcomes"))]
                    toks = [str(t) for t in parsear_lista(m.get("clobTokenIds"))]
                    if len(outs) != 2 or len(toks) != 2 or [o.lower() for o in outs] == ["yes", "no"]:
                        continue
                    inicio = parsear_fecha(m.get("gameStartTime") or ev.get("startTime"))
                    if inicio is None or not (-1 <= (ahora - inicio).total_seconds() / 3600 <= 12):
                        continue
                    vistos.add(m.get("id"))
                    mercados.append({"id": str(m.get("id")), "titulo": str(ev.get("title") or ""),
                                     "inicio": inicio, "outcomes": outs, "tokens": toks})
            if len(lote) < 100:
                break
    return mercados


def cruzar(partido: Dict[str, Any], mercados: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Cruce EXACTO: cada outcome de Polymarket debe coincidir con un nombre del equipo en ESPN."""
    candidatos = []
    for m in mercados:
        if partido["inicio"] and abs((m["inicio"] - partido["inicio"]).total_seconds()) > 6 * 3600:
            continue
        o0, o1 = norm(m["outcomes"][0]), norm(m["outcomes"][1])
        e0, e1 = partido["equipos"]
        if o0 in e0 and o1 in e1:
            candidatos.append((m, [0, 1]))   # outcome i -> equipo ESPN mapa[i]
        elif o0 in e1 and o1 in e0:
            candidatos.append((m, [1, 0]))
    if len(candidatos) != 1:
        return None
    m, mapa = candidatos[0]
    return {**m, "mapa": mapa}


def leer_libro(token: str) -> Dict[str, float]:
    libro = get_json(URL_BOOK, {"token_id": token}, timeout=6)
    if not isinstance(libro, dict):
        return {"ask": 0.0, "bid": 0.0, "usd_bajo_umbral": 0.0, "ganancia": 0.0, "ok": False}
    asks = sorted((float(a["price"]), float(a["size"])) for a in libro.get("asks") or [] if float(a.get("price", 0)) > 0)
    bids = [float(b["price"]) for b in libro.get("bids") or []]
    usd, gan = 0.0, 0.0
    for p, sz in asks:
        if p <= PRECIO_UMBRAL:
            usd += p * sz
            gan += (1 - p) * sz
    return {"ask": asks[0][0] if asks else 0.0, "bid": max(bids) if bids else 0.0,
            "usd_bajo_umbral": round(usd, 2), "ganancia": round(gan, 2), "ok": bool(asks or bids)}


def mercado_abierto(market_id: str) -> Optional[bool]:
    d = get_json(URL_GAMMA_MARKET.format(id=market_id), timeout=8)
    if not isinstance(d, dict):
        return None
    return bool(d.get("active", True)) and not bool(d.get("closed", False))


# ── Resumen ──────────────────────────────────────────────────────────────────
def escribir_resumen(seguimiento: Dict[str, Dict[str, Any]], inicio: datetime) -> None:
    finalizados = [s for s in seguimiento.values() if s.get("t_final")]
    con_oport = [s for s in finalizados if s["max_usd"] > 0]
    lineas = [
        f"RESUMEN DEL OBSERVADOR  ({inicio:%d/%m %H:%M} -> {datetime.now(ART):%d/%m %H:%M} hora ARG)",
        "=" * 70,
        f"Partidos cruzados con Polymarket:          {len(seguimiento)}",
        f"Partidos que terminaron mientras miraba:   {len(finalizados)}",
        f"Con ganador vendiéndose a <= {PRECIO_UMBRAL} tras el final: {len(con_oport)}",
        f"Ganancia teórica máxima sumando todo:      ${sum(s['max_gan'] for s in con_oport):.2f}",
        "",
        "Detalle de cada partido finalizado:",
    ]
    for s in sorted(finalizados, key=lambda x: x["t_final"]):
        cierre = f"cerró a los {s['min_cierre']:.1f} min" if s.get("min_cierre") is not None else "seguía abierto"
        oport = (f"ask<=0.98 durante ~{s['min_oport']:.1f} min, hasta ${s['max_usd']:.2f} disponibles "
                 f"(ganancia posible ${s['max_gan']:.2f})") if s["max_usd"] > 0 else "nunca hubo ask <= 0.98"
        precio = f"primer ask tras final {s['primer_ask']:.3f}" if s.get("primer_ask") else "sin libro"
        lineas.append(f" - [{s['liga']}] {s['marcador']} | ganó {s['ganador']} | {precio} | {oport} | {cierre}")
    RUTA_RESUMEN.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    log(f"Resumen actualizado: {len(finalizados)} finalizados, {len(con_oport)} con oportunidad.")


# ── Loop principal ───────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser()
    manana = (datetime.now(ART) + timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    ap.add_argument("--hasta", default=manana.strftime("%Y-%m-%d %H:%M"), help="hora Argentina 'AAAA-MM-DD HH:MM'")
    args = ap.parse_args()
    fin = datetime.strptime(args.hasta, "%Y-%m-%d %H:%M").replace(tzinfo=ART)
    inicio = datetime.now(ART)
    log(f"Observador iniciado. Mide hasta {fin:%d/%m %H:%M} (hora ARG). No compra nada.")

    if not RUTA_CSV.exists():
        with open(RUTA_CSV, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(COLUMNAS)

    mercados_por_liga: Dict[str, List[Dict[str, Any]]] = {}
    ultimo_refresco = 0.0
    seguimiento: Dict[str, Dict[str, Any]] = {}   # clave: id ESPN
    ultimo_resumen = time.time()

    while datetime.now(ART) < fin:
        t0 = time.time()
        if t0 - ultimo_refresco > REFRESCO_POLY_SEG:
            for ruta, tags in LIGAS:
                mercados_por_liga[ruta] = leer_moneylines(tags)
            ultimo_refresco = t0
            log("Mercados Polymarket abiertos: " + ", ".join(
                f"{r.split('/')[-1]}={len(v)}" for r, v in mercados_por_liga.items()))

        ahora = datetime.now(timezone.utc)
        filas = []
        for ruta, _ in LIGAS:
            for p in leer_espn(ruta):
                s = seguimiento.get(p["id"])
                if s is None:
                    m = cruzar(p, mercados_por_liga.get(ruta, []))
                    if not m:
                        continue
                    s = seguimiento[p["id"]] = {
                        "liga": p["liga"], "marcador": p["marcador"], "mercado": m, "t_final": None,
                        "ganador": "", "token": "", "max_usd": 0.0, "max_gan": 0.0,
                        "min_oport": 0.0, "primer_ask": None, "min_cierre": None, "terminado": False,
                    }
                    log(f"Siguiendo: [{p['liga']}] {m['titulo']}")
                if s["terminado"]:
                    continue
                s["marcador"] = p["marcador"]
                if not p["finalizado"] or p["ganador_idx"] is None:
                    continue
                if s["t_final"] is None:
                    s["t_final"] = ahora
                    mapa = s["mercado"]["mapa"]
                    idx_outcome = mapa.index(p["ganador_idx"])
                    s["ganador"] = s["mercado"]["outcomes"][idx_outcome]
                    s["token"] = s["mercado"]["tokens"][idx_outcome]
                    log(f"FINAL: [{p['liga']}] {p['marcador']} -> gana {s['ganador']}")

                min_desde = (ahora - s["t_final"]).total_seconds() / 60
                libro = leer_libro(s["token"])
                abierto = mercado_abierto(s["mercado"]["id"])
                if abierto is None:
                    abierto = libro["ok"]
                if s["primer_ask"] is None and libro["ask"]:
                    s["primer_ask"] = libro["ask"]
                if libro["usd_bajo_umbral"] > 0:
                    s["min_oport"] = min_desde
                    s["max_usd"] = max(s["max_usd"], libro["usd_bajo_umbral"])
                    s["max_gan"] = max(s["max_gan"], libro["ganancia"])
                    log(f"  OPORTUNIDAD: {s['ganador']} ask {libro['ask']:.3f} | ${libro['usd_bajo_umbral']:.2f} "
                        f"a <= {PRECIO_UMBRAL} | {min_desde:.1f} min tras el final")
                filas.append([f"{datetime.now(ART):%Y-%m-%d %H:%M:%S}", p["liga"], p["marcador"], s["ganador"],
                              f"{min_desde:.1f}", abierto, libro["ask"], libro["bid"],
                              libro["usd_bajo_umbral"], libro["ganancia"]])
                if not abierto:
                    s["min_cierre"] = min_desde
                    s["terminado"] = True
                    log(f"  Mercado cerrado: {s['ganador']} ({min_desde:.1f} min tras el final)")
                elif min_desde > SEGUIR_TRAS_FINAL_MIN:
                    s["terminado"] = True

        if filas:
            with open(RUTA_CSV, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows(filas)
        if time.time() - ultimo_resumen > 3600:
            escribir_resumen(seguimiento, inicio)
            ultimo_resumen = time.time()
        time.sleep(max(1.0, INTERVALO_SEG - (time.time() - t0)))

    escribir_resumen(seguimiento, inicio)
    log("Observación terminada. Mirá observador_resumen.txt")
    while True:  # las Always-on tasks se reinician si el script termina: quedarse quieto
        time.sleep(3600)


if __name__ == "__main__":
    main()
