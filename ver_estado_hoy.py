"""
Panel de Control en Consola: `ver_estado_hoy.py`
Muestra en tiempo real el estado de rotación diaria del Daemon 24/7 ($200 USD/día en micro-apuestas de $2.50 a $6.00 USD):
1. Progreso hacia la meta diaria de $200.00 USD y ganancia matemática acumulada (+EV / ROI).
2. Desglose por cada uno de los 3 Motores (Favoritos <=2.10, Surebets >=1% y Trading Pre-Partido CLOB).
3. Desglose de capital requerido por plataforma (Polymarket, Limitless, SX Bet, Kalshi).
4. Listado detallado de todas las micro-apuestas ejecutadas hoy y las descartadas por el verificador de Orderbook.
"""
from datetime import datetime, timezone
import sys
import pandas as pd

from configuracion import DIRECTORIO_DATOS

RUTA_HISTORIAL = DIRECTORIO_DATOS / "historial_ejecuciones.csv"
META_DIARIA_USD = 200.0
META_GANANCIA_DIARIA_USD = 8.0  # 4% de $200 USD


def mostrar_panel_hoy() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    hoy_utc = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    ahora_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    print("\n" + "═" * 108)
    print(f"📊 PANEL DE CONTROL DIARIO — TRIPLE MOTOR CUANTITATIVO ({ahora_str})")
    print("═" * 108)

    if not RUTA_HISTORIAL.exists():
        print("⚠️ Todavía no existe `datos/historial_ejecuciones.csv`. El daemon está iniciando su primer barrido.")
        print("═" * 108 + "\n")
        return

    df = pd.read_csv(RUTA_HISTORIAL)
    if df.empty or "Timestamp_UTC" not in df.columns:
        print("⚠️ El historial de ejecuciones está vacío por ahora.")
        print("═" * 108 + "\n")
        return

    df_hoy = df[df["Timestamp_UTC"].astype(str).str.startswith(hoy_utc)].copy()
    if df_hoy.empty:
        print(f"⚠️ No hay registros para la fecha UTC {hoy_utc}.")
        print("═" * 108 + "\n")
        return

    mask_aprobadas = df_hoy["Estado_Orden"].astype(str).str.contains("OK|EJECUTAD|ACTIVO", na=False)
    df_ok = df_hoy[mask_aprobadas].copy()
    df_rechazadas = df_hoy[~mask_aprobadas].copy()

    df_ok["Ganancia_Esperada_USD"] = round(df_ok["Stake_USD"] * (df_ok["Ventaja_Viva_Pct"] / 100.0), 2)

    capital_rotado = float(df_ok["Stake_USD"].sum()) if not df_ok.empty else 0.0
    capital_restante = max(0.0, META_DIARIA_USD - capital_rotado)
    pct_meta_rotacion = min(100.0, (capital_rotado / META_DIARIA_USD) * 100.0)
    ganancia_esp_total = float(df_ok["Ganancia_Esperada_USD"].sum()) if not df_ok.empty else 0.0
    roi_promedio_pct = (ganancia_esp_total / capital_rotado * 100.0) if capital_rotado > 0 else 0.0

    # Barra de progreso visual
    bloques_llenos = int(pct_meta_rotacion // 5)
    barra = "█" * bloques_llenos + "░" * (20 - bloques_llenos)

    print(f"🎯 META DE ROTACIÓN DIARIA ($200 USD): [{barra}] {pct_meta_rotacion:.1f}%")
    print(
        f"   • Capital ya apostado hoy : ${capital_rotado:.2f} USD ({len(df_ok)} micro-apuestas aprobadas en vivo)"
    )
    print(f"   • Capital disponible hoy  : ${capital_restante:.2f} USD")
    print(
        f"   • Ganancia esperada hoy   : +${ganancia_esp_total:.2f} USD "
        f"(Rendimiento medio: +{roi_promedio_pct:.2f}% | Meta 4% = +${META_GANANCIA_DIARIA_USD:.2f} USD)"
    )
    print(
        f"   • Filtro de Orderbook     : {len(df_rechazadas)} órdenes bloqueadas a tiempo por falta de liquidez o slippage"
    )

    if not df_ok.empty:
        print("\n" + "─" * 108)
        print("⚙️  DESGLOSE POR CADA UNO DE LOS 3 MOTORES:")
        print("─" * 108)
        resumen_motor = (
            df_ok.groupby("Estrategia", as_index=False)
            .agg(
                Micro_Apuestas=("Stake_USD", "count"),
                Capital_Rotado_USD=("Stake_USD", "sum"),
                Ventaja_Media_Pct=("Ventaja_Viva_Pct", "mean"),
                Ganancia_Esp_USD=("Ganancia_Esperada_USD", "sum"),
            )
            .round(2)
        )
        print(resumen_motor.to_string(index=False))

        print("\n" + "─" * 108)
        print("🏦 DESGLOSE POR PLATAFORMA (Billetera Web3 vs Kalshi):")
        print("─" * 108)
        resumen_plat = (
            df_ok.groupby("Plataforma", as_index=False)
            .agg(
                Micro_Apuestas=("Stake_USD", "count"),
                Capital_Rotado_USD=("Stake_USD", "sum"),
                Ganancia_Esp_USD=("Ganancia_Esperada_USD", "sum"),
            )
            .round(2)
        )
        print(resumen_plat.to_string(index=False))

        print("\n" + "─" * 108)
        print("✅ MICRO-APUESTAS APROBADAS HOY EN VIVO ($2.50 a $6.00 USD):")
        print("─" * 108)
        cols_mostrar = [
            "Timestamp_UTC",
            "Estrategia",
            "Plataforma",
            "Evento",
            "Seleccion",
            "Stake_USD",
            "Cuota_VWAP_Real_Libro",
            "Ventaja_Viva_Pct",
            "Ganancia_Esperada_USD",
        ]
        print(df_ok[cols_mostrar].to_string(index=False))

    print("═" * 108 + "\n")


def generar_texto_resumen_telegram_hoy() -> str:
    """Construye el resumen ejecutivo del día en formato Markdown para enviar a Telegram cada 2 horas."""
    hoy_utc = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    ahora_str = datetime.now(tz=timezone.utc).strftime("%H:%M UTC")

    if not RUTA_HISTORIAL.exists():
        return f"📊 *RESUMEN 2H — TRIPLE MOTOR ({ahora_str})*\nAún sin ejecuciones registradas hoy."

    df = pd.read_csv(RUTA_HISTORIAL)
    if df.empty or "Timestamp_UTC" not in df.columns:
        return f"📊 *RESUMEN 2H — TRIPLE MOTOR ({ahora_str})*\nHistorial vacío por ahora."

    df_hoy = df[df["Timestamp_UTC"].astype(str).str.startswith(hoy_utc)].copy()
    if df_hoy.empty:
        return f"📊 *RESUMEN 2H — TRIPLE MOTOR ({ahora_str})*\nSin operaciones para {hoy_utc}."

    mask_aprobadas = df_hoy["Estado_Orden"].astype(str).str.contains("OK|EJECUTAD|ACTIVO", na=False)
    df_ok = df_hoy[mask_aprobadas].copy()
    df_rechazadas = df_hoy[~mask_aprobadas].copy()

    df_ok["Ganancia_Esperada_USD"] = round(df_ok["Stake_USD"] * (df_ok["Ventaja_Viva_Pct"] / 100.0), 2)

    capital_rotado = float(df_ok["Stake_USD"].sum()) if not df_ok.empty else 0.0
    capital_restante = max(0.0, META_DIARIA_USD - capital_rotado)
    pct_meta = min(100.0, (capital_rotado / META_DIARIA_USD) * 100.0)
    ganancia_esp = float(df_ok["Ganancia_Esperada_USD"].sum()) if not df_ok.empty else 0.0
    roi_medio = (ganancia_esp / capital_rotado * 100.0) if capital_rotado > 0 else 0.0

    bloques = int(pct_meta // 10)
    barra = "█" * bloques + "░" * (10 - bloques)

    lineas = [
        f"🤖 *REPORTE CADA 2 HORAS — TRIPLE MOTOR ({hoy_utc} {ahora_str})*",
        f"🎯 *Meta Diaria ($200 USD):* `[{barra}] {pct_meta:.1f}%`",
        f"• *Capital apostado hoy:* `${capital_rotado:.2f} USD` ({len(df_ok)} micro-apuestas)",
        f"• *Capital restante hoy:* `${capital_restante:.2f} USD`",
        f"• *Ganancia esperada hoy:* `+${ganancia_esp:.2f} USD` (+{roi_medio:.2f}% ROI medio | Meta 4% = +$8.00)",
        f"• *Órdenes filtradas en Orderbook:* `{len(df_rechazadas)}` bloqueadas por slippage/liquidez",
        "",
        "⚙️ *Desglose por Motor:*",
    ]

    if not df_ok.empty:
        resumen_motor = (
            df_ok.groupby("Estrategia", as_index=False)
            .agg(
                Cant=("Stake_USD", "count"),
                Capital=("Stake_USD", "sum"),
                Ventaja=("Ventaja_Viva_Pct", "mean"),
                Ganancia=("Ganancia_Esperada_USD", "sum"),
            )
            .round(2)
        )
        for _, r in resumen_motor.iterrows():
            lineas.append(
                f"  • `{r['Estrategia']}`: *{int(r['Cant'])} tiros* | `${r['Capital']:.2f}` | *+${r['Ganancia']:.2f} USD* (media +{r['Ventaja']:.1f}%)"
            )

        lineas.append("")
        lineas.append("🏦 *Desglose por Plataforma:*")
        resumen_plat = (
            df_ok.groupby("Plataforma", as_index=False)
            .agg(Cant=("Stake_USD", "count"), Capital=("Stake_USD", "sum"), Ganancia=("Ganancia_Esperada_USD", "sum"))
            .round(2)
        )
        for _, rp in resumen_plat.iterrows():
            lineas.append(
                f"  • *{rp['Plataforma']}*: {int(rp['Cant'])} tiros (`${rp['Capital']:.2f}` ➡️ `+${rp['Ganancia']:.2f}`)"
            )

        lineas.append("")
        lineas.append("✅ *Últimas 5 Micro-Apuestas Aprobadas:*")
        for _, u in df_ok.tail(5).iterrows():
            lineas.append(
                f"  • [{u['Plataforma']}] *{u['Evento']}*\n"
                f"    `{u['Seleccion']}` | Stake: *${u['Stake_USD']:.2f}* @ `{u['Cuota_VWAP_Real_Libro']}` (+{u['Ventaja_Viva_Pct']}%)"
            )

    return "\n".join(lineas)


if __name__ == "__main__":
    mostrar_panel_hoy()

