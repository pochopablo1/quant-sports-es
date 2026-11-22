"""
Escáner de Fútbol 3-vías en Polymarket (`escaner_futbol.py`) - SOLO MIDE, NO COMPRA.
====================================================================================
En un partido de fútbol hay 3 mercados (gana local / empate / gana visitante) y
EXACTAMENTE UNO paga. Entonces:
  - Comprar el SÍ de los 3 paga $1 seguro  -> conviene si cuesta < $1.
  - Comprar el NO de los 3 paga $2 seguro  -> conviene si cuesta < $2.

Cada 60 s revisa los partidos de fútbol (pre-partido y EN VIVO), y cuando la suma
no cierra lee el LIBRO DE ÓRDENES real de las 3 patas para medir:
  - cuántos "juegos completos" se pueden comprar con ganancia >= 2% (fees incluidos)
  - cuánta plata y ganancia había disponible
  - cuántos minutos duró la oportunidad

Salida (misma carpeta):
  futbol_oportunidades.csv  -> cada detección
  futbol_resumen.txt        -> resumen (se actualiza cada hora y al final)

Uso:  python3 escaner_futbol.py                 (24 h)
      python3 escaner_futbol.py --horas 48
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

ART = timezone(timedelta(hours=-3))
CARPETA = Path(__file__).resolve().parent
RUTA_CSV = CARPETA / "futbol_oportunidades.csv"
RUTA_RESUMEN = CARPETA / "futbol_resumen.txt"

URL_EVENTS = "https://gamma-api.polymarket.com/events"
URL_BOOK = "https://clob.polymarket.com/book"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

INTERVALO_SEG = 60
MARGEN_MIN = 0.005         # se anota desde 0.5% neto (casi-oportunidades)
MARGEN_UTIL = 0.02         # 2% neto = oportunidad útil
TASA_FEE = 0.05            # fee taker deportes ~ shares * 0.05 * p * (1 - p)
FILTRO_PREVIO = 0.005      # pre-filtro barato con bestBid/bestAsk de gamma

COLUMNAS = ["Hora_ART", "Partido", "Liga", "En_vivo", "Marcador", "Periodo", "Tipo",
            "Costo_por_juego", "Paga_por_juego", "Margen_neto_pct", "Juegos_disponibles",
            "USD_invertibles", "Ganancia_USD", "Minutos_activa", "Link"]


def log(msg: str) -> None:
    print(f"{datetime.now(ART):%Y-%m-%d %H:%M:%S} | {msg}", flush=True)


def get_json(url: str, params: Optional[dict] = None, timeout: int = 20) -> Any:
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        return r.json() if r.status_code == 200 else None
    except Exception:
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


def fee(p: float) -> float:
    return TASA_FEE * p * (1 - p)


# ── Partidos ─────────────────────────────────────────────────────────────────
def leer_partidos() -> List[Dict[str, Any]]:
    """Partidos de fútbol de 3 resultados que empezaron hace <= 3 h o empiezan en <= 12 h."""
    ahora = datetime.now(timezone.utc)
    params_base = {
        "closed": "false", "tag_slug": "soccer", "order": "endDate", "ascending": "true",
        "end_date_min": (ahora - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_date_max": (ahora + timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "limit": "100",
    }
    partidos = []
    for pag in range(10):
        lote = get_json(URL_EVENTS, {**params_base, "offset": str(pag * 100)}, timeout=40)
        if not isinstance(lote, list) or not lote:
            break
        for ev in lote:
            if not ev.get("negRisk") or ev.get("negRiskAugmented") or ev.get("ended"):
                continue
            mk = ev.get("markets") or []
            if len(mk) != 3 or any(m.get("closed") or m.get("acceptingOrders") is False for m in mk):
                continue
            if any(str(m.get("sportsMarketType") or "") != "moneyline" for m in mk):
                continue
            tokens = [lista(m.get("clobTokenIds")) for m in mk]
            if any(len(t) != 2 for t in tokens):
                continue
            tags = [t.get("slug") for t in ev.get("tags") or [] if isinstance(t, dict)]
            liga = next((t for t in tags if t not in ("sports", "games", "soccer")), "")
            partidos.append({
                "titulo": str(ev.get("title") or ""), "slug": ev.get("slug", ""), "liga": liga,
                "vivo": bool(ev.get("live")), "marcador": ev.get("score") or "", "periodo": ev.get("period") or "",
                "asks": [num(m.get("bestAsk")) for m in mk], "bids": [num(m.get("bestBid")) for m in mk],
                "tok_si": [t[0] for t in tokens], "tok_no": [t[1] for t in tokens],
            })
        if len(lote) < 100:
            break
    return partidos


# ── Libro de órdenes ─────────────────────────────────────────────────────────
def asks_de(token: str) -> List[Tuple[float, float]]:
    libro = get_json(URL_BOOK, {"token_id": token}, timeout=8)
    if not isinstance(libro, dict):
        return []
    return sorted((float(a["price"]), float(a["size"])) for a in libro.get("asks") or [] if float(a.get("price", 0)) > 0)


def medir_juegos(libros: List[List[Tuple[float, float]]], paga: float) -> Tuple[float, float, float]:
    """Compra 'juegos completos' (1 share de cada pata) mientras el margen neto marginal sea >= MARGEN_MIN.
    Devuelve (juegos, usd_invertidos, ganancia_usd)."""
    libros = [list(l) for l in libros]
    if any(not l for l in libros):
        return 0.0, 0.0, 0.0
    juegos = invertido = ganancia = 0.0
    idx = [0, 0, 0]
    restante = [libros[i][0][1] for i in range(3)]
    while all(idx[i] < len(libros[i]) for i in range(3)):
        precios = [libros[i][idx[i]][0] for i in range(3)]
        costo = sum(p + fee(p) for p in precios)
        if paga / costo - 1 < MARGEN_MIN:
            break
        q = min(restante)
        juegos += q
        invertido += q * costo
        ganancia += q * (paga - costo)
        for i in range(3):
            restante[i] -= q
            if restante[i] <= 1e-9:
                idx[i] += 1
                if idx[i] < len(libros[i]):
                    restante[i] = libros[i][idx[i]][1]
    return round(juegos, 2), round(invertido, 2), round(ganancia, 2)


def evaluar(p: Dict[str, Any]) -> List[Dict[str, Any]]:
    oportunidades = []
    asks, bids = p["asks"], p["bids"]
    # Pre-filtro barato: solo leer libros si la suma parece no cerrar
    posible_si = all(a for a in asks) and sum(asks) < 1 - FILTRO_PREVIO
    # un bid faltante cuenta como 0 (pasa en vivo con resultados casi muertos: justo donde hay oportunidades)
    posible_no = sum(b or 0.0 for b in bids) > 1 + FILTRO_PREVIO
    for tipo, posible, tokens, paga in (("TODOS_SI", posible_si, p["tok_si"], 1.0),
                                        ("TODOS_NO", posible_no, p["tok_no"], 2.0)):
        if not posible:
            continue
        libros = [asks_de(t) for t in tokens]
        juegos, invertido, ganancia = medir_juegos(libros, paga)
        if juegos <= 0:
            continue
        costo = invertido / juegos
        oportunidades.append({
            "Partido": p["titulo"], "Liga": p["liga"], "En_vivo": p["vivo"], "Marcador": p["marcador"],
            "Periodo": p["periodo"], "Tipo": tipo, "Costo_por_juego": round(costo, 4), "Paga_por_juego": paga,
            "Margen_neto_pct": round((paga / costo - 1) * 100, 2), "Juegos_disponibles": juegos,
            "USD_invertibles": invertido, "Ganancia_USD": ganancia,
            "Link": f"https://polymarket.com/event/{p['slug']}",
        })
    return oportunidades


# ── Resumen ──────────────────────────────────────────────────────────────────
def escribir_resumen(historial: Dict[str, Dict[str, Any]], inicio: datetime, escaneos: int, partidos_vistos: int) -> None:
    ops = sorted(historial.values(), key=lambda o: -o["max_ganancia"])
    utiles = [o for o in ops if o["max_usd"] >= 5 and o["max_margen"] >= MARGEN_UTIL * 100]
    buenas = [o for o in ops if o["max_margen"] >= MARGEN_UTIL * 100]
    lineas = [
        f"ESCÁNER DE FÚTBOL ({inicio:%d/%m %H:%M} -> {datetime.now(ART):%d/%m %H:%M} hora ARG)",
        "=" * 70,
        f"Escaneos: {escaneos} | partidos distintos revisados: {partidos_vistos}",
        f"Casi-oportunidades (margen neto >= {MARGEN_MIN*100:.1f}%): {len(ops)}",
        f"Oportunidades útiles (>= {MARGEN_UTIL*100:.0f}%): {len(buenas)} | con >= $5 invertibles: {len(utiles)}",
        f"  en vivo: {sum(1 for o in ops if o['vivo'])} | pre-partido: {sum(1 for o in ops if not o['vivo'])}",
        f"Ganancia máxima sumando la mejor foto de cada una: ${sum(o['max_ganancia'] for o in ops):.2f}",
        "", "Detalle (ordenado por ganancia):",
    ]
    for o in ops[:40]:
        lineas.append(f" - {o['partido']} [{o['liga']}] {o['tipo']} | margen máx {o['max_margen']}% | "
                      f"hasta ${o['max_usd']} invertibles -> +${o['max_ganancia']} | "
                      f"duró ~{o['minutos']} min | {'EN VIVO' if o['vivo'] else 'pre-partido'}")
    RUTA_RESUMEN.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horas", type=float, default=24.0)
    args = ap.parse_args()
    inicio = datetime.now(ART)
    fin = inicio + timedelta(hours=args.horas)
    log(f"Escáner de fútbol iniciado hasta {fin:%d/%m %H:%M} (hora ARG). No compra nada.")

    if not RUTA_CSV.exists():
        with open(RUTA_CSV, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(COLUMNAS)

    historial: Dict[str, Dict[str, Any]] = {}
    vistos: set = set()
    escaneos, ultimo_resumen = 0, time.time()
    while datetime.now(ART) < fin:
        t0 = time.time()
        try:
            partidos = leer_partidos()
            escaneos += 1
            vistos.update(p["slug"] for p in partidos)
            en_vivo = sum(1 for p in partidos if p["vivo"])
            nuevas = 0
            for p in partidos:
                for o in evaluar(p):
                    clave = f"{p['slug']}|{o['Tipo']}"
                    h = historial.setdefault(clave, {
                        "partido": o["Partido"], "liga": o["Liga"], "tipo": o["Tipo"], "vivo": o["En_vivo"],
                        "primera": time.time(), "max_margen": 0.0, "max_usd": 0.0, "max_ganancia": 0.0, "minutos": 0.0})
                    h["minutos"] = round((time.time() - h["primera"]) / 60, 1)
                    h["max_margen"] = max(h["max_margen"], o["Margen_neto_pct"])
                    h["max_usd"] = max(h["max_usd"], o["USD_invertibles"])
                    h["max_ganancia"] = max(h["max_ganancia"], o["Ganancia_USD"])
                    with open(RUTA_CSV, "a", newline="", encoding="utf-8") as f:
                        csv.DictWriter(f, fieldnames=COLUMNAS).writerow(
                            {"Hora_ART": f"{datetime.now(ART):%Y-%m-%d %H:%M:%S}", "Minutos_activa": h["minutos"], **o})
                    nuevas += 1
                    log(f"  OPORTUNIDAD {o['Tipo']} {o['Margen_neto_pct']}% | {o['Partido']} | "
                        f"${o['USD_invertibles']} invertibles -> +${o['Ganancia_USD']} | "
                        f"{'EN VIVO ' + str(o['Marcador']) if o['En_vivo'] else 'pre-partido'}")
            log(f"Escaneo {escaneos}: {len(partidos)} partidos ({en_vivo} en vivo), {nuevas} oportunidades")
        except Exception as exc:
            log(f"Error: {exc}")
        if time.time() - ultimo_resumen > 3600:
            escribir_resumen(historial, inicio, escaneos, len(vistos))
            ultimo_resumen = time.time()
        time.sleep(max(1.0, INTERVALO_SEG - (time.time() - t0)))

    escribir_resumen(historial, inicio, escaneos, len(vistos))
    log("Terminado. Mirá futbol_resumen.txt")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
