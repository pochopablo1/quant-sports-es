"""
Barredor de Mercados Decididos 24/7 (`barredor_24_7.py`).
==========================================================
Compra en Polymarket el GANADOR de partidos que YA TERMINARON pero cuyo mercado
todavía no se liquidó y se sigue vendiendo por debajo de $1 (ej. 0.96 - 0.98).
Al liquidarse, cada share paga $1.00 -> ganancia = (1 - precio) por share.

Capas de seguridad (todas obligatorias para comprar):
  1. ESPN confirma el partido FINALIZADO (`completed`), con ganador marcado y sin empate.
  2. Solo ligas sin empate en el Moneyline: NBA, NCAAB, NFL, NCAAF, NHL, MLB.
  3. Ambos equipos de Polymarket coinciden con los de ESPN (similitud >= 90) y la fecha es compatible.
  4. Consenso del propio mercado: el BID del ganador en Polymarket >= BARREDOR_BID_MIN (0.90).
     Si el reglamento de Polymarket difiere de ESPN (ej. alargue), el mercado no lo va a pagar alto y se descarta.
  5. Precio de compra VWAP <= BARREDOR_PRECIO_MAX (0.98) con liquidez suficiente en el libro.
  6. Nunca repite un token (historial CSV + candado On-Chain de `firmar_orden_polymarket_clob`).
  7. Tope de $6 por orden (candado de `gestor_wallet`) y stake configurable.

Ejecución real: respeta `EJECUCION_REAL_HABILITADA=true` del .env (mismo candado que el bot de surebets).

Uso:
  python barredor_24_7.py            # loop 24/7 (cada BARREDOR_INTERVALO_SEG)
  python barredor_24_7.py --una-vez  # un solo escaneo (para probar)
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RUTA_BASE = Path(__file__).resolve().parent
if str(RUTA_BASE) not in sys.path:
    sys.path.insert(0, str(RUTA_BASE))

from configuracion import DIRECTORIO_DATOS, TELEGRAM_TOKEN, CHAT_ID  # noqa: E402
from extractores.polymarket import parsear_campo_json  # noqa: E402
from normalizador.emparejador import similitud_equipos, parsear_datetime_utc  # noqa: E402
from ejecutor.verificador_atomico import verificar_pata_polymarket_vwap  # noqa: E402
from ejecutor.gestor_wallet import firmar_orden_polymarket_clob, verificar_estado_wallet  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("Barredor")

# ── Parámetros (se pueden cambiar desde el .env) ─────────────────────────────
PRECIO_MAX = float(os.getenv("BARREDOR_PRECIO_MAX", "0.98"))      # pagar como máximo 0.98 (>= 2% bruto)
BID_MIN = float(os.getenv("BARREDOR_BID_MIN", "0.90"))            # consenso mínimo del mercado
STAKE_USD = float(os.getenv("BARREDOR_STAKE_USD", "5.0"))         # monto por compra (tope duro $6)
INTERVALO_SEG = int(os.getenv("BARREDOR_INTERVALO_SEG", "180"))   # cada 3 minutos
SIMILITUD_MIN = 90.0

URL_GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"
URL_ESPN = "https://site.api.espn.com/apis/site/v2/sports/{ruta}/scoreboard"
RUTA_HISTORIAL = DIRECTORIO_DATOS / "historial_barredor.csv"

# (ruta ESPN, tags de Polymarket)  -> solo ligas SIN empate en el Moneyline
LIGAS = [
    ("basketball/nba", ["nba"]),
    ("basketball/mens-college-basketball", ["ncaab", "cbb"]),
    ("football/nfl", ["nfl"]),
    ("football/college-football", ["cfb", "ncaaf"]),
    ("hockey/nhl", ["nhl"]),
    ("baseball/mlb", ["mlb"]),
]
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

COLUMNAS_HISTORIAL = [
    "Fecha_UTC", "Modo", "Estado", "Liga", "Evento_Polymarket", "Ganador", "Marcador_ESPN",
    "Token", "Precio_VWAP", "Bid", "Stake_USD", "Ganancia_Esperada_USD", "Detalle",
]


# ── ESPN: partidos finalizados ───────────────────────────────────────────────
def obtener_finalizados_espn(ruta: str) -> List[Dict[str, Any]]:
    """Devuelve partidos FINALIZADOS (hoy y ayer UTC) con ganador claro y sin empate."""
    ahora = datetime.now(timezone.utc)
    fechas = sorted({(ahora - timedelta(days=d)).strftime("%Y%m%d") for d in (0, 1)})
    finalizados: List[Dict[str, Any]] = []
    vistos = set()
    for fecha in fechas:
        params = {"dates": fecha, "limit": "300"}
        if "college" in ruta:
            params["groups"] = "50" if "basketball" in ruta else "80"  # todas las divisiones I
        try:
            resp = requests.get(URL_ESPN.format(ruta=ruta), params=params, headers=HEADERS, timeout=10)
            if resp.status_code != 200:
                continue
            eventos = resp.json().get("events") or []
        except Exception as exc:
            logger.debug("ESPN %s %s: %s", ruta, fecha, exc)
            continue

        for ev in eventos:
            if ev.get("id") in vistos:
                continue
            comp = (ev.get("competitions") or [{}])[0]
            estado = (comp.get("status") or ev.get("status") or {}).get("type") or {}
            if not estado.get("completed") or str(estado.get("state", "")).lower() != "post":
                continue
            equipos = comp.get("competitors") or []
            if len(equipos) != 2:
                continue
            try:
                s0, s1 = float(equipos[0].get("score") or 0), float(equipos[1].get("score") or 0)
            except (TypeError, ValueError):
                continue
            ganadores = [c for c in equipos if c.get("winner") is True]
            if s0 == s1 or len(ganadores) != 1:
                continue  # empate o sin ganador claro -> no se toca
            ganador = ganadores[0]
            perdedor = equipos[1] if ganador is equipos[0] else equipos[0]
            if float(ganador.get("score") or 0) <= float(perdedor.get("score") or 0):
                continue  # inconsistencia de datos -> no se toca

            vistos.add(ev.get("id"))
            finalizados.append({
                "ruta": ruta,
                "inicio": ev.get("date") or comp.get("date"),
                "ganador": _nombres_equipo(ganador),
                "perdedor": _nombres_equipo(perdedor),
                "marcador": f"{_nombres_equipo(ganador)[0]} {ganador.get('score')} - "
                            f"{perdedor.get('score')} {_nombres_equipo(perdedor)[0]}",
            })
    return finalizados


def _nombres_equipo(competidor: Dict[str, Any]) -> List[str]:
    t = competidor.get("team") or {}
    nombres = [t.get("displayName"), t.get("shortDisplayName"), t.get("name"), t.get("location"),
               f"{t.get('location', '')} {t.get('name', '')}".strip()]
    return [str(n) for n in nombres if n]


def _similitud_max(nombre: str, alternativas: List[str]) -> float:
    return max((similitud_equipos(nombre, a) for a in alternativas), default=0.0)


# ── Polymarket: moneylines abiertos de partidos ya empezados ─────────────────
def obtener_moneylines_polymarket(tags: List[str]) -> List[Dict[str, Any]]:
    """Mercados Moneyline 2-vías (equipo vs equipo) aún abiertos, cuyo partido empezó hace 1.5h - 30h."""
    ahora = datetime.now(timezone.utc)
    mercados: List[Dict[str, Any]] = []
    vistos = set()
    for tag in tags:
        desde = (ahora - timedelta(hours=32)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for pag in range(5):
            params = {
                "closed": "false", "tag_slug": tag, "end_date_min": desde,
                "order": "endDate", "ascending": "true", "limit": "50", "offset": str(pag * 50),
            }
            try:
                resp = requests.get(URL_GAMMA_EVENTS, params=params, headers=HEADERS, timeout=30)
                resp.raise_for_status()
                lote = resp.json()
            except Exception as exc:
                logger.debug("Gamma %s pág %d: %s", tag, pag, exc)
                break
            if not isinstance(lote, list) or not lote:
                break
            for ev in lote:
                for m in ev.get("markets") or []:
                    if m.get("id") in vistos or m.get("closed") or not m.get("active", True):
                        continue
                    if str(m.get("sportsMarketType") or "").lower().strip() != "moneyline":
                        continue
                    if str(m.get("umaResolutionStatus") or "").lower() in ("disputed", "resolved"):
                        continue
                    outcomes = [str(o) for o in parsear_campo_json(m.get("outcomes"))]
                    tokens = [str(t) for t in parsear_campo_json(m.get("clobTokenIds"))]
                    if len(outcomes) != 2 or len(tokens) != 2:
                        continue
                    if [o.lower() for o in outcomes] == ["yes", "no"] or any(
                        o.lower() in ("draw", "tie", "empate") for o in outcomes
                    ):
                        continue  # mercados Sí/No o con empate -> fuera del barredor
                    inicio = parsear_datetime_utc(m.get("gameStartTime") or ev.get("startTime"))
                    if inicio is None:
                        continue
                    horas = (ahora - inicio).total_seconds() / 3600.0
                    if not (1.5 <= horas <= 30.0):
                        continue
                    vistos.add(m.get("id"))
                    mercados.append({
                        "evento": str(ev.get("title") or m.get("question") or ""),
                        "inicio": inicio.isoformat(),
                        "outcomes": outcomes,
                        "tokens": tokens,
                    })
            if len(lote) < 50:
                break
    return mercados


def obtener_mejor_bid(token_id: str) -> float:
    try:
        resp = requests.get("https://clob.polymarket.com/book", params={"token_id": token_id}, timeout=6)
        if resp.status_code != 200:
            return 0.0
        bids = resp.json().get("bids") or []
        return max((float(b.get("price", 0)) for b in bids), default=0.0)
    except Exception:
        return 0.0


# ── Cruce ESPN <-> Polymarket ────────────────────────────────────────────────
def emparejar_ganador(mercado: Dict[str, Any], finalizados: List[Dict[str, Any]]) -> Optional[Tuple[int, Dict[str, Any]]]:
    """Devuelve (índice del outcome ganador en Polymarket, partido ESPN) solo si el cruce es inequívoco."""
    candidatos = []
    o1, o2 = mercado["outcomes"]
    inicio_poly = parsear_datetime_utc(mercado["inicio"])
    for p in finalizados:
        inicio_espn = parsear_datetime_utc(p["inicio"])
        if inicio_poly and inicio_espn and abs((inicio_poly - inicio_espn).total_seconds()) > 6 * 3600:
            continue
        g1, p2 = _similitud_max(o1, p["ganador"]), _similitud_max(o2, p["perdedor"])
        g2, p1 = _similitud_max(o2, p["ganador"]), _similitud_max(o1, p["perdedor"])
        if min(g1, p2) >= SIMILITUD_MIN and max(g2, p1) < SIMILITUD_MIN:
            candidatos.append((0, p))
        elif min(g2, p1) >= SIMILITUD_MIN and max(g1, p2) < SIMILITUD_MIN:
            candidatos.append((1, p))
    return candidatos[0] if len(candidatos) == 1 else None  # 0 o >1 coincidencias -> no se toca


# ── Historial ────────────────────────────────────────────────────────────────
def tokens_en_historial(estados: Tuple[str, ...]) -> set:
    if not RUTA_HISTORIAL.exists():
        return set()
    with open(RUTA_HISTORIAL, newline="", encoding="utf-8") as f:
        return {r["Token"] for r in csv.DictReader(f) if r.get("Estado") in estados}


def registrar(fila: Dict[str, Any]) -> None:
    nuevo = not RUTA_HISTORIAL.exists()
    with open(RUTA_HISTORIAL, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS_HISTORIAL)
        if nuevo:
            w.writeheader()
        w.writerow({k: fila.get(k, "") for k in COLUMNAS_HISTORIAL})


def enviar_telegram(texto: str) -> None:
    if not TELEGRAM_TOKEN or not CHAT_ID:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": CHAT_ID, "text": texto}, timeout=8)
    except Exception:
        pass


# ── Escaneo principal ────────────────────────────────────────────────────────
def escanear_una_vez() -> int:
    from dotenv import load_dotenv
    load_dotenv(RUTA_BASE / ".env", override=True)
    modo_real = os.getenv("EJECUCION_REAL_HABILITADA", "false").lower() == "true"
    modo = "REAL" if modo_real else "PAPEL"

    saldo = None
    if modo_real:
        try:
            saldo = float(verificar_estado_wallet().get("polygon_pusd_polymarket") or 0.0)
        except Exception as exc:
            logger.warning("No se pudo leer el saldo de Polymarket: %s", exc)

    operados = tokens_en_historial(("COMPRADO", "SIMULADO"))
    descartados = tokens_en_historial(("DESCARTADO_SIN_CONSENSO",))
    compras = 0
    for ruta, tags in LIGAS:
        finalizados = obtener_finalizados_espn(ruta)
        if not finalizados:
            continue
        mercados = obtener_moneylines_polymarket(tags)
        logger.info("%s: %d partidos finalizados en ESPN | %d moneylines abiertos en Polymarket",
                    ruta, len(finalizados), len(mercados))

        for mkt in mercados:
            cruce = emparejar_ganador(mkt, finalizados)
            if not cruce:
                continue
            idx, partido = cruce
            token = mkt["tokens"][idx]
            if token in operados:
                continue

            ok, cuota_vwap, liq, _, detalle_libro = verificar_pata_polymarket_vwap(token, STAKE_USD)
            if not ok or cuota_vwap <= 1.0:
                logger.info("  %s -> sin liquidez útil (%s)", mkt["evento"], detalle_libro)
                continue
            precio = round(1.0 / cuota_vwap, 4)
            bid = obtener_mejor_bid(token)
            ganancia = round(STAKE_USD * (1.0 / precio - 1.0), 2)
            base = {
                "Fecha_UTC": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "Modo": modo, "Liga": ruta, "Evento_Polymarket": mkt["evento"],
                "Ganador": mkt["outcomes"][idx], "Marcador_ESPN": partido["marcador"],
                "Token": token, "Precio_VWAP": precio, "Bid": bid, "Stake_USD": STAKE_USD,
                "Ganancia_Esperada_USD": ganancia,
            }

            if precio > PRECIO_MAX:
                logger.info("  %s -> %s ya cotiza %.3f (> %.2f), sin margen", mkt["evento"], base["Ganador"], precio, PRECIO_MAX)
                continue
            if bid < BID_MIN:
                if token not in descartados:  # se re-evalúa cada vuelta, pero se anota una sola vez
                    logger.warning("  %s -> BID %.2f < %.2f: el mercado no confirma a %s. Se descarta por seguridad.",
                                   mkt["evento"], bid, BID_MIN, base["Ganador"])
                    registrar({**base, "Estado": "DESCARTADO_SIN_CONSENSO", "Detalle": f"bid={bid}"})
                    descartados.add(token)
                continue

            if not modo_real:
                logger.info("  [PAPEL] Compraría %s @ %.3f ($%.2f -> +$%.2f) | %s",
                            base["Ganador"], precio, STAKE_USD, ganancia, partido["marcador"])
                registrar({**base, "Estado": "SIMULADO", "Detalle": detalle_libro})
                operados.add(token)
                compras += 1
                continue

            if saldo is not None and saldo < STAKE_USD:
                logger.info("  Saldo insuficiente en Polymarket ($%.2f) para %s", saldo, mkt["evento"])
                continue

            precio_limite = min(PRECIO_MAX, round(precio + 0.005, 2))
            exito, msg = firmar_orden_polymarket_clob(token_id=token, precio=precio_limite,
                                                      tamano_usd=STAKE_USD, lado="BUY", tipo_orden="FOK")
            registrar({**base, "Estado": "COMPRADO" if exito else "FALLIDO", "Detalle": msg})
            if exito:
                operados.add(token)
                compras += 1
                if saldo is not None:
                    saldo -= STAKE_USD
                logger.info("  ✅ COMPRADO %s @ %.3f | %s", base["Ganador"], precio, msg)
                enviar_telegram(f"🧹 Barredor: compré {base['Ganador']} @ {precio:.3f} (${STAKE_USD:.2f})\n"
                                f"{partido['marcador']}\nGanancia esperada: +${ganancia:.2f}")
            else:
                logger.warning("  ❌ No se ejecutó %s: %s", base["Ganador"], msg)
    return compras


def main() -> None:
    parser = argparse.ArgumentParser(description="Barredor de mercados decididos en Polymarket")
    parser.add_argument("--una-vez", action="store_true", help="Ejecuta un solo escaneo y termina")
    args = parser.parse_args()

    logger.info("Barredor iniciado | precio máx %.2f | bid mín %.2f | stake $%.2f", PRECIO_MAX, BID_MIN, STAKE_USD)
    if args.una_vez:
        logger.info("Compras en este escaneo: %d", escanear_una_vez())
        return
    while True:
        try:
            n = escanear_una_vez()
            logger.info("Escaneo terminado: %d compras. Próximo en %ds.", n, INTERVALO_SEG)
        except Exception as exc:
            logger.exception("Error en el escaneo: %s", exc)
        time.sleep(INTERVALO_SEG)


if __name__ == "__main__":
    main()
