"""
Oráculo Sharp / Bookmaker 100% Gratuito e Ilimitado en Tiempo Real (0 Tokens / Sin API Keys).
Reemplaza y complementa a The-Odds-API combinando dos fuentes públicas en vivo:
1. Action Network Live Scoreboard API (`api.actionnetwork.com/web/v1/scoreboard/{liga}`)
   -> Línea de consenso institucional en tiempo real (Moneyline, Spread, Totales).
2. ESPN / DraftKings Live Scoreboard API (`site.api.espn.com/apis/site/v2/sports/{deporte}/{liga}/scoreboard`)
   -> Cuotas en vivo de DraftKings Sportsbook (Moneyline, Point Spread, Over/Under, 1X2).
"""
import logging
from typing import List, Dict, Any, Optional
import requests
from configuracion import calcular_overround_pct

logger = logging.getLogger(__name__)

LIGAS_ACTION_NETWORK = [
    ("nba", "Básquetbol", "NBA"),
    ("nfl", "Fútbol Americano", "NFL"),
    ("nhl", "Hockey sobre Hielo", "NHL"),
    ("mlb", "Béisbol", "MLB"),
    ("soccer", "Fútbol", "Fútbol Internacional"),
    ("ufc", "MMA / Boxeo", "UFC"),
    ("ncaaf", "Fútbol Americano", "NCAAF"),
    ("ncaab", "Básquetbol", "NCAAB"),
]

LIGAS_ESPN_DRAFTKINGS = [
    ("basketball/nba", "Básquetbol", "NBA"),
    ("football/nfl", "Fútbol Americano", "NFL"),
    ("hockey/nhl", "Hockey sobre Hielo", "NHL"),
    ("baseball/mlb", "Béisbol", "MLB"),
    ("mma/ufc", "MMA / Boxeo", "UFC"),
    ("soccer/eng.1", "Fútbol", "Premier League"),
    ("soccer/esp.1", "Fútbol", "La Liga"),
    ("soccer/ita.1", "Fútbol", "Serie A"),
    ("soccer/ger.1", "Fútbol", "Bundesliga"),
    ("soccer/fra.1", "Fútbol", "Ligue 1"),
    ("soccer/uefa.champions", "Fútbol", "UEFA Champions League"),
    ("soccer/usa.1", "Fútbol", "MLS"),
]


def _americana_a_decimal(valor: Any) -> Optional[float]:
    """Convierte cuota americana (ej. -135, '+114', 'EVEN') a cuota decimal."""
    if valor is None:
        return None
    s = str(valor).strip().upper()
    if not s or s in ("N/A", "NONE", "NULL", "OFF"):
        return None
    if s in ("EVEN", "EV"):
        return 2.0
    try:
        num = float(s.replace("+", ""))
    except ValueError:
        return None
    if abs(num) < 100:
        return None
    if num > 0:
        return round(1.0 + (num / 100.0), 4)
    return round(1.0 + (100.0 / abs(num)), 4)


