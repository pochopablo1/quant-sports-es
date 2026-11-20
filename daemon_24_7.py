"""
Daemon Autónomo 24/7 EXCLUSIVO DE SUREBETS Y ARBITRAJE EN VIVO (`daemon_24_7.py`).
==================================================================================
Configurado exactamente según el pedido del usuario:
  1. Escanea todas las casas de apuestas (Polymarket, SX Bet V3, Kalshi, Limitless, Overtime, Vegas Live)
     cada 1 MINUTO (`--intervalo-minutos 1` por defecto) buscando:
       • Surebets En Vivo (Motor E In-Play en partidos jugándose ahora mismo).
       • Surebets Puras de 2 Patas (Motor B Taker-Taker y Motor C Maker-Taker).
       • Pasillos / Middles de Riesgo Cero (Motor D) y Triángulos 1X2 (Motor A).
  2. Si ejecuta una Surebet real en el ciclo, envía una alerta instantánea a Telegram.
  3. Envía ÚNICAMENTE el Reporte Consolidado de Surebets cada 2 HORAS (`--intervalo-reporte-horas 2.0`).
     (Eliminados por completo los reportes viejos del bot de favoritos).
"""
import argparse
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
import sys
import time
from typing import Dict, Any, List
import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RUTA_BASE = Path(__file__).resolve().parent
RUTA_SPORTS = RUTA_BASE.parent / "quant_sports_es"
if str(RUTA_BASE) not in sys.path:
    sys.path.insert(0, str(RUTA_BASE))
if RUTA_SPORTS.exists() and str(RUTA_SPORTS) not in sys.path:
    sys.path.append(str(RUTA_SPORTS))

from configuracion import (
    DIRECTORIO_DATOS,
    TELEGRAM_TOKEN,
    CHAT_ID,
    STAKE_TOTAL_SUREBET_USD,
)
from extractores.multi_exchange import extraer_todas_las_plataformas_en_paralelo
from motores.motor_surebets import (
    ejecutar_motor_a_intra_exchange,
    ejecutar_motores_cross_exchange,
    ejecutar_motor_e_inplay_en_vivo,
)
from ejecutor.bot_surebets import ejecutar_oportunidades_surebets
from ejecutor.gestor_wallet import verificar_estado_wallet

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("DaemonSurebets24_7")


