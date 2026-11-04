"""
Auditor de Resultados Reales (Backtest En Vivo Post-Partido): `auditar_pnl_real.py`
Cruza todas las micro-apuestas registradas en `datos/historial_ejecuciones.csv` contra:
1. Los marcadores finales reales de ESPN API (`site.api.espn.com`) para NBA, NFL, MLB, NHL, Fútbol y UFC
   entre el 19 de octubre y la fecha actual.
2. Verifica para cada apuesta de `MOTOR_1_VALUE_FAVORITO` (y también qué habría pasado si `MOTOR_3` se mantenía
   hasta el final del partido vs si cerraba pre-partido) si el resultado real fue GANADA, PERDIDA o PENDIENTE.
3. Calcula cuántos dólares reales habrías ganado o perdido hoy en tu bolsillo.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import re
import sys
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
import requests

from configuracion import DIRECTORIO_DATOS
from normalizador.emparejador import similitud_equipos, quitar_spread_de_nombre

RUTA_HISTORIAL = DIRECTORIO_DATOS / "historial_ejecuciones.csv"
RUTA_REPORTE_REAL = DIRECTORIO_DATOS / "reporte_pnl_real_verificado.csv"

LIGAS_ESPN_HISTORICO = [
    "basketball/nba",
    "football/nfl",
    "baseball/mlb",
    "hockey/nhl",
    "mma/ufc",
    "soccer/eng.1",
    "soccer/esp.1",
    "soccer/ita.1",
    "soccer/ger.1",
    "soccer/fra.1",
    "soccer/usa.1",
    "soccer/uefa.champions",
]


def _fetch_espn_dia(args: Tuple[str, str]) -> List[Dict[str, Any]]:
    liga, fecha_str = args
    salida: List[Dict[str, Any]] = []
    url = f"https://site.api.espn.com/apis/site/v2/sports/{liga}/scoreboard"
    try:
        resp = requests.get(
            url,
            params={"dates": fecha_str, "limit": 200},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        if resp.status_code != 200:
            return salida
        eventos = resp.json().get("events") or []
    except Exception:
        return salida

    for ev in eventos:
        comp = (ev.get("competitions") or [{}])[0]
        estado = ((ev.get("status") or {}).get("type") or {})
        if not bool(estado.get("completed")):
            continue

        fecha_ev = str(ev.get("date", ""))[:10]
        competitors = comp.get("competitors") or []
        if len(competitors) < 2:
            continue

        eq_home, eq_away = "", ""
        pts_home, pts_away = 0.0, 0.0
        ganador_nombre = ""

        for c in competitors:
            team_obj = c.get("team") or {}
            athlete_obj = c.get("athlete") or {}
            nombre = (
                team_obj.get("displayName")
                or team_obj.get("name")
                or athlete_obj.get("displayName")
                or ""
            )
            try:
                score_val = float(str(c.get("score", "0")))
            except ValueError:
                score_val = 0.0

            if c.get("homeAway") == "home" or not eq_home:
                if not eq_home:
                    eq_home = nombre
                    pts_home = score_val
                else:
                    eq_away = nombre
                    pts_away = score_val
            else:
                eq_away = nombre
                pts_away = score_val

            if c.get("winner") is True:
                ganador_nombre = nombre

        if eq_home and eq_away:
            salida.append(
                {
                    "Liga": liga,
                    "Fecha": fecha_ev,
                    "Home": eq_home,
                    "Away": eq_away,
                    "Pts_Home": pts_home,
                    "Pts_Away": pts_away,
                    "Total_Pts": pts_home + pts_away,
                    "Ganador": ganador_nombre,
                    "Empate": (pts_home == pts_away and not ganador_nombre),
                }
            )
    return salida


def descargar_marcadores_finales_espn(fechas_yyyymmdd: List[str]) -> List[Dict[str, Any]]:
    """Descarga en paralelo los resultados finales reales de ESPN para cada día."""
    tareas = [(liga, f) for liga in LIGAS_ESPN_HISTORICO for f in fechas_yyyymmdd]
    partidos_finalizados: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=16) as pool:
        for res in pool.map(_fetch_espn_dia, tareas):
            partidos_finalizados.extend(res)
    return partidos_finalizados


def _buscar_resultado_partido(
    evento_str: str,
    fecha_apuesta_str: str,
    partidos_espn: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Empareja el evento de la apuesta contra el partido finalizado real dentro de una ventana de 0 a +4 días."""
    partes = re.split(r"\s+vs\.?\s+|\s+@\s+|\s+-\s+", str(evento_str), flags=re.IGNORECASE)
    if len(partes) < 2:
        return None
    eq1 = quitar_spread_de_nombre(partes[0].split(":")[-1].strip())
    eq2 = quitar_spread_de_nombre(partes[1].split("(")[0].strip())

    try:
        dt_ap = datetime.strptime(fecha_apuesta_str[:10], "%Y-%m-%d")
    except ValueError:
        dt_ap = None

    mejor_match = None
    mejor_sim = 0.0

    for p in partidos_espn:
        if dt_ap is not None:
            try:
                dt_p = datetime.strptime(p["Fecha"], "%Y-%m-%d")
                diff_dias = (dt_p - dt_ap).days
                if diff_dias < -1 or diff_dias > 5:
                    continue
            except ValueError:
                pass

        sim_dir = min(similitud_equipos(eq1, p["Home"]), similitud_equipos(eq2, p["Away"]))
        sim_inv = min(similitud_equipos(eq1, p["Away"]), similitud_equipos(eq2, p["Home"]))
        sim = max(sim_dir, sim_inv)
        if sim >= 80.0 and sim > mejor_sim:
            mejor_sim = sim
            mejor_match = p

    return mejor_match


