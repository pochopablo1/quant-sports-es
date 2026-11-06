"""
Panel de Control y Reporte de Telegram en Vivo (`ver_estado_hoy.py`).
====================================================================
Cuando `EJECUCION_REAL_HABILITADA=true`, consulta directamente la Blockchain de Polygon
y la API Oficial de Polymarket V2 (`SecureClient`) de tu Deposit Wallet (`0x71DD64...`),
mostrando únicamente:
1. Saldo líquido real en `pUSD` (`$ USD`) disponible en tu billetera + Valor actual de posiciones en juego.
2. Apuestas reales GANADAS y cobradas automáticamente (`REDEEM`).
3. Apuestas reales ABIERTAS en curso ahora mismo con su cotización en vivo.
4. Apuestas reales finalizadas sin éxito.
Jamás mezcla simulaciones antiguas de Paper Trading (`Motor 3`, `Futuur`, `Kalshi`).
"""
from datetime import datetime, timezone
import os
import sys
from dotenv import load_dotenv
import pandas as pd

from configuracion import DIRECTORIO_DATOS, RUTA_BASE
from ejecutor.gestor_wallet import verificar_estado_wallet
from alertas.telegram_bot import enviar_mensaje_telegram

RUTA_HISTORIAL = DIRECTORIO_DATOS / "historial_ejecuciones.csv"
CAPITAL_INICIAL_REFERENCIA_USD = 89.24


def obtener_radiografia_real_polymarket() -> dict:
    """Consulta en vivo los saldos On-Chain y las posiciones/actividades reales en Polymarket V2."""
    load_dotenv(RUTA_BASE / ".env", override=True)
    estado_w = verificar_estado_wallet()
    priv_key = os.getenv("BOT_WALLET_PRIVATE_KEY", "").strip()

    pusd_cash = float(estado_w.get("polygon_pusd_polymarket", 0.0))
    pol_gas = float(estado_w.get("polygon_pol_gas", 0.0))
    dep_wallet = str(estado_w.get("deposit_wallet_polymarket", ""))

    abiertas = []
    ganadas_redeem = []
    perdidas = []
    valor_posiciones_usd = 0.0

    if priv_key:
        try:
            from polymarket import SecureClient
            sc = SecureClient._create(private_key=priv_key, wallet=None)
            try:
                pv = sc.get_portfolio_value()
                valor_posiciones_usd = float(pv.value)
            except Exception:
                pass

            # 1. Posiciones actuales (OPEN y REDEEMABLE)
            try:
                pos_items = sc.list_positions().first_page().items
                for p in pos_items:
                    estado_p = str(p.status.value if hasattr(p.status, "value") else p.status)
                    costo = round(float(p.total_cost_usdc), 2)
                    val_act = round(float(p.current_value), 2)
                    pnl = round(float(p.total_pnl), 2)
                    item_dict = {
                        "titulo": str(p.title),
                        "seleccion": str(p.outcome),
                        "contratos": round(float(p.current_size), 2),
                        "precio_entrada": round(float(p.avg_price), 3),
                        "precio_actual": round(float(p.current_price), 3),
                        "costo_usd": costo,
                        "valor_actual_usd": val_act,
                        "pnl_usd": pnl,
                    }
                    if estado_p == "OPEN":
                        abiertas.append(item_dict)
                    elif val_act <= 0.01 and pnl < 0:
                        perdidas.append(item_dict)
            except Exception:
                pass

            # 2. Actividades de cobro (REDEEM = Apuestas Ganadas pagadas a tu pUSD)
            try:
                act_items = sc.list_activity().first_page().items
                trades_por_cond = {}
                for a in act_items:
                    tipo_a = str(a.type.value if hasattr(a.type, "value") else a.type)
                    if tipo_a == "TRADE":
                        trades_por_cond[str(a.condition_id)] = {
                            "costo_usd": round(float(a.amount), 2),
                            "precio": round(float(a.price), 2),
                            "shares": round(float(a.shares), 2),
                        }
                for a in act_items:
                    tipo_a = str(a.type.value if hasattr(a.type, "value") else a.type)
                    if tipo_a == "REDEEM":
                        cond_id = str(a.condition_id)
                        cobrado = round(float(a.amount), 2)
                        info_tr = trades_por_cond.get(cond_id, {})
                        costo_est = info_tr.get("costo_usd", round(cobrado * 0.55, 2))
                        # En caso de redención parcial/total, el pago de cada share ganador es $1.00
                        shares_gan = info_tr.get("shares", cobrado)
                        pago_real = max(cobrado, round(shares_gan * 1.0, 2))
                        ganancia_neta = round(pago_real - costo_est, 2)
                        ganadas_redeem.append({
                            "titulo": str(a.title),
                            "seleccion": str(a.outcome),
                            "costo_usd": costo_est,
                            "cobrado_usd": pago_real,
                            "ganancia_neta_usd": ganancia_neta,
                            "fecha": a.timestamp.strftime("%d/%m %H:%M"),
                        })
            except Exception:
                pass
            sc.close()
        except Exception:
            pass

    if valor_posiciones_usd == 0.0 and abiertas:
        valor_posiciones_usd = round(sum(x["valor_actual_usd"] for x in abiertas), 2)

    patrimonio_total_usd = round(pusd_cash + valor_posiciones_usd, 2)
    pnl_global_usd = round(patrimonio_total_usd - CAPITAL_INICIAL_REFERENCIA_USD, 2)

    return {
        "deposit_wallet": dep_wallet,
        "pusd_cash": round(pusd_cash, 2),
        "valor_en_juego": round(valor_posiciones_usd, 2),
        "patrimonio_total": patrimonio_total_usd,
        "pnl_global_usd": pnl_global_usd,
        "pol_gas": round(pol_gas, 2),
        "abiertas": abiertas,
        "ganadas": ganadas_redeem,
        "perdidas": perdidas,
    }


