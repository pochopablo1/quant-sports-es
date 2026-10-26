"""
Extractor de Manifold Markets (API v0 - Mercados de Predicción).
Consulta `https://api.manifold.markets/v0/search-markets` para deportes principales
(NBA, NFL, MLB, NHL, UFC, Champions League, Premier League, Tenis), filtrando enfrentamientos
binarios (`vs` / `vs.`) con liquidez activa y convirtiendo la probabilidad implícita del AMM (CPMM-1)
a cuotas decimales equivalentes.
"""
import logging
import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple
import requests
from configuracion import calcular_overround_pct

logger = logging.getLogger(__name__)

URL_MANIFOLD_SEARCH = "https://api.manifold.markets/v0/search-markets"

TERMINOS_DEPORTIVOS: List[Tuple[str, str, str]] = [
    ("NBA vs", "Básquetbol", "NBA"),
    ("NFL vs", "Fútbol Americano", "NFL"),
    ("MLB vs", "Béisbol", "MLB"),
    ("NHL vs", "Hockey sobre Hielo", "NHL"),
    ("UFC vs", "MMA / Boxeo", "UFC"),
    ("Premier League vs", "Fútbol", "Premier League"),
    ("Champions League vs", "Fútbol", "UEFA Champions League"),
    ("ATP vs", "Tenis", "ATP"),
]


def _parsear_equipos_pregunta_manifold(pregunta: str) -> Tuple[str, str, str]:
    """
    Extrae (evento_limpio, lado_1, lado_2) desde preguntas de Manifold como:
      - 'NBA: Celtics vs. Knicks'
      - 'Will the Warriors beat the Lakers?'
      - 'Commanders vs 49ers: Who will win?'
    """
    q = str(pregunta or "").strip()
    # Quitar prefijos como 'NBA:' o 'NFL Week 7:' y sufijos como ': Who will win?'
    q_limpia = re.sub(r"^\[.*?\]\s*", "", q)
    q_limpia = re.sub(r"^[A-Za-z0-9\s]+:\s*", "", q_limpia)
    q_limpia = re.sub(r"[:\-\?]\s*(who will win|winner|moneyline).*$", "", q_limpia, flags=re.I)
    q_limpia = q_limpia.rstrip("?").strip()

    # Patrón 1: "Equipo A vs. Equipo B"
    partes_vs = re.split(r"\s+vs\.?\s+", q_limpia, flags=re.IGNORECASE)
    if len(partes_vs) == 2:
        eq1 = re.sub(r"^will\s+(the\s+)?", "", partes_vs[0], flags=re.I).strip()
        eq2 = re.sub(r"\s+(win|have|score).*$", "", partes_vs[1], flags=re.I).strip()
        if eq1 and eq2 and len(eq1) < 35 and len(eq2) < 35:
            return f"{eq1} vs {eq2}", eq1, eq2

    # Patrón 2: "Will [Equipo A] beat [Equipo B]..."
    match_beat = re.search(
        r"will\s+(?:the\s+)?([A-Za-z0-9\s\.\-]+?)\s+(?:beat|defeat)\s+(?:the\s+)?([A-Za-z0-9\s\.\-]+?)(?:\s+in|\s+on|\?|$)",
        q,
        flags=re.IGNORECASE,
    )
    if match_beat:
        eq1 = match_beat.group(1).strip()
        eq2 = match_beat.group(2).strip()
        return f"{eq1} vs {eq2}", eq1, eq2

    return "", "", ""


def extraer_manifold(limite_por_termino: int = 25) -> List[Dict[str, Any]]:
    """
    Consulta Manifold API v0 por términos deportivos, descarta preguntas no deportivas o props
    exóticos (ej. 'even or odd score', 'before 2030') y devuelve mercados binarios de partido.
    """
    filas_normalizadas: List[Dict[str, Any]] = []
    ids_vistos = set()
    ahora_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    # Solo considerar mercados que cierren dentro de los próximos 60 días (evita futuros a largo plazo como 2030/2040)
    max_cierre_ms = ahora_ms + (60 * 86400 * 1000)

    for termino, deporte_es, liga_es in TERMINOS_DEPORTIVOS:
        parametros = {
            "term": termino,
            "filter": "open",
            "contractType": "BINARY",
            "sort": "liquidity",
            "limit": str(limite_por_termino),
        }
        try:
            resp = requests.get(URL_MANIFOLD_SEARCH, params=parametros, timeout=10)
            if resp.status_code != 200:
                continue
            mercados = resp.json()
            if not isinstance(mercados, list):
                continue
        except Exception as exc:
            logger.warning("Error consultando Manifold para '%s': %s", termino, exc)
            continue

        for m in mercados:
            mid = m.get("id")
            if not mid or mid in ids_vistos:
                continue
            ids_vistos.add(mid)

            if m.get("isResolved"):
                continue

            close_ts = m.get("closeTime")
            if close_ts and (int(close_ts) < ahora_ms or int(close_ts) > max_cierre_ms):
                continue

            pregunta = str(m.get("question") or "")
            q_low = pregunta.lower()
            # Descartar props de par/impar, carreras anuales, o preguntas ajenas
            if any(
                ruido in q_low
                for ruido in ("even or odd", "ever happen", "series", "championship", "mvp", "playoffs", "draft")
            ):
                continue

            evento_limpio, lado_1, lado_2 = _parsear_equipos_pregunta_manifold(pregunta)
            if not evento_limpio:
                continue

            prob = float(m.get("probability") or 0.0)
            if not (0.02 < prob < 0.98):
                continue

            # Aplicamos un pequeño spread implícito del AMM de 1% por lado para representar precio Taker
            p1_taker = min(0.99, prob * 1.01)
            p2_taker = min(0.99, (1.0 - prob) * 1.01)
            cuota_1 = round(1.0 / p1_taker, 4)
            cuota_2 = round(1.0 / p2_taker, 4)

            liq = round(float(m.get("totalLiquidity") or 0.0) / 2.0, 2)
            inicio_utc = ""
            if close_ts:
                inicio_utc = datetime.fromtimestamp(int(close_ts) / 1000.0, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )

            filas_normalizadas.append(
                {
                    "Plataforma": "Manifold",
                    "Deporte": deporte_es,
                    "Liga": liga_es,
                    "Evento": evento_limpio,
                    "Inicio_UTC": inicio_utc,
                    "Tipo_Mercado": "Ganador (Moneyline)",
                    "Linea": "N/A",
                    "Lado_1": lado_1,
                    "Cuota_Taker_1": cuota_1,
                    "Liquidez_1_USD": liq,
                    "Lado_2": lado_2,
                    "Cuota_Taker_2": cuota_2,
                    "Liquidez_2_USD": liq,
                    "Overround_Libro_Pct": calcular_overround_pct(cuota_1, cuota_2),
                    "ID_Mercado": f"mnf_{mid}",
                }
            )

    return filas_normalizadas


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    datos = extraer_manifold()
    print(f"Total mercados extraídos de Manifold: {len(datos)}")
    for muestra in datos[:10]:
        print(muestra)
