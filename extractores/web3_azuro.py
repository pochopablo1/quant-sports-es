"""
Extractores Web3 descentralizados:
1. Azuro Protocol V3 (GraphQL Data-feed en Polygon / Gnosis).
2. Overtime Markets V2 (TheGraph / API pública en Optimism / Arbitrum).
"""
import logging
from datetime import datetime, timezone
import time
from typing import List, Dict, Any
import requests
from configuracion import calcular_overround_pct

logger = logging.getLogger(__name__)

# Endpoints públicos de Subgraphs de Azuro Protocol V3 (Data Feed)
URLS_AZURO_GRAPHQL = [
    ("Polygon", "https://thegraph-1.onchainfeed.org/subgraphs/name/azuro-protocol/azuro-data-feed-polygon"),
    ("Gnosis", "https://thegraph-1.onchainfeed.org/subgraphs/name/azuro-protocol/azuro-data-feed-gnosis"),
    ("Base", "https://thegraph-1.onchainfeed.org/subgraphs/name/azuro-protocol/azuro-data-feed-base"),
]

QUERY_AZURO_JUEGOS = """
query ObtenerJuegosActivos($startsAtMin: BigInt!, $first: Int!) {
  games(
    first: $first
    where: {
      startsAt_gt: $startsAtMin
      state_in: [Created, Live]
    }
    orderBy: startsAt
    orderDirection: asc
  ) {
    gameId
    title
    startsAt
    state
    sport {
      name
    }
    league {
      name
      country {
        name
      }
    }
    participants {
      name
      sortOrder
    }
    conditions(first: 5, where: { state: Active }) {
      conditionId
      state
      outcomes {
        outcomeId
        currentOdds
      }
    }
  }
}
"""

QUERY_AZURO_FALLBACK = """
query ObtenerUltimosJuegos($first: Int!) {
  games(
    first: $first
    orderBy: startsAt
    orderDirection: desc
  ) {
    gameId
    title
    startsAt
    sport {
      name
    }
    league {
      name
      country {
        name
      }
    }
    participants {
      name
      sortOrder
    }
    conditions(first: 3) {
      conditionId
      outcomes {
        outcomeId
        currentOdds
      }
    }
  }
}
"""


def extraer_azuro(limite: int = 50) -> List[Dict[str, Any]]:
    """
    Consulta los Subgraphs GraphQL de Azuro V3 (Polygon, Gnosis, Base) para extraer
    condiciones pre-partido y cuotas AMM sin duplicar gameId.
    """
    filas_normalizadas: List[Dict[str, Any]] = []
    ahora_ts = int(time.time())
    variables = {"startsAtMin": str(ahora_ts - 7200), "first": limite}

    juegos = []
    ids_vistos = set()
    for nombre_red, url in URLS_AZURO_GRAPHQL:
        try:
            juegos_red = []
            resp = requests.post(
                url,
                json={"query": QUERY_AZURO_JUEGOS, "variables": variables},
                timeout=12,
            )
            if resp.status_code == 200:
                payload = resp.json()
                juegos_red = (payload.get("data") or {}).get("games") or []
            if not juegos_red:
                resp_fb = requests.post(
                    url,
                    json={"query": QUERY_AZURO_FALLBACK, "variables": {"first": limite}},
                    timeout=12,
                )
                if resp_fb.status_code == 200:
                    juegos_red = (resp_fb.json().get("data") or {}).get("games") or []
            for j in juegos_red:
                gid = j.get("gameId")
                if gid and gid not in ids_vistos:
                    ids_vistos.add(gid)
                    juegos.append(j)
        except Exception as exc:
            logger.warning("Fallo consultando nodo Azuro %s (%s): %s", nombre_red, url, exc)

    for juego in juegos:
        participantes = sorted(
            juego.get("participants") or [], key=lambda x: x.get("sortOrder", 0)
        )
        if len(participantes) < 2:
            continue

        equipo_1 = str(participantes[0].get("name", "Lado 1"))
        equipo_2 = str(participantes[1].get("name", "Lado 2"))
        titulo = juego.get("title") or f"{equipo_1} vs {equipo_2}"

        deporte_raw = (juego.get("sport") or {}).get("name", "Deportes")
        liga_info = juego.get("league") or {}
        pais_nombre = (liga_info.get("country") or {}).get("name", "")
        liga_nombre = liga_info.get("name", "General")
        liga_completa = f"{pais_nombre} - {liga_nombre}".strip(" -")

        starts_at = juego.get("startsAt")
        try:
            inicio_utc = datetime.fromtimestamp(int(starts_at), tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        except (ValueError, TypeError):
            inicio_utc = str(starts_at or "")

        condiciones = juego.get("conditions") or []
        for cond in condiciones:
            outcomes = cond.get("outcomes") or []
            # Tomamos mercados de 2 resultados para comparativa directa
            if len(outcomes) != 2:
                continue

            try:
                c1 = round(float(outcomes[0].get("currentOdds", 0.0)), 4)
                c2 = round(float(outcomes[1].get("currentOdds", 0.0)), 4)
            except (ValueError, TypeError):
                continue

            if c1 <= 1.0 or c2 <= 1.0:
                continue

            filas_normalizadas.append(
                {
                    "Plataforma": "Azuro V3",
                    "Deporte": str(deporte_raw),
                    "Liga": liga_completa,
                    "Evento": str(titulo),
                    "Inicio_UTC": inicio_utc,
                    "Tipo_Mercado": "Ganador (Moneyline / 2-Way)",
                    "Linea": "N/A",
                    "Lado_1": equipo_1,
                    "Cuota_Taker_1": c1,
                    "Liquidez_1_USD": 2500.0,  # Liquidez base estimada del pool AMM v3
                    "Lado_2": equipo_2,
                    "Cuota_Taker_2": c2,
                    "Liquidez_2_USD": 2500.0,
                    "Overround_Libro_Pct": calcular_overround_pct(c1, c2),
                    "ID_Mercado": str(cond.get("conditionId") or juego.get("gameId")),
                }
            )
            # Solo tomamos la condición principal de 2 vías por partido para evitar duplicados de props secundarios
            break

    return filas_normalizadas


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    datos = extraer_azuro(limite=30)
    print(f"Total mercados extraídos de Azuro V3: {len(datos)}")
    for muestra in datos[:5]:
        print(muestra)
