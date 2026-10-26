"""
Orquestador Principal del Motor Cuantitativo de Mercados Deportivos.
Modo ahorro de tokens activado por defecto (`usar_odds_api=False`, `enviar_telegram=False`):
- Permite auditar y cruzar mercados entre Polymarket, SX Bet y Azuro V3 sin gastar cuota de The-Odds-API,
  o reutilizar la caché local de Pinnacle ya guardada en el CSV/SQLite.
"""
import argparse
import logging
import sqlite3
import sys
from collections import Counter
from typing import List, Dict, Any
import pandas as pd

from configuracion import (
    COLUMNAS_ESQUEMA,
    DIRECTORIO_DATOS,
    RUTA_CSV_CONSOLIDADO,
    RUTA_SQLITE_DB,
)
from extractores.polymarket import extraer_polymarket
from extractores.sx_bet import extraer_sx_bet
from extractores.web3_azuro import extraer_azuro
from extractores.kalshi import extraer_kalshi
from extractores.limitless import extraer_limitless
from extractores.futuur import extraer_futuur
from extractores.manifold import extraer_manifold
from extractores.smarkets import extraer_smarkets
from extractores.pinnacle import extraer_pinnacle
from extractores.oraculo_gratis import extraer_oraculo_gratis_en_vivo
from normalizador.emparejador import normalizar_filas
from estrategias.motor_cuantitativo import detectar_oportunidades_cuantitativas
from alertas.telegram_bot import (
    formatear_resumen_markdown,
    enviar_mensaje_telegram,
    enviar_documento_telegram,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("OrquestadorCuantitativo")

RUTA_CSV_CRUCES = DIRECTORIO_DATOS / "auditoria_cruces_normalizados.csv"
RUTA_CSV_ACCIONABLES = DIRECTORIO_DATOS / "oportunidades_accionables.csv"


def cargar_cache_pinnacle() -> List[Dict[str, Any]]:
    """Carga los mercados de Pinnacle (`pin_`) desde el CSV local si existe, sin gastar tokens de The-Odds-API."""
    if not RUTA_CSV_CONSOLIDADO.exists():
        return []
    try:
        df_prev = pd.read_csv(RUTA_CSV_CONSOLIDADO)
        df_pin = df_prev[
            (df_prev["Plataforma"] == "Pinnacle")
            & (df_prev["ID_Mercado"].astype(str).str.startswith("pin_"))
        ].fillna("N/A")
        return df_pin.to_dict(orient="records")
    except Exception as exc:
        logger.warning("No se pudo leer caché local de Pinnacle: %s", exc)
        return []


def guardar_artefactos(
    filas: List[Dict[str, Any]],
    cruces: List[Dict[str, Any]],
    accionables: List[Dict[str, Any]],
) -> pd.DataFrame:
    """
    Guarda los datos consolidados en:
      1. CSV codificado en UTF-8-sig con las 15 columnas exactas requeridas.
      2. CSV de auditoría de cruces (`auditoria_cruces_normalizados.csv`).
      3. CSV de Oportunidades Accionables (`oportunidades_accionables.csv`) con filtro de liquidez, comisiones y Kelly.
      4. Base de datos SQLite (`mercados_deportivos.db`).
    """
    df = pd.DataFrame(filas)
    for col in COLUMNAS_ESQUEMA:
        if col not in df.columns:
            df[col] = ""
    df = df[COLUMNAS_ESQUEMA]

    df.to_csv(RUTA_CSV_CONSOLIDADO, index=False, encoding="utf-8-sig")
    logger.info("Archivo CSV consolidado generado en: %s", RUTA_CSV_CONSOLIDADO)

    if cruces:
        pd.DataFrame(cruces).to_csv(RUTA_CSV_CRUCES, index=False, encoding="utf-8-sig")
        logger.info("Archivo de auditoría de cruces generado en: %s", RUTA_CSV_CRUCES)

    if accionables:
        pd.DataFrame(accionables).to_csv(RUTA_CSV_ACCIONABLES, index=False, encoding="utf-8-sig")
        logger.info(
            "Archivo de OPORTUNIDADES ACCIONABLES (%d oportunidades) generado en: %s",
            len(accionables),
            RUTA_CSV_ACCIONABLES,
        )

    with sqlite3.connect(RUTA_SQLITE_DB) as conexion:
        df.to_sql("mercados_consolidados", conexion, if_exists="replace", index=False)
        if cruces:
            pd.DataFrame(cruces).to_sql("auditoria_cruces", conexion, if_exists="replace", index=False)
        if accionables:
            pd.DataFrame(accionables).to_sql("oportunidades_accionables", conexion, if_exists="replace", index=False)

    return df


def ejecutar_pipeline(
    enviar_telegram: bool = False,
    usar_odds_api_vivo: bool = False,
    usar_cache_local: bool = False,
) -> Dict[str, Any]:
    """
    Ejecuta el ciclo de extracción, normalización y análisis cuantitativo.
    - `enviar_telegram=False` por defecto (desactivado a pedido del usuario).
    - `usar_odds_api_vivo=False` por defecto (no consume tokens de The-Odds-API a menos que se pida explícitamente).
    """
    if usar_cache_local and RUTA_CSV_CONSOLIDADO.exists():
        logger.info("Cargando todos los mercados desde el CSV local para auditoría rápida (0 llamadas a APIs)...")
        df_local = pd.read_csv(RUTA_CSV_CONSOLIDADO).fillna("N/A")
        todos_crudos = df_local.to_dict(orient="records")
    else:
        logger.info(
            "Iniciando extracción en vivo de exchanges gratuitos (Polymarket, Kalshi, SX Bet, Limitless, Futuur, Manifold, Azuro V3, Smarkets)..."
        )
        mercados_poly = extraer_polymarket(limite=80)
        logger.info("Polymarket: %d mercados extraídos", len(mercados_poly))

        mercados_kalshi = extraer_kalshi()
        logger.info("Kalshi: %d mercados extraídos", len(mercados_kalshi))

        mercados_sx = extraer_sx_bet(tamano_pagina=100)
        logger.info("SX Bet: %d mercados extraídos", len(mercados_sx))

        mercados_limitless = extraer_limitless(max_paginas=6)
        logger.info("Limitless Exchange (Base L2): %d mercados extraídos", len(mercados_limitless))

        mercados_futuur = extraer_futuur(max_paginas=4)
        logger.info("Futuur (USDC): %d mercados extraídos", len(mercados_futuur))

        mercados_manifold = extraer_manifold(limite_por_termino=25)
        logger.info("Manifold Markets: %d mercados extraídos", len(mercados_manifold))

        mercados_azuro = extraer_azuro(limite=50)
        logger.info("Azuro V3 (Polygon/Gnosis/Base): %d mercados extraídos", len(mercados_azuro))

        mercados_smarkets = extraer_smarkets(limite_eventos=40)
        logger.info("Smarkets Exchange: %d mercados extraídos", len(mercados_smarkets))

        # Oráculo Gratuito Ilimitado en Tiempo Real (Action Network Consensus + ESPN/DraftKings -> 0 tokens)
        mercados_oraculo_gratis = extraer_oraculo_gratis_en_vivo()
        logger.info(
            "Oráculo Sharp Gratuito en Vivo (Action Network + ESPN/DraftKings): %d mercados extraídos (0 tokens)",
            len(mercados_oraculo_gratis),
        )

        if usar_odds_api_vivo:
            logger.info("Consultando The-Odds-API (Pinnacle) en vivo...")
            mercados_pinnacle = extraer_pinnacle(max_deportes=6) + mercados_oraculo_gratis
        else:
            mercados_pinnacle = mercados_oraculo_gratis + cargar_cache_pinnacle()
            logger.info(
                "Oráculo combinado listo: %d mercados de referencia en vivo (0 tokens gastados de The-Odds-API).",
                len(mercados_pinnacle),
            )

        todos_crudos = (
            mercados_poly
            + mercados_kalshi
            + mercados_sx
            + mercados_limitless
            + mercados_futuur
            + mercados_manifold
            + mercados_azuro
            + mercados_smarkets
            + mercados_pinnacle
        )

    todos_normalizados = normalizar_filas(todos_crudos)
    oportunidades = detectar_oportunidades_cuantitativas(todos_normalizados)
    cruces = oportunidades.get("cruces_verificados", [])
    accionables = oportunidades.get("oportunidades_accionables", [])

    df = guardar_artefactos(todos_normalizados, cruces, accionables)

    conteo = dict(Counter(m["Plataforma"] for m in todos_normalizados))
    resumen_md = formatear_resumen_markdown(
        total_mercados=len(todos_normalizados),
        conteo_por_plataforma=conteo,
        oportunidades=oportunidades,
    )

    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print("\n" + "=" * 75)
        print(resumen_md)
        print(f"\n🔍 Total de cruces exactos auditados: {len(cruces)}")
        print("=" * 75 + "\n")
    except Exception:
        pass

    envio_msg_ok = False
    envio_doc_ok = False
    if enviar_telegram and len(todos_normalizados) > 0:
        logger.info("Enviando resumen y archivo CSV consolidado a Telegram...")
        envio_msg_ok = enviar_mensaje_telegram(resumen_md)
        envio_doc_ok = enviar_documento_telegram(RUTA_CSV_CONSOLIDADO)

    return {
        "total_mercados": len(todos_normalizados),
        "conteo_plataformas": conteo,
        "oportunidades": oportunidades,
        "dataframe": df,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Motor Cuantitativo de Mercados Deportivos")
    parser.add_argument("--telegram", action="store_true", help="Habilitar envío a Telegram")
    parser.add_argument("--odds-api-vivo", action="store_true", help="Consultar The-Odds-API en vivo (gasta tokens)")
    parser.add_argument("--solo-local", action="store_true", help="Reprocesar únicamente el CSV local sin llamar a ninguna API")
    args = parser.parse_args()

    ejecutar_pipeline(
        enviar_telegram=args.telegram,
        usar_odds_api_vivo=args.odds_api_vivo,
        usar_cache_local=args.solo_local,
    )