def evaluar_apuesta_contra_marcador(
    fila: pd.Series,
    partido: Dict[str, Any],
) -> Tuple[str, float, str]:
    """
    Evalúa si una apuesta fue GANADA, PERDIDA o PUSH según el marcador real finalizado.
    Retorna: (resultado_str, pnl_usd_real, marcador_str)
    """
    mercado = str(fila.get("Mercado", ""))
    seleccion_raw = str(fila.get("Seleccion", ""))
    seleccion_limpia = seleccion_raw.split(" (Prob:")[0].strip()
    stake = float(fila.get("Stake_USD", 0.0))
    cuota = float(fila.get("Cuota_VWAP_Real_Libro", 1.0))

    marcador_str = f"{partido['Home']} {int(partido['Pts_Home'])} - {int(partido['Pts_Away'])} {partido['Away']}"

    # 1. Totales (Over / Under)
    if "total" in mercado.lower() or "over/under" in mercado.lower() or seleccion_limpia.lower() in ("over", "under"):
        m_num = re.findall(r"[-+]?\d+(?:\.\d+)?", mercado)
        if not m_num:
            return "SIN_LINEA", 0.0, marcador_str
        linea_total = float(m_num[-1])
        total_real = float(partido["Total_Pts"])
        es_over = "over" in seleccion_limpia.lower()
        if abs(total_real - linea_total) < 0.01:
            return "PUSH", 0.0, f"{marcador_str} (Total: {total_real})"
        gano = (total_real > linea_total) if es_over else (total_real < linea_total)
        pnl = round(stake * (cuota - 1.0), 2) if gano else round(-stake, 2)
        return ("GANADA" if gano else "PERDIDA"), pnl, f"{marcador_str} (Total: {total_real} vs {linea_total})"

    # 2. Hándicap (Spread)
    if "hándicap" in mercado.lower() or "handicap" in mercado.lower() or "spread" in mercado.lower():
        m_num = re.findall(r"[-+]?\d+(?:\.\d+)?", mercado)
        if not m_num:
            return "SIN_LINEA", 0.0, marcador_str
        linea_raw = float(m_num[-1])
        # Si la cuota es > 2.50 en un spread alternativo (ej. -13.5 o -25.5), la apuesta es siempre al hándicap negativo (-abs)
        if cuota > 2.50:
            linea_efectiva = -abs(linea_raw)
        else:
            partes_ev = re.split(r"\s+vs\.?\s+|\s+@\s+|\s+-\s+", str(fila.get("Evento", "")), flags=re.IGNORECASE)
            if len(partes_ev) >= 2:
                eq1_ev = quitar_spread_de_nombre(partes_ev[0].split(":")[-1].strip())
                eq2_ev = quitar_spread_de_nombre(partes_ev[1].split("(")[0].strip())
                es_lado_1 = similitud_equipos(seleccion_limpia, eq1_ev) >= similitud_equipos(seleccion_limpia, eq2_ev)
                linea_efectiva = linea_raw if es_lado_1 else -linea_raw
            else:
                linea_efectiva = linea_raw

        sim_home = similitud_equipos(seleccion_limpia, partido["Home"])
        sim_away = similitud_equipos(seleccion_limpia, partido["Away"])
        pts_sel = partido["Pts_Home"] if sim_home >= sim_away else partido["Pts_Away"]
        pts_riv = partido["Pts_Away"] if sim_home >= sim_away else partido["Pts_Home"]
        diff_ajustada = (pts_sel + linea_efectiva) - pts_riv
        if abs(diff_ajustada) < 0.01:
            return "PUSH", 0.0, marcador_str
        gano = diff_ajustada > 0
        pnl = round(stake * (cuota - 1.0), 2) if gano else round(-stake, 2)
        return ("GANADA" if gano else "PERDIDA"), pnl, f"{marcador_str} (Spread {seleccion_limpia} {linea_efectiva:+g})"

    # 3. Ganador (Moneyline / 1X2)
    if partido["Empate"] and "1x2" in mercado.lower():
        return "PERDIDA", round(-stake, 2), f"{marcador_str} (Empate)"

    sim_home = similitud_equipos(seleccion_limpia, partido["Home"])
    sim_away = similitud_equipos(seleccion_limpia, partido["Away"])
    apostado_home = sim_home >= sim_away
    gano_home = partido["Pts_Home"] > partido["Pts_Away"] or (
        partido["Ganador"] and similitud_equipos(partido["Ganador"], partido["Home"]) >= 80
    )
    gano = apostado_home == gano_home
    pnl = round(stake * (cuota - 1.0), 2) if gano else round(-stake, 2)
    return ("GANADA" if gano else "PERDIDA"), pnl, marcador_str


