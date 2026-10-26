"""
Módulo de Alertas y Despacho de Reportes por Telegram.
Envía resúmenes ejecutivos en Markdown y el dataset CSV consolidado mediante `sendDocument`.
"""
import logging
from pathlib import Path
from typing import Dict, List, Any
import requests
from configuracion import TELEGRAM_TOKEN, CHAT_ID

logger = logging.getLogger(__name__)


def formatear_resumen_markdown(
    total_mercados: int,
    conteo_por_plataforma: Dict[str, int],
    oportunidades: Dict[str, List[Dict[str, Any]]],
) -> str:
    """
    Construye un mensaje conciso en español destacando el estado de extracción,
    arbitrajes (Surebets), Value Bets (+EV Taker) y oportunidades Maker ("Ser la Casa").
    """
    lineas = [
        "📊 *REPORTE CUANTITATIVO DE MERCADOS DEPORTIVOS*",
        f"Total de mercados normalizados: *{total_mercados}*",
        "",
        "🌐 *Desglose por Plataforma:*",
    ]
    for plat, cant in conteo_por_plataforma.items():
        lineas.append(f"  • {plat}: `{cant}` mercados")

    arbs = oportunidades.get("arbitrajes", [])
    vbs = oportunidades.get("value_bets", [])
    trads = oportunidades.get("trading_pre", [])
    mms = oportunidades.get("market_making", [])

    lineas.append("")
    lineas.append(f"🎯 *MOTOR 1 — Value en Favoritos (Cuota <= 2.10, EV >= 4%):* `{len(vbs)}`")
    for v in vbs[:5]:
        lineas.append(
            f"  • [{v['Plataforma']}] *{v['Evento']}* ({v.get('Tipo_Mercado', '')})\n"
            f"    Selección: `{v['Seleccion']}` @ *{v['Cuota_Taker']}* "
            f"(Prob: {v.get('Prob_Real_Pct', 50)}% | Justa: {v['Cuota_Justa_Pinnacle']}) ➡️ *EV: +{v['EV_Pct']}%* [Stake: ${v.get('Stake_Sugerido_USD', 10)}]"
        )

    lineas.append("")
    lineas.append(f"⚡ *MOTOR 2 — Surebets / Arbitraje Puro (ROI Neto >= 1.0%):* `{len(arbs)}`")
    for a in arbs[:5]:
        lineas.append(
            f"  • *{a['Evento']}* | ROI Neto: `+{a['ROI_Garantizado_Pct']}%` (Liq: ${a.get('Liquidez_Max_Arb_USD', 0):.0f})\n"
            f"    L1: {a['Lado_1']} | L2: {a['Lado_2']}"
        )

    lineas.append("")
    lineas.append(f"📈 *MOTOR 3 — Trading Pre-Partido CLOB (Comprar Ask -> Vender Maker Pre-Kickoff):* `{len(trads)}`")
    for t in trads[:5]:
        lineas.append(
            f"  • [{t['Plataforma']}] *{t['Evento']}* — `{t['Seleccion']}`\n"
            f"    Comprar @ `${t['Precio_Compra']:.3f}` ➡️ Vender Maker @ `${t['Precio_Venta_Maker']:.3f}` "
            f"(*+{t['ROI_Scalping_Pct']}% ROI* | Stake: ${t['Stake_USD']})"
        )

    lineas.append("")
    lineas.append(f"🏦 *Liquidez Pasiva (Market Making 2 Puntas):* `{len(mms)}` mercados elegibles")

    return "\n".join(lineas)


def enviar_mensaje_telegram(texto: str) -> bool:
    """Envía un mensaje de texto a Telegram."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.warning("Faltan TELEGRAM_TOKEN o CHAT_ID en .env")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": texto,
        "parse_mode": "Markdown",
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code != 200:
            # Si falla por algún caracter especial de Markdown, reintentar en texto plano
            payload.pop("parse_mode", None)
            resp = requests.post(url, json=payload, timeout=15)
        return resp.status_code == 200
    except Exception as exc:
        logger.error("Error enviando mensaje a Telegram: %s", exc)
        return False


def enviar_documento_telegram(ruta_csv: Path, comentario: str = "") -> bool:
    """Envía el archivo CSV consolidado (UTF-8-sig) al chat de Telegram usando sendDocument."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.warning("Faltan TELEGRAM_TOKEN o CHAT_ID en .env")
        return False

    if not ruta_csv.exists():
        logger.error("El archivo CSV no existe: %s", ruta_csv)
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument"
    try:
        with open(ruta_csv, "rb") as archivo:
            archivos = {"document": (ruta_csv.name, archivo, "text/csv")}
            datos = {"chat_id": CHAT_ID, "caption": comentario[:1024]}
            resp = requests.post(url, data=datos, files=archivos, timeout=30)
            if resp.status_code != 200:
                logger.error("Error de Telegram sendDocument: %s", resp.text)
            return resp.status_code == 200
    except Exception as exc:
        logger.error("Excepción enviando documento a Telegram: %s", exc)
        return False
