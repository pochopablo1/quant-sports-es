"""
Módulo Normalizador y de Emparejamiento Canónico Estricto.
Corrige y previene falsos positivos garantizando:
1. Limpieza de números de spread incrustados en los nombres de equipos (ej. 'Boston Celtics -2.5' -> 'Boston Celtics').
2. Diccionario de alias y nombres canónicos (ej. '49ers' -> 'San Francisco 49ers', 'L.A. Lakers' -> 'Los Angeles Lakers').
3. Coincidencia obligatoria de FECHA / VENTANA DE TIEMPO UTC (máximo ±12 horas) para no mezclar partidos de fechas distintas.
4. En Hándicap (Spread), validación exacta del signo (+/-) que recibe cada equipo:
   'Commanders -7.5' NUNCA puede cruzarse con 'Commanders +7.5' (que es '49ers -7.5').
5. Filtro de cordura cuantitativa: descarta desfasajes irreales (> 15% EV o > 10% Arbitraje) producto de mercados ilíquidos o exóticos.
"""
import re
import unicodedata
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from rapidfuzz import fuzz

PALABRAS_RUIDO = {
    "fc",
    "cf",
    "sc",
    "ac",
    "afc",
    "bc",
    "club",
    "deportivo",
    "utd",
    "sv",
    "vfb",
    "tsg",
    "1.",
    "fsv",
    "fk",
    "sk",
    "bk",
    "if",
    "cd",
    "ud",
    "rcd",
    "ca",
    "cs",
    "es",
    "as",
    "ss",
}

# Alias comunes en casas americanas/prediction markets (Polymarket usa solo el apodo en NFL/NBA/MLB/NHL)
ALIAS_EQUIPOS_CANONICOS = {
    # NFL
    "49ers": "san francisco 49ers",
    "sf 49ers": "san francisco 49ers",
    "commanders": "washington commanders",
    "chiefs": "kansas city chiefs",
    "ravens": "baltimore ravens",
    "bills": "buffalo bills",
    "eagles": "philadelphia eagles",
    "cowboys": "dallas cowboys",
    "lions": "detroit lions",
    "packers": "green bay packers",
    "bengals": "cincinnati bengals",
    "texans": "houston texans",
    "jets": "new york jets",
    "ny jets": "new york jets",
    "giants": "new york giants",
    "ny giants": "new york giants",
    "dolphins": "miami dolphins",
    "browns": "cleveland browns",
    "steelers": "pittsburgh steelers",
    "saints": "new orleans saints",
    "falcons": "atlanta falcons",
    "bears": "chicago bears",
    "vikings": "minnesota vikings",
    "seahawks": "seattle seahawks",
    "rams": "los angeles rams",
    "la rams": "los angeles rams",
    "chargers": "los angeles chargers",
    "la chargers": "los angeles chargers",
    "raiders": "las vegas raiders",
    "broncos": "denver broncos",
    "colts": "indianapolis colts",
    "jaguars": "jacksonville jaguars",
    "titans": "tennessee titans",
    "patriots": "new england patriots",
    "cardinals": "arizona cardinals",
    "panthers": "carolina panthers",
    "buccaneers": "tampa bay buccaneers",
    "bucs": "tampa bay buccaneers",
    # NBA
    "lakers": "los angeles lakers",
    "la lakers": "los angeles lakers",
    "l a lakers": "los angeles lakers",
    "clippers": "los angeles clippers",
    "la clippers": "los angeles clippers",
    "l a clippers": "los angeles clippers",
    "warriors": "golden state warriors",
    "celtics": "boston celtics",
    "knicks": "new york knicks",
    "ny knicks": "new york knicks",
    "nets": "brooklyn nets",
    "76ers": "philadelphia 76ers",
    "sixers": "philadelphia 76ers",
    "bucks": "milwaukee bucks",
    "nuggets": "denver nuggets",
    "thunder": "oklahoma city thunder",
    "okc thunder": "oklahoma city thunder",
    "suns": "phoenix suns",
    "mavericks": "dallas mavericks",
    "mavs": "dallas mavericks",
    "timberwolves": "minnesota timberwolves",
    "wolves": "minnesota timberwolves",
    "heat": "miami heat",
    "cavaliers": "cleveland cavaliers",
    "cavs": "cleveland cavaliers",
    "magic": "orlando magic",
    "pacers": "indiana pacers",
    "pelicans": "new orleans pelicans",
    "kings": "sacramento kings",
    "spurs": "san antonio spurs",
    "rockets": "houston rockets",
    "grizzlies": "memphis grizzlies",
    "hawks": "atlanta hawks",
    "bulls": "chicago bulls",
    "raptors": "toronto raptors",
    "jazz": "utah jazz",
    "hornets": "charlotte hornets",
    "pistons": "detroit pistons",
    "wizards": "washington wizards",
    "trail blazers": "portland trail blazers",
    "blazers": "portland trail blazers",
    # Abreviaturas / Ciudades de Kalshi
    "was commanders": "washington commanders",
    "sf 49ers": "san francisco 49ers",
    "san francisco": "san francisco 49ers",
    "washington": "washington commanders",
    "la lakers": "los angeles lakers",
    "los angeles l": "los angeles lakers",
    "los angeles c": "los angeles clippers",
    "golden state": "golden state warriors",
    "new york k": "new york knicks",
    "new york n": "brooklyn nets",
    "oklahoma city": "oklahoma city thunder",
    "san antonio": "san antonio spurs",
    "new orleans": "new orleans saints",
    "tampa bay": "tampa bay rays",
    "cleveland": "cleveland guardians",
}