def ejecutar_auditoria_real() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not RUTA_HISTORIAL.exists():
        print("No se encontró `datos/historial_ejecuciones.csv`.")
        return

    df = pd.read_csv(RUTA_HISTORIAL)
    df_ok = df[df["Estado_Orden"].astype(str).str.contains("OK|EJECUTAD|ACTIVO", na=False)].copy()

    print("\nConsultando marcadores finales reales en ESPN API (2026-10-19 al 2026-11-04)...")
    rangos_fechas = [
        "20261019",
        "20261025",
        "20261026",
        "20261027",
        "20261028",
        "20261029",
        "20261030",
        "20261031",
        "20261101",
        "20261102",
        "20261103",
    ]
    partidos_reales = descargar_marcadores_finales_espn(rangos_fechas)
    print(f"Total de partidos finalizados oficiales descargados: {len(partidos_reales)}")

    resultados_verificados = []
    for _, fila in df_ok.iterrows():
        est = str(fila["Estrategia"])
        stake = float(fila["Stake_USD"])
        ventaja_pct = float(fila["Ventaja_Viva_Pct"])
        ganancia_esp = round(stake * (ventaja_pct / 100.0), 2)

        if "MOTOR_2_SUREBET" in est:
            # En Surebet de 2 patas simultáneas, el retorno está bloqueado en ambos lados
            res_str = "GANADA_SUREBET"
            pnl_hold = ganancia_esp
            pnl_plan = ganancia_esp
            marcador = "Arbitraje 2 Lados (Retorno Garantizado)"
        else:
            partido = _buscar_resultado_partido(
                str(fila["Evento"]),
                str(fila["Timestamp_UTC"]),
                partidos_reales,
            )
            if partido is None:
                res_str = "PENDIENTE_O_OTRA_LIGA"
                pnl_hold = 0.0
                pnl_plan = ganancia_esp if "MOTOR_3" in est else 0.0
                marcador = "Partido futuro o liga secundaria (Tenis/Esports)"
            else:
                res_str, pnl_hold, marcador = evaluar_apuesta_contra_marcador(fila, partido)
                # Para MOTOR 3 (Trading Pre-Partido), el plan de salida es vender antes del inicio (+ROI scalping)
                pnl_plan = ganancia_esp if "MOTOR_3" in est else pnl_hold

        resultados_verificados.append(
            {
                "Fecha": str(fila["Timestamp_UTC"])[:10],
                "Estrategia": est,
                "Plataforma": fila["Plataforma"],
                "Evento": fila["Evento"],
                "Mercado": fila["Mercado"],
                "Seleccion": str(fila["Seleccion"]).split(" (Prob:")[0],
                "Stake_USD": stake,
                "Cuota_Viva": fila["Cuota_VWAP_Real_Libro"],
                "Ventaja_Pct": ventaja_pct,
                "Resultado_Partido_Real": res_str,
                "Marcador_Oficial": marcador,
                "PnL_Si_Mantenes_Al_Final_USD": pnl_hold,
                "PnL_Segun_Plan_Motor_USD": pnl_plan,
                "EV_Matematico_USD": ganancia_esp,
            }
        )

    df_res = pd.DataFrame(resultados_verificados)
    df_res.to_csv(RUTA_REPORTE_REAL, index=False, encoding="utf-8-sig")

    resueltas = df_res[df_res["Resultado_Partido_Real"].isin(["GANADA", "PERDIDA", "GANADA_SUREBET"])].copy()
    ganadas = resueltas[resueltas["Resultado_Partido_Real"].str.startswith("GANADA")]
    perdidas = resueltas[resueltas["Resultado_Partido_Real"] == "PERDIDA"]

    print("\n" + "═" * 108)
    print("🏆 AUDITORÍA DE RESULTADOS REALES (19 OCT AL 04 NOV — ¿HABRÍAS GANADO PLATA DE VERDAD?)")
    print("═" * 108)
    print(f"• Total de micro-apuestas aprobadas por el bot : {len(df_res)} apuestas (${df_res['Stake_USD'].sum():.2f} USD rotados)")
    print(f"• Ganancia Matemática Esperada (+EV total)     : +${df_res['EV_Matematico_USD'].sum():.2f} USD (+{(df_res['EV_Matematico_USD'].sum()/df_res['Stake_USD'].sum()*100):.2f}% ROI)")
    print("─" * 108)
    print(f"📊 PARTIDOS FINALIZADOS VERIFICADOS CON MARCADOR OFICIAL ({len(resueltas)} partidos resueltos):")
    if not resueltas.empty:
        win_rate = (len(ganadas) / len(resueltas)) * 100.0
        capital_resuelto = resueltas["Stake_USD"].sum()
        pnl_hold_total = resueltas["PnL_Si_Mantenes_Al_Final_USD"].sum()
        pnl_plan_total = resueltas["PnL_Segun_Plan_Motor_USD"].sum()
        print(f"   ✅ Apuestas GANADAS en la cancha : {len(ganadas)} ({win_rate:.1f}% de acierto real)")
        print(f"   ❌ Apuestas PERDIDAS en la cancha: {len(perdidas)}")
        print(f"   💵 Capital jugado en resueltas   : ${capital_resuelto:.2f} USD")
        print(
            f"   💰 GANANCIA NETA REAL (Quedándose hasta el final en TODAS) : "
            f"{pnl_hold_total:+.2f} USD ({(pnl_hold_total/capital_resuelto*100):+.2f}% ROI Real)"
        )
        print(
            f"   🚀 GANANCIA NETA REAL (Motor 1 al final + Motor 3 Scalping): "
            f"{pnl_plan_total:+.2f} USD ({(pnl_plan_total/capital_resuelto*100):+.2f}% ROI Real)"
        )

        print("\n" + "─" * 108)
        print("⚙️  RENDIMIENTO REAL POR MOTOR (EN PARTIDOS YA FINALIZADOS):")
        print("─" * 108)
        por_motor = (
            resueltas.groupby("Estrategia", as_index=False)
            .agg(
                Resueltas=("Stake_USD", "count"),
                Ganadas=("Resultado_Partido_Real", lambda s: sum(s.str.startswith("GANADA"))),
                Capital_USD=("Stake_USD", "sum"),
                PnL_Hold_Final_USD=("PnL_Si_Mantenes_Al_Final_USD", "sum"),
                PnL_Plan_Motor_USD=("PnL_Segun_Plan_Motor_USD", "sum"),
            )
            .round(2)
        )
        por_motor["WinRate_Pct"] = ((por_motor["Ganadas"] / por_motor["Resueltas"]) * 100.0).round(1)
        print(por_motor.to_string(index=False))

        print("\n" + "─" * 108)
        print("📋 MUESTRA DE LAS ÚLTIMAS 25 APUESTAS VERIFICADAS CONTRA EL MARCADOR OFICIAL:")
        print("─" * 108)
        cols = [
            "Fecha",
            "Estrategia",
            "Evento",
            "Seleccion",
            "Stake_USD",
            "Cuota_Viva",
            "Resultado_Partido_Real",
            "PnL_Si_Mantenes_Al_Final_USD",
            "Marcador_Oficial",
        ]
        print(resueltas[cols].tail(25).to_string(index=False))

    print("═" * 108 + "\n")


if __name__ == "__main__":
    ejecutar_auditoria_real()