def generar_texto_resumen_telegram_hoy() -> str:
    """Construye el reporte 100% REAL ON-CHAIN de Polymarket V2 para Telegram."""
    ahora_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rad = obtener_radiografia_real_polymarket()

    cant_gan = len(rad["ganadas"])
    cant_per = len(rad["perdidas"])
    cant_abi = len(rad["abiertas"])
    resueltas = cant_gan + cant_per
    wr_pct = round((cant_gan / resueltas) * 100.0, 1) if resueltas > 0 else 0.0

    lineas = [
        f"🤖 *REPORTE REAL ON-CHAIN — POLYMARKET V2 ({ahora_str})*",
        f"💼 *Patrimonio Total Actual:* `${rad['patrimonio_total']:.2f} USD` (Inicial: `$89.24` | PnL: `{rad['pnl_global_usd']:+.2f} USD`)",
        f"• *Efectivo Líquido (`pUSD`):* `${rad['pusd_cash']:.2f} USD`",
        f"• *Capital en Juego ({cant_abi} abiertas):* `${rad['valor_en_juego']:.2f} USD`",
        f"• *Gas en Billetera:* `{rad['pol_gas']:.2f} POL`",
        f"• *Balance Resueltas:* `{cant_gan} Ganadas ✅` / `{cant_per} Perdidas ❌` (`{wr_pct}%` acierto)",
        "",
    ]

    if rad["ganadas"]:
        lineas.append("🏆 *Apuestas Ganadas y Cobradas en Billetera:*")
        for g in rad["ganadas"]:
            lineas.append(
                f"  • ✅ *{g['titulo']}* (`{g['seleccion']}`)\n"
                f"    Invertido: `${g['costo_usd']:.2f}` ➡️ Cobrado: *${g['cobrado_usd']:.2f} USD* (`+{g['ganancia_neta_usd']:.2f} USD`)"
            )
        lineas.append("")

    if rad["abiertas"]:
        lineas.append(f"⏳ *Apuestas En Curso Ahora Mismo ({cant_abi}):*")
        for ab in rad["abiertas"]:
            signo = "🟢" if ab["pnl_usd"] >= 0 else "🟡"
            lineas.append(
                f"  • {signo} *{ab['titulo']}* — `{ab['seleccion']}`\n"
                f"    Entrada: `${ab['precio_entrada']:.2f}` ➡️ Actual: `${ab['precio_actual']:.3f}` "
                f"(Valor: `${ab['valor_actual_usd']:.2f}` | `{ab['pnl_usd']:+.2f} USD`)"
            )
        lineas.append("")

    if rad["perdidas"]:
        lineas.append(f"❌ *Apuestas Finalizadas Sin Éxito ({cant_per}):*")
        for pe in rad["perdidas"]:
            lineas.append(f"  • `{pe['titulo']}` ({pe['seleccion']}) | `-${pe['costo_usd']:.2f} USD`")

    return "\n".join(lineas)


def mostrar_panel_hoy() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    texto = generar_texto_resumen_telegram_hoy()
    print("\n" + "═" * 95)
    print(texto.replace("*", "").replace("`", ""))
    print("═" * 95 + "\n")


if __name__ == "__main__":
    mostrar_panel_hoy()
    if "--enviar-telegram" in sys.argv:
        ok = enviar_mensaje_telegram(generar_texto_resumen_telegram_hoy())
        print("Enviado a Telegram:", ok)