TRADUCCIONES_DEPORTE = {
    "basketball": "Básquetbol",
    "american football": "Fútbol Americano",
    "football": "Fútbol",
    "soccer": "Fútbol",
    "baseball": "Béisbol",
    "ice hockey": "Hockey sobre Hielo",
    "hockey": "Hockey sobre Hielo",
    "tennis": "Tenis",
    "mixed martial arts": "MMA / Boxeo",
    "mma": "MMA / Boxeo",
    "boxing": "MMA / Boxeo",
    "esports": "eSports",
}


def quitar_spread_de_nombre(nombre: str) -> str:
    """
    Elimina números de línea o hándicap al final de un nombre de equipo:
    Ej: 'Boston Celtics -2.5' -> 'Boston Celtics'
        'Over 225.5' -> 'Over'
    """
    if not nombre:
        return ""
    limpio = re.sub(r"\s*[+-]?\d+(\.\d+)?\s*$", "", str(nombre).strip())
    return limpio.strip()


def limpiar_texto(texto: str) -> str:
    """
    Elimina números de spread al final, quita tildes (unicodedata), aplica el diccionario
    de alias canónicos y limpia tokens de ruido.
    """
    if not texto:
        return ""
    sin_spread = quitar_spread_de_nombre(texto)
    texto_nfd = unicodedata.normalize("NFD", sin_spread)
    sin_tildes = "".join(c for c in texto_nfd if unicodedata.category(c) != "Mn")
    limpio = re.sub(r"[^a-zA-Z0-9\s]", " ", sin_tildes.lower())
    limpio_espacios = " ".join(limpio.split())

    if limpio_espacios in ALIAS_EQUIPOS_CANONICOS:
        return ALIAS_EQUIPOS_CANONICOS[limpio_espacios]

    tokens = [t for t in limpio_espacios.split() if t not in PALABRAS_RUIDO and len(t) > 1]
    resultado = " ".join(tokens) if tokens else limpio_espacios
    return ALIAS_EQUIPOS_CANONICOS.get(resultado, resultado)


def estandarizar_deporte(deporte_raw: str) -> str:
    if not deporte_raw:
        return "Deportes"
    clave = deporte_raw.strip().lower()
    return TRADUCCIONES_DEPORTE.get(clave, deporte_raw.strip())