def extraer_action_network() -> List[Dict[str, Any]]:
    """Extrae líneas de consenso en tiempo real desde Action Network (0 tokens)."""
    filas: List[Dict[str, Any]] = []
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    for slug_liga, deporte_es, liga_es in LIGAS_ACTION_NETWORK:
        url = f"https://api.actionnetwork.com/web/v1/scoreboard/{slug_liga}"
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code != 200:
                continue
            juegos = resp.json().get("games") or []
        except Exception as exc:
            logger.debug("Error ActionNetwork %s: %s", slug_liga, exc)
            continue

        for g in juegos:
            if str(g.get("status", "")).lower() not in ("scheduled", "pregame", "created"):
                # Ignorar partidos ya finalizados o en juego
                if str(g.get("status", "")).lower() in ("complete", "closed", "inprogress"):
                    continue

            equipos = {t.get("id"): t.get("full_name") for t in (g.get("teams") or []) if isinstance(t, dict)}
            id_local = g.get("home_team_id")
            id_vis = g.get("away_team_id")
            local = str(equipos.get(id_local) or "Local")
            visitante = str(equipos.get(id_vis) or "Visitante")
            if local == "Local" or visitante == "Visitante":
                continue

            evento_str = f"{local} vs {visitante}"
            inicio_utc = str(g.get("start_time", ""))
            id_juego = str(g.get("id", ""))

            # Buscar el nodo de cuotas de partido completo ('type': 'game')
            odds_juego = [o for o in (g.get("odds") or []) if isinstance(o, dict) and o.get("type") == "game"]
            if not odds_juego:
                continue
            nodo = odds_juego[0]

            # 1. Moneyline ( o 1X2 si incluye draw )
            c_local = _americana_a_decimal(nodo.get("ml_home"))
            c_vis = _americana_a_decimal(nodo.get("ml_away"))
            c_empate = _americana_a_decimal(nodo.get("draw"))

            if c_local and c_vis and c_local > 1.01 and c_vis > 1.01:
                if c_empate and c_empate > 1.01:
                    overround_3 = round(((1.0 / c_local) + (1.0 / c_vis) + (1.0 / c_empate) - 1.0) * 100.0, 2)
                    filas.append(
                        {
                            "Plataforma": "Pinnacle",
                            "Deporte": deporte_es,
                            "Liga": liga_es,
                            "Evento": evento_str,
                            "Inicio_UTC": inicio_utc,
                            "Tipo_Mercado": "Ganador (1X2 - Sin Empate Ref)",
                            "Linea": f"Empate@{c_empate}",
                            "Lado_1": local,
                            "Cuota_Taker_1": c_local,
                            "Liquidez_1_USD": 10000.0,
                            "Lado_2": visitante,
                            "Cuota_Taker_2": c_vis,
                            "Liquidez_2_USD": 10000.0,
                            "Overround_Libro_Pct": overround_3,
                            "ID_Mercado": f"an_{id_juego}_1x2",
                        }
                    )
                else:
                    filas.append(
                        {
                            "Plataforma": "Pinnacle",
                            "Deporte": deporte_es,
                            "Liga": liga_es,
                            "Evento": evento_str,
                            "Inicio_UTC": inicio_utc,
                            "Tipo_Mercado": "Ganador (Moneyline)",
                            "Linea": "N/A",
                            "Lado_1": local,
                            "Cuota_Taker_1": c_local,
                            "Liquidez_1_USD": 10000.0,
                            "Lado_2": visitante,
                            "Cuota_Taker_2": c_vis,
                            "Liquidez_2_USD": 10000.0,
                            "Overround_Libro_Pct": calcular_overround_pct(c_local, c_vis),
                            "ID_Mercado": f"an_{id_juego}_ml",
                        }
                    )

            # 2. Spread (Hándicap)
            sp_home = nodo.get("spread_home")
            c_sp_home = _americana_a_decimal(nodo.get("spread_home_line"))
            c_sp_away = _americana_a_decimal(nodo.get("spread_away_line"))
            if sp_home is not None and c_sp_home and c_sp_away:
                filas.append(
                    {
                        "Plataforma": "Pinnacle",
                        "Deporte": deporte_es,
                        "Liga": liga_es,
                        "Evento": evento_str,
                        "Inicio_UTC": inicio_utc,
                        "Tipo_Mercado": "Hándicap (Spread)",
                        "Linea": str(float(sp_home)),
                        "Lado_1": local,
                        "Cuota_Taker_1": c_sp_home,
                        "Liquidez_1_USD": 10000.0,
                        "Lado_2": visitante,
                        "Cuota_Taker_2": c_sp_away,
                        "Liquidez_2_USD": 10000.0,
                        "Overround_Libro_Pct": calcular_overround_pct(c_sp_home, c_sp_away),
                        "ID_Mercado": f"an_{id_juego}_sp_{sp_home}",
                    }
                )

            # 3. Totales (Over/Under)
            total_pts = nodo.get("total")
            c_over = _americana_a_decimal(nodo.get("over"))
            c_under = _americana_a_decimal(nodo.get("under"))
            if total_pts is not None and c_over and c_under:
                filas.append(
                    {
                        "Plataforma": "Pinnacle",
                        "Deporte": deporte_es,
                        "Liga": liga_es,
                        "Evento": evento_str,
                        "Inicio_UTC": inicio_utc,
                        "Tipo_Mercado": "Totales (Over/Under)",
                        "Linea": str(float(total_pts)),
                        "Lado_1": "Over",
                        "Cuota_Taker_1": c_over,
                        "Liquidez_1_USD": 10000.0,
                        "Lado_2": "Under",
                        "Cuota_Taker_2": c_under,
                        "Liquidez_2_USD": 10000.0,
                        "Overround_Libro_Pct": calcular_overround_pct(c_over, c_under),
                        "ID_Mercado": f"an_{id_juego}_tot_{total_pts}",
                    }
                )

    return filas