def enviar_mensaje_telegram(texto: str) -> bool:
    """Envía un mensaje Markdown a Telegram usando TELEGRAM_TOKEN y CHAT_ID de .env."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.warning("Falta TELEGRAM_TOKEN o CHAT_ID en .env; no se envió mensaje a Telegram.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": CHAT_ID, "text": texto, "parse_mode": "Markdown"},
            timeout=12,
        )
        if resp.status_code != 200:
            # Reintentar en texto plano si algún nombre de equipo tiene caracteres especiales de Markdown
            resp = requests.post(
                url,
                json={"chat_id": CHAT_ID, "text": texto.replace("*", "").replace("`", "")},
                timeout=12,
            )
        return resp.status_code == 200
    except Exception as exc:
        logger.error("Error enviando Telegram: %s", exc)
        return False


TZ_ARG = timezone(timedelta(hours=-3))
_DIAS_ES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def _obtener_horario_arg_evento(event_slug: str, slug_mkt: str) -> str:
    """Consulta la fecha/hora exacta de inicio del partido en Gamma API y la devuelve en Hora Argentina (UTC-3)."""
    from normalizador.emparejador import parsear_datetime_utc

    dt_utc = None
    for url, valor in [
        ("https://gamma-api.polymarket.com/events", event_slug),
        ("https://gamma-api.polymarket.com/markets", slug_mkt),
    ]:
        if not valor:
            continue
        try:
            r = requests.get(url, params={"slug": valor}, timeout=5)
            if r.status_code == 200 and r.json():
                item = r.json()[0]
                mkts = item.get("markets") or [item]
                raw_dt = (
                    mkts[0].get("gameStartTime")
                    or item.get("startTime")
                    or item.get("startDate")
                    or item.get("endDate")
                )
                dt_utc = parsear_datetime_utc(raw_dt)
                if dt_utc:
                    break
        except Exception:
            pass

    if not dt_utc:
        return "Horario a confirmar"

    ahora_utc = datetime.now(tz=timezone.utc)
    dif_min = (ahora_utc - dt_utc).total_seconds() / 60.0
    dt_arg = dt_utc.astimezone(TZ_ARG)
    ahora_arg = ahora_utc.astimezone(TZ_ARG)

    if -5.0 <= dif_min <= 180.0:
        return f"🟢 EN VIVO AHORA ({dt_arg.strftime('%H:%M')} hs ARG)"
    if dt_arg.date() == ahora_arg.date():
        return f"HOY {dt_arg.strftime('%H:%M')} hs ARG"
    if dt_arg.date() == (ahora_arg + timedelta(days=1)).date():
        return f"MAÑANA {dt_arg.strftime('%H:%M')} hs ARG"
    dia_sem = _DIAS_ES[dt_arg.weekday()]
    return f"{dia_sem} {dt_arg.strftime('%d/%m %H:%M')} hs ARG"


def construir_reporte_surebets_2_horas(
    ciclos_en_ventana: int,
    total_mercados: int,
    surebets_taker: List[Dict[str, Any]],
    arbs_maker_taker: List[Dict[str, Any]],
    pasillos_middles: List[Dict[str, Any]],
    cruces_inplay: List[Dict[str, Any]],
    ejecutadas_ventana: List[Dict[str, Any]],
    mejores_inplay_ventana: List[Dict[str, Any]],
) -> str:
    ahora_arg_str = datetime.now(tz=TZ_ARG).strftime("%d/%m %H:%M hs ARG")
    est_w = verificar_estado_wallet()
    pusd_poly = float(est_w.get("polygon_pusd_polymarket", 0.0))
    usdc_sx = float(est_w.get("sx_usdc_sxbet", 0.0))
    usdc_base = float(est_w.get("base_usdc_limitless", 0.0))
    usdc_poly = float(est_w.get("polygon_usdc_nativo", 0.0))
    total_liquido = round(pusd_poly + usdc_sx + usdc_base + usdc_poly, 2)

    # Consultar posiciones abiertas reales en Polymarket V2 y su horario en Argentina
    abiertas_poly = []
    valor_en_juego_usd = 0.0
    priv_key = os.getenv("BOT_WALLET_PRIVATE_KEY", "").strip()
    if priv_key:
        try:
            from polymarket import SecureClient

            sc = SecureClient._create(private_key=priv_key, wallet=None)
            try:
                for p in sc.list_positions().first_page().items:
                    st = str(p.status.value if hasattr(p.status, "value") else p.status)
                    if st == "OPEN":
                        costo = round(float(p.total_cost_usdc), 2)
                        val_act = round(float(p.current_value), 2)
                        shares = round(float(p.current_size), 2)
                        p_ent = round(float(p.avg_price), 2)
                        valor_en_juego_usd += val_act
                        ev_slug = str(getattr(p, "event_slug", "") or "")
                        mkt_slug = str(getattr(p, "slug", "") or "")
                        horario_arg = _obtener_horario_arg_evento(ev_slug, mkt_slug)
                        abiertas_poly.append({
                            "titulo": str(p.title),
                            "seleccion": str(p.outcome),
                            "contratos": shares,
                            "precio_entrada": p_ent,
                            "costo_usd": costo,
                            "valor_actual_usd": val_act,
                            "cobro_si_gana_usd": shares,
                            "horario_arg": horario_arg,
                        })
            finally:
                sc.close()
        except Exception as exc:
            logger.debug("Aviso leyendo posiciones abiertas para reporte: %s", exc)

    valor_en_juego_usd = round(valor_en_juego_usd, 2)
    patrimonio_total_usd = round(total_liquido + valor_en_juego_usd, 2)

    lineas = [
        f"📊 *ESTADO DE BILLETERAS Y APUESTAS ({ahora_arg_str})*",
        "",
        f"💼 *PATRIMONIO TOTAL:* `${patrimonio_total_usd:.2f} USD`",
        f"  • Efectivo Libre Polymarket (`pUSD`): `${pusd_poly:.2f} USD`",
        f"  • Efectivo Libre SX Bet (`USDC`): `${usdc_sx:.2f} USD`",
        f"  • Efectivo Libre Base L2 (`USDC`): `${usdc_base:.2f} USD`",
        f"  • Capital en Juego Ahora ({len(abiertas_poly)} patas): `${valor_en_juego_usd:.2f} USD`",
        "",
    ]

    if abiertas_poly:
        lineas.append(f"⏳ *APUESTAS ACTIVAS ({len(abiertas_poly)} patas abiertas):*")
        for ap in abiertas_poly:
            lineas.append(
                f"  • *{ap['titulo']}* ➡️ `{ap['seleccion']}`\n"
                f"    🕒 *Cuándo juega:* `{ap['horario_arg']}`\n"
                f"    💵 Invertido: `${ap['costo_usd']:.2f}` (`@{ap['precio_entrada']:.2f}`) | Valor hoy: `${ap['valor_actual_usd']:.2f}` | Cobrás si gana: `${ap['cobro_si_gana_usd']:.2f} USD`"
            )
    else:
        lineas.append("⏳ *APUESTAS ACTIVAS:* `Ninguna abierta en este momento` (100% efectivo libre)")

    lineas.append("")
    lineas.append(f"⏱️ _Escáner activo: {ciclos_en_ventana} ciclos de 1 min ({total_mercados} mercados/min)_")
    return "\n".join(lineas)


def iniciar_daemon_surebets(
    intervalo_minutos: float = 1.0,
    intervalo_reporte_horas: float = 2.0,
    max_ciclos: int = 0,
    stake_por_pata_usd: float = 4.5,
) -> None:
    segundos_espera = max(15.0, float(intervalo_minutos) * 60.0)
    segundos_reporte = max(300.0, float(intervalo_reporte_horas) * 3600.0)

    ultimo_reporte_ts = 0.0
    ciclo_global = 0
    ciclos_en_ventana = 0
    ejecutadas_ventana: List[Dict[str, Any]] = []
    mejores_inplay_ventana: Dict[str, Dict[str, Any]] = {}

    logger.info(
        "🚀 Iniciando Daemon EXCLUSIVO DE SUREBETS 24/7 | Escaneo cada %.1f min | Reporte Telegram cada %.1f horas",
        intervalo_minutos,
        intervalo_reporte_horas,
    )

    while True:
        ciclo_global += 1
        ciclos_en_ventana += 1
        t_inicio = time.time()

        try:
            datos = extraer_todas_las_plataformas_en_paralelo()
            mercados_norm = datos["mercados_normalizados"]
            triangulos_1x2 = datos["triangulos_1x2"]

            res_motor_a = ejecutar_motor_a_intra_exchange(triangulos_1x2)
            res_cross = ejecutar_motores_cross_exchange(mercados_norm)
            res_inplay = ejecutar_motor_e_inplay_en_vivo(mercados_norm)

            surebets_taker = res_cross["surebets_taker"]
            arbs_maker_taker = res_cross["arbs_maker_taker"]
            pasillos_middles = res_cross["pasillos_middles"]
            cruces_inplay = res_inplay["cruces_inplay"]

            # Guardar los mejores cruces In-Play vistos durante la ventana de 2 horas
            for ip in cruces_inplay:
                ev_k = str(ip.get("Evento", ""))
                prev = mejores_inplay_ventana.get(ev_k)
                if not prev or float(ip.get("ROI_OnChain_0Bps_Pct", -99)) > float(prev.get("ROI_OnChain_0Bps_Pct", -99)):
                    mejores_inplay_ventana[ev_k] = ip

            # Evaluar y ejecutar Surebets accionables
            nuevas_ej = ejecutar_oportunidades_surebets(
                surebets_taker=surebets_taker,
                arbs_maker_taker=arbs_maker_taker,
                pasillos_middles=pasillos_middles,
                cruces_inplay=cruces_inplay,
                triangulos_1x2=res_motor_a,
                stake_por_pata_usd=stake_por_pata_usd,
            )

            if nuevas_ej:
                ejecutadas_ventana.extend(nuevas_ej)
                lineas_alerta = [f"🚨 *¡SUREBET / ARBITRAJE DETECTADO Y EJECUTADO! ({len(nuevas_ej)})*"]
                for ej in nuevas_ej:
                    lineas_alerta.append(
                        f"• *{ej['Evento']}* (`{ej['Tipo_Estrategia']}`)\n"
                        f"  Pata 1: `{ej['Pata_1']}`\n"
                        f"  Pata 2: `{ej['Pata_2']}`\n"
                        f"  ROI Neto: `{ej['ROI_Esperado_Pct']:+.2f}%` | Stake: `${ej['Stake_Por_Pata_USD']:.2f} USD`\n"
                        f"  Estado: `{ej['Estado_Ejecucion']}`"
                    )
                enviar_mensaje_telegram("\n".join(lineas_alerta))

            duracion_seg = time.time() - t_inicio
            logger.info(
                "Ciclo #%d completado en %.1fs | Mercados: %d | InPlay: %d cruces | Surebets: %d | MakerTaker: %d | Pasillos: %d | Ejecutadas hoy: %d",
                ciclo_global,
                duracion_seg,
                len(mercados_norm),
                len(cruces_inplay),
                len(surebets_taker),
                len(arbs_maker_taker),
                len(pasillos_middles),
                len(nuevas_ej),
            )

            # Enviar el Reporte de Surebets en el Ciclo #1 (confirmación de arranque) y luego cada 2 horas exactas
            ahora_ts = time.time()
            if ultimo_reporte_ts == 0.0 or (ahora_ts - ultimo_reporte_ts) >= segundos_reporte:
                top_ip_lista = sorted(
                    mejores_inplay_ventana.values(),
                    key=lambda x: float(x.get("ROI_OnChain_0Bps_Pct", -99.0)),
                    reverse=True,
                )
                texto_rep = construir_reporte_surebets_2_horas(
                    ciclos_en_ventana=ciclos_en_ventana,
                    total_mercados=len(mercados_norm),
                    surebets_taker=surebets_taker,
                    arbs_maker_taker=arbs_maker_taker,
                    pasillos_middles=pasillos_middles,
                    cruces_inplay=cruces_inplay,
                    ejecutadas_ventana=ejecutadas_ventana,
                    mejores_inplay_ventana=top_ip_lista,
                )
                ok_tg = enviar_mensaje_telegram(texto_rep)
                logger.info("📲 Reporte Surebets (cada 2h) enviado a Telegram: %s", ok_tg)
                ultimo_reporte_ts = ahora_ts
                ciclos_en_ventana = 0
                ejecutadas_ventana.clear()
                mejores_inplay_ventana.clear()

        except Exception as exc:
            logger.error("Error en ciclo #%d del Daemon Surebets: %s", ciclo_global, exc)

        if max_ciclos > 0 and ciclo_global >= max_ciclos:
            logger.info("Se alcanzó max_ciclos=%d. Finalizando daemon.", max_ciclos)
            break

        transcurrido = time.time() - t_inicio
        pausa = max(5.0, segundos_espera - transcurrido)
        time.sleep(pausa)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daemon 24/7 Exclusivo de Surebets (Escaneo 1 min / Reporte 2h)")
    parser.add_argument(
        "--intervalo-minutos",
        type=float,
        default=1.0,
        help="Minutos entre cada escaneo de Surebets en vivo (default: 1.0 minuto)",
    )
    parser.add_argument(
        "--intervalo-reporte-horas",
        type=float,
        default=2.0,
        help="Horas entre cada reporte consolidado en Telegram (default: 2.0 horas)",
    )
    parser.add_argument(
        "--max-ciclos",
        type=int,
        default=0,
        help="Cantidad máxima de ciclos a ejecutar (0 = infinito 24/7)",
    )
    parser.add_argument(
        "--stake-usd",
        type=float,
        default=4.5,
        help="Stake en USD por pata de Surebet (default: $4.50 USD)",
    )
    args = parser.parse_args()
    iniciar_daemon_surebets(
        intervalo_minutos=args.intervalo_minutos,
        intervalo_reporte_horas=args.intervalo_reporte_horas,
        max_ciclos=args.max_ciclos,
        stake_por_pata_usd=args.stake_usd,
    )