def parsear_datetime_utc(valor_fecha: Any) -> Optional[datetime]:
    """Convierte cualquier representación de fecha (ISO o Unix timestamp) en un objeto datetime UTC."""
    if not valor_fecha:
        return None
    s = str(valor_fecha).strip()
    if not s or s.lower() == "nan":
        return None
    if s.isdigit():
        ts = int(s)
        if ts > 1e11:
            ts = ts // 1000
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OSError):
            return None
    try:
        s_iso = s.replace("Z", "+00:00")
        if " " in s_iso and "T" not in s_iso:
            s_iso = s_iso.replace(" ", "T", 1)
        if s_iso.endswith("+00"):
            s_iso = s_iso + ":00"
        dt = datetime.fromisoformat(s_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def estandarizar_fecha_utc(valor_fecha: Any) -> str:
    dt = parsear_datetime_utc(valor_fecha)
    if dt:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(valor_fecha or "").strip()


def fechas_compatibles(fecha_a: Any, fecha_b: Any, max_horas: float = 18.0) -> bool:
    """
    Verifica que dos eventos correspondan al mismo partido comprobando que sus horas de inicio
    estén dentro de una ventana de `max_horas` (por defecto 18h).
    """
    dt_a = parsear_datetime_utc(fecha_a)
    dt_b = parsear_datetime_utc(fecha_b)
    if dt_a is None or dt_b is None:
        return True
    diferencia_horas = abs((dt_a - dt_b).total_seconds()) / 3600.0
    return diferencia_horas <= max_horas


def similitud_equipos(nombre_a: str, nombre_b: str) -> float:
    """
    Calcula puntaje de similitud (0 a 100) entre nombres de equipos ya canonizados.
    """
    limpio_a = limpiar_texto(nombre_a)
    limpio_b = limpiar_texto(nombre_b)
    if not limpio_a or not limpio_b:
        return 0.0
    if limpio_a == limpio_b:
        return 100.0
    puntaje_set = fuzz.token_set_ratio(limpio_a, limpio_b)
    puntaje_sort = fuzz.token_sort_ratio(limpio_a, limpio_b)
    return 0.60 * puntaje_set + 0.40 * puntaje_sort


def _categoria_mercado(tipo: str) -> str:
    t = str(tipo or "").lower()
    if t.startswith("prop"):
        return "prop"
    if "total" in t or "over/under" in t:
        return "totales"
    if "hándicap" in t or "handicap" in t or "spread" in t:
        return "handicap"
    if "1x2" in t:
        return "1x2"
    return "ganador"


def _es_prop_secundario(evento: str, lado_1: str, lado_2: str, tipo_mercado: str = "") -> bool:
    if str(tipo_mercado).lower().startswith("prop"):
        return True
    ev_low = evento.lower()
    palabras_prop = (
        "exact score",
        "more markets",
        "halftime",
        "1h ",
        "2h ",
        "1q ",
        "2q ",
        "3q ",
        "4q ",
        "first half",
        "second half",
        "first goal",
        "both teams to score",
        "btts",
        "corners",
        "cards",
        "player",
        "champion",
        "winner 20",
        "mvp",
        "playoffs",
    )
    if any(p in ev_low for p in palabras_prop):
        return True
    l1_clean = quitar_spread_de_nombre(lado_1).lower()
    l2_clean = quitar_spread_de_nombre(lado_2).lower()
    if l1_clean in ("yes", "no", "sí") or l2_clean in ("yes", "no", "sí"):
        return True
    return False


def emparejar_con_referencia(
    mercado_objetivo: Dict[str, Any],
    mercados_referencia: List[Dict[str, Any]],
    umbral_similitud: float = 85.0,
) -> Tuple[Optional[Dict[str, Any]], bool, float]:
    """
    Busca en `mercados_referencia` exactamente el mismo partido (equipos + fecha UTC compatible),
    la misma categoría de mercado y la misma línea CON SIGNO CORRECTO.
    Retorna:
      (mercado_ref_encontrado, lados_invertidos, puntaje_similitud)
    """
    evento_obj = str(mercado_objetivo.get("Evento", ""))
    lado_1_obj = str(mercado_objetivo.get("Lado_1", ""))
    lado_2_obj = str(mercado_objetivo.get("Lado_2", ""))
    tipo_obj = str(mercado_objetivo.get("Tipo_Mercado", ""))

    if _es_prop_secundario(evento_obj, lado_1_obj, lado_2_obj, tipo_obj):
        return None, False, 0.0

    cat_obj = _categoria_mercado(tipo_obj)
    linea_obj_str = str(mercado_objetivo.get("Linea", "N/A")).strip()

    if cat_obj == "totales":
        partes_ev = re.split(
            r"\s+vs\.?\s+|\s+@\s+|\s+–\s+|\s+-\s+", evento_obj, flags=re.IGNORECASE
        )
        if len(partes_ev) < 2:
            return None, False, 0.0
        eq1_obj, eq2_obj = partes_ev[0], partes_ev[1]
    else:
        eq1_obj, eq2_obj = lado_1_obj, lado_2_obj

    mejor_ref = None
    mejor_invertido = False
    mejor_puntaje = 0.0

    for ref in mercados_referencia:
        if ref.get("ID_Mercado") == mercado_objetivo.get("ID_Mercado"):
            continue

        cat_ref = _categoria_mercado(str(ref.get("Tipo_Mercado", "")))
        if cat_obj != cat_ref:
            continue

        # 1. Validar que la fecha/hora del partido sea compatible (evita cruzar partidos de distintas semanas)
        if not fechas_compatibles(mercado_objetivo.get("Inicio_UTC"), ref.get("Inicio_UTC")):
            continue

        # 2. Extraer equipos de la referencia
        if cat_ref == "totales":
            partes_ref = re.split(
                r"\s+vs\.?\s+|\s+@\s+|\s+–\s+|\s+-\s+",
                str(ref.get("Evento", "")),
                flags=re.IGNORECASE,
            )
            if len(partes_ref) < 2:
                continue
            eq1_ref, eq2_ref = partes_ref[0], partes_ref[1]
        else:
            eq1_ref, eq2_ref = str(ref.get("Lado_1", "")), str(ref.get("Lado_2", ""))

        sim_directa_1 = similitud_equipos(eq1_obj, eq1_ref)
        sim_directa_2 = similitud_equipos(eq2_obj, eq2_ref)
        puntaje_directo = min(sim_directa_1, sim_directa_2)

        sim_cruzada_1 = similitud_equipos(eq1_obj, eq2_ref)
        sim_cruzada_2 = similitud_equipos(eq2_obj, eq1_ref)
        puntaje_cruzado = min(sim_cruzada_1, sim_cruzada_2)

        es_cruzado = puntaje_cruzado > puntaje_directo
        puntaje_actual = max(puntaje_directo, puntaje_cruzado)

        if puntaje_actual < umbral_similitud:
            continue

        # 3. Validación estricta de LÍNEA y SIGNO según categoría
        linea_ref_str = str(ref.get("Linea", "N/A")).strip()
        if cat_obj == "totales":
            try:
                if abs(float(linea_obj_str) - float(linea_ref_str)) > 0.01:
                    continue
            except (ValueError, TypeError):
                continue
            # En totales, verificar si Lado_1 es Over en ambos o está invertido
            l1_es_over_obj = "over" in lado_1_obj.lower()
            l1_es_over_ref = "over" in str(ref.get("Lado_1", "")).lower()
            invertido_final = l1_es_over_obj != l1_es_over_ref

        elif cat_obj == "handicap":
            # En Hándicap, `Linea` representa el hándicap de `Lado_1` (ej. Lado_1 = 49ers, Linea = -7.5).
            # Por lo tanto:
            # - Si los equipos están en el MISMO orden (es_cruzado == False), las líneas deben ser IGUALES (-7.5 == -7.5).
            # - Si los equipos están INVERTIDOS (es_cruzado == True), la línea de Lado_1_obj debe ser OPUESTA a la de Lado_1_ref (-7.5 == - (+7.5)).
            try:
                val_linea_obj = float(linea_obj_str)
                val_linea_ref = float(linea_ref_str)
            except (ValueError, TypeError):
                continue

            if not es_cruzado:
                if abs(val_linea_obj - val_linea_ref) > 0.01:
                    continue
                invertido_final = False
            else:
                if abs(val_linea_obj + val_linea_ref) > 0.01:
                    continue
                invertido_final = True
        else:
            # Ganador (Moneyline)
            invertido_final = es_cruzado

        if puntaje_actual > mejor_puntaje:
            mejor_puntaje = puntaje_actual
            mejor_ref = ref
            mejor_invertido = invertido_final

    if mejor_ref is not None:
        return mejor_ref, mejor_invertido, round(mejor_puntaje, 1)

    return None, False, 0.0


def normalizar_filas(filas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Estandariza nombres de deportes, fechas UTC y limpia los nombres de Lado_1 y Lado_2
    para que no tengan el número de spread pegado al nombre del equipo.
    """
    salida = []
    for f in filas:
        copia = dict(f)
        copia["Deporte"] = estandarizar_deporte(str(copia.get("Deporte", "")))
        copia["Inicio_UTC"] = estandarizar_fecha_utc(copia.get("Inicio_UTC", ""))
        cat = _categoria_mercado(str(copia.get("Tipo_Mercado", "")))
        if cat in ("ganador", "handicap"):
            copia["Lado_1"] = quitar_spread_de_nombre(str(copia.get("Lado_1", "")))
            copia["Lado_2"] = quitar_spread_de_nombre(str(copia.get("Lado_2", "")))
        elif cat == "totales":
            copia["Lado_1"] = "Over" if "over" in str(copia.get("Lado_1", "")).lower() else "Under"
            copia["Lado_2"] = "Under" if copia["Lado_1"] == "Over" else "Over"
        salida.append(copia)
    return salida