def extraer_espn_draftkings() -> List[Dict[str, Any]]:
    """Extrae cuotas en vivo de DraftKings desde la API pública de ESPN (0 tokens)."""
    filas: List[Dict[str, Any]] = []
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

    for ruta_deporte, deporte_es, liga_es in LIGAS_ESPN_DRAFTKINGS:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{ruta_deporte}/scoreboard"
        try:
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code != 200:
                continue
            eventos = resp.json().get("events") or []
        except Exception as exc:
            logger.debug("Error ESPN %s: %s", ruta_deporte, exc)
            continue

        for ev in eventos:
            estado_tipo = (ev.get("status") or {}).get("type") or {}
            if estado_tipo.get("state") in ("in", "post"):
                continue

            comp = (ev.get("competitions") or [{}])[0]
            odds_list = comp.get("odds") or []
            if not odds_list:
                continue
            odd = odds_list[0]

            local = ((odd.get("homeTeamOdds") or {}).get("team") or {}).get("displayName")
            visitante = ((odd.get("awayTeamOdds") or {}).get("team") or {}).get("displayName")
            if not local or not visitante:
                competitors = comp.get("competitors") or []
                for c in competitors:
                    if c.get("homeAway") == "home":
                        local = (c.get("team") or {}).get("displayName")
                    elif c.get("homeAway") == "away":
                        visitante = (c.get("team") or {}).get("displayName")
            if not local or not visitante:
                continue

            evento_str = f"{local} vs {visitante}"
            inicio_utc = str(ev.get("date", ""))
            id_ev = str(ev.get("id", ""))

            # 1. Moneyline / 1X2
            ml = odd.get("moneyline") or {}
            c_home = _americana_a_decimal(((ml.get("home") or {}).get("close") or {}).get("odds"))
            c_away = _americana_a_decimal(((ml.get("away") or {}).get("close") or {}).get("odds"))
            c_draw = _americana_a_decimal(((odd.get("drawOdds") or {}).get("moneyLine")))

            if c_home and c_away and c_home > 1.01 and c_away > 1.01:
                if "soccer" in ruta_deporte and c_draw and c_draw > 1.01:
                    overround_3 = round(((1.0 / c_home) + (1.0 / c_away) + (1.0 / c_draw) - 1.0) * 100.0, 2)
                    filas.append(
                        {
                            "Plataforma": "Pinnacle",
                            "Deporte": deporte_es,
                            "Liga": liga_es,
                            "Evento": evento_str,
                            "Inicio_UTC": inicio_utc,
                            "Tipo_Mercado": "Ganador (1X2 - Sin Empate Ref)",
                            "Linea": f"Empate@{c_draw}",
                            "Lado_1": local,
                            "Cuota_Taker_1": c_home,
                            "Liquidez_1_USD": 10000.0,
                            "Lado_2": visitante,
                            "Cuota_Taker_2": c_away,
                            "Liquidez_2_USD": 10000.0,
                            "Overround_Libro_Pct": overround_3,
                            "ID_Mercado": f"espn_{id_ev}_1x2",
                        }
                    )
                elif "soccer" not in ruta_deporte:
                    filas.append(
                        {
                            "Plataforma": "Pinnacle",
                            "Deporte": deporte_es,
                            "Liga": liga_es,
                            "Evento": evento_str,
                            "Inicio_UTC": inicio_utc,
                            "Tipo_Mercado": "Ganador (Moneyline)",
                            "Linea": "N/A",
                            "Lado_1": local,
                            "Cuota_Taker_1": c_home,
                            "Liquidez_1_USD": 10000.0,
                            "Lado_2": visitante,
                            "Cuota_Taker_2": c_away,
                            "Liquidez_2_USD": 10000.0,
                            "Overround_Libro_Pct": calcular_overround_pct(c_home, c_away),
                            "ID_Mercado": f"espn_{id_ev}_ml",
                        }
                    )

            # 2. Point Spread
            ps = odd.get("pointSpread") or {}
            home_ps = (ps.get("home") or {}).get("close") or {}
            away_ps = (ps.get("away") or {}).get("close") or {}
            linea_sp = home_ps.get("line")
            c_sp_h = _americana_a_decimal(home_ps.get("odds"))
            c_sp_a = _americana_a_decimal(away_ps.get("odds"))
            if linea_sp is not None and c_sp_h and c_sp_a:
                try:
                    val_sp = str(float(str(linea_sp).replace("+", "")))
                    filas.append(
                        {
                            "Plataforma": "Pinnacle",
                            "Deporte": deporte_es,
                            "Liga": liga_es,
                            "Evento": evento_str,
                            "Inicio_UTC": inicio_utc,
                            "Tipo_Mercado": "Hándicap (Spread)",
                            "Linea": val_sp,
                            "Lado_1": local,
                            "Cuota_Taker_1": c_sp_h,
                            "Liquidez_1_USD": 10000.0,
                            "Lado_2": visitante,
                            "Cuota_Taker_2": c_sp_a,
                            "Liquidez_2_USD": 10000.0,
                            "Overround_Libro_Pct": calcular_overround_pct(c_sp_h, c_sp_a),
                            "ID_Mercado": f"espn_{id_ev}_sp_{val_sp}",
                        }
                    )
                except ValueError:
                    pass

            # 3. Total (Over/Under)
            tot = odd.get("total") or {}
            over_close = (tot.get("over") or {}).get("close") or {}
            under_close = (tot.get("under") or {}).get("close") or {}
            linea_tot = odd.get("overUnder")
            c_ov = _americana_a_decimal(over_close.get("odds"))
            c_un = _americana_a_decimal(under_close.get("odds"))
            if linea_tot is not None and c_ov and c_un:
                filas.append(
                    {
                        "Plataforma": "Pinnacle",
                        "Deporte": deporte_es,
                        "Liga": liga_es,
                        "Evento": evento_str,
                        "Inicio_UTC": inicio_utc,
                        "Tipo_Mercado": "Totales (Over/Under)",
                        "Linea": str(float(linea_tot)),
                        "Lado_1": "Over",
                        "Cuota_Taker_1": c_ov,
                        "Liquidez_1_USD": 10000.0,
                        "Lado_2": "Under",
                        "Cuota_Taker_2": c_un,
                        "Liquidez_2_USD": 10000.0,
                        "Overround_Libro_Pct": calcular_overround_pct(c_ov, c_un),
                        "ID_Mercado": f"espn_{id_ev}_tot_{linea_tot}",
                    }
                )

    return filas


def extraer_oraculo_gratis_en_vivo() -> List[Dict[str, Any]]:
    """
    Combina Action Network (Consenso Sharp) y ESPN/DraftKings en tiempo real,
    100% gratis y sin límite de llamadas.
    """
    m_an = extraer_action_network()
    m_espn = extraer_espn_draftkings()
    return m_an + m_espn


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    datos = extraer_oraculo_gratis_en_vivo()
    print(f"Total mercados extraídos del Oráculo Gratuito en Vivo: {len(datos)}")
    for m in datos[:6]:
        print(m)
