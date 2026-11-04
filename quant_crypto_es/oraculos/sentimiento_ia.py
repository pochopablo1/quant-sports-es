"""
Oráculo Híbrido de Sentimiento con IA y Noticias Cripto en Tiempo Real.
Combina 3 fuentes sin costo:
1. Índice Oficial Crypto Fear & Greed (`api.alternative.me/fng`).
2. Titulares de noticias cripto en tiempo real (`min-api.cryptocompare.com/data/v2/news/`).
3. Clasificador de Sentimiento Híbrido:
   - Si el usuario configura `GEMINI_API_KEY` o `GROQ_API_KEY` en `.env`, consulta al LLM para puntuar el impacto
     institucional/macro de los titulares en vivo de `-1.00` a `+1.00`.
   - En paralelo (y como motor instantáneo 100% gratuito sin API Key), ejecuta un Analizador Léxico Financiero
     Cuantitativo calibrado para catalizadores cripto (ETF inflows, recortes de tasas, hackeos, liquidaciones, SEC, etc.).
"""
import json
import logging
import re
from typing import Dict, Any, List
import requests

from configuracion import GEMINI_API_KEY, GROQ_API_KEY, PARES_BINANCE

logger = logging.getLogger("OraculoSentimientoIA")

# Léxico cuantitativo ponderado para noticias cripto institucionales (Inglés + Español)
LEXICO_ALCISTA = {
    "etf inflow": 0.45,
    "inflows": 0.35,
    "record inflow": 0.55,
    "bullish": 0.30,
    "surge": 0.30,
    "surges": 0.30,
    "rally": 0.30,
    "rallies": 0.30,
    "breakout": 0.35,
    "all-time high": 0.45,
    "ath": 0.35,
    "adoption": 0.25,
    "approval": 0.40,
    "approved": 0.40,
    "accumulating": 0.35,
    "whale bought": 0.35,
    "treasury": 0.25,
    "rate cut": 0.40,
    "partnership": 0.25,
    "upgrade": 0.25,
    "institutional buying": 0.45,
    "short squeeze": 0.40,
    "rebound": 0.25,
    "gains": 0.20,
    "soars": 0.35,
}

LEXICO_BAJISTA = {
    "hack": -0.65,
    "hacked": -0.65,
    "exploit": -0.65,
    "stolen": -0.60,
    "outflow": -0.35,
    "outflows": -0.35,
    "sec lawsuit": -0.50,
    "subpoena": -0.45,
    "ban": -0.50,
    "crash": -0.50,
    "crashes": -0.50,
    "plunge": -0.40,
    "plunges": -0.40,
    "dump": -0.35,
    "liquidation": -0.30,
    "liquidations": -0.30,
    "bankruptcy": -0.65,
    "insolvent": -0.65,
    "delist": -0.45,
    "bearish": -0.30,
    "sell-off": -0.35,
    "selloff": -0.35,
    "slump": -0.30,
    "tumbles": -0.35,
    "drops": -0.20,
    "fears": -0.25,
}

KEYWORDS_ACTIVOS = {
    "BTC": ("bitcoin", "btc", "ibit", "blackrock", "saylor", "microstrategy"),
    "ETH": ("ethereum", "eth", "vitalik", "ether"),
    "SOL": ("solana", "sol"),
    "XRP": ("ripple", "xrp", "rlusd"),
    "POL": ("polygon", "pol", "matic", "polymarket"),
}


def extraer_fear_and_greed() -> Dict[str, Any]:
    """Obtiene el índice Crypto Fear & Greed actual (0 = Pánico Extremo, 100 = Euforia Extrema)."""
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=2", timeout=6)
        datos = r.json().get("data", [])
        if datos:
            actual = int(datos[0].get("value", 50))
            previo = int(datos[1].get("value", actual)) if len(datos) > 1 else actual
            clasificacion = str(datos[0].get("value_classification", "Neutral"))
            return {
                "valor": actual,
                "previo": previo,
                "delta": actual - previo,
                "clasificacion": clasificacion,
            }
    except Exception as exc:
        logger.warning("No se pudo obtener Fear & Greed Index: %s", exc)
    return {"valor": 50, "previo": 50, "delta": 0, "clasificacion": "Neutral"}


def extraer_titulares_cripto_vivo(limite: int = 30) -> List[Dict[str, str]]:
    """Extrae los últimos titulares cripto en tiempo real desde CryptoCompare News API (pública y gratuita)."""
    titulares: List[Dict[str, str]] = []
    try:
        r = requests.get("https://min-api.cryptocompare.com/data/v2/news/?lang=EN", timeout=8)
        if r.status_code == 200:
            items = r.json().get("Data", [])[:limite]
            for it in items:
                titulares.append(
                    {
                        "titulo": str(it.get("title", "")).strip(),
                        "categorias": str(it.get("categories", "")).upper(),
                        "fuente": str(it.get("source", "")),
                    }
                )
    except Exception as exc:
        logger.warning("No se pudieron extraer titulares de CryptoCompare: %s", exc)
    return titulares


def _puntuar_texto_lexico(texto: str) -> float:
    t_low = texto.lower()
    puntaje = 0.0
    for frase, peso in LEXICO_ALCISTA.items():
        if frase in t_low:
            puntaje += peso
    for frase, peso in LEXICO_BAJISTA.items():
        if frase in t_low:
            puntaje += peso
    return max(-1.0, min(1.0, puntaje))


def _consultar_llm_sentimiento(titulares: List[str]) -> Dict[str, float] | None:
    """Si GEMINI_API_KEY o GROQ_API_KEY está presente en .env, pide puntuación de sentimiento por activo al LLM."""
    if not titulares or (not GEMINI_API_KEY and not GROQ_API_KEY):
        return None

    prompt = (
        "Analiza estos titulares cripto en tiempo real y devuelve ÚNICAMENTE un objeto JSON con puntajes "
        "de sentimiento entre -1.0 (muy bajista/hack/pánico) y +1.0 (muy alcista/adopción/inflows) "
        "para las claves MACRO, BTC, ETH, SOL, XRP, POL:\n"
        + "\n".join(f"- {t}" for t in titulares[:18])
    )
    try:
        if GEMINI_API_KEY:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
            resp = requests.post(
                url,
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=8,
            )
            if resp.status_code == 200:
                txt = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                m = re.search(r"\{.*\}", txt, re.DOTALL)
                if m:
                    return json.loads(m.group(0))
        elif GROQ_API_KEY:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                },
                timeout=8,
            )
            if resp.status_code == 200:
                txt = resp.json()["choices"][0]["message"]["content"]
                m = re.search(r"\{.*\}", txt, re.DOTALL)
                if m:
                    return json.loads(m.group(0))
    except Exception as exc:
        logger.warning("Fallo consulta opcional LLM Sentimiento (usando motor NLP cuantitativo local): %s", exc)
    return None


def analizar_sentimiento_ia_completo() -> Dict[str, Any]:
    """
    Devuelve el estado de Sentimiento IA global y por cada moneda (`BTC`, `ETH`, `SOL`, `XRP`, `POL`),
    incluyendo un detector de 'Cisne Negro / Hackeo' que bloquea compras automáticamente si hay peligro.
    """
    fng = extraer_fear_and_greed()
    noticias = extraer_titulares_cripto_vivo(limite=30)

    # Normalizar Fear & Greed (0..100) a escala (-0.50 .. +0.50) más impulso del día (delta)
    score_fng = ((fng["valor"] - 50.0) / 100.0) + (fng["delta"] * 0.01)
    score_fng = max(-0.75, min(0.75, score_fng))

    puntajes_noticias_activo: Dict[str, List[float]] = {tk: [] for tk in PARES_BINANCE}
    puntajes_macro: List[float] = []
    alerta_cisne_negro = False
    titulares_destacados: List[str] = []

    for item in noticias:
        tit = item["titulo"]
        cat = item["categorias"]
        sc = _puntuar_texto_lexico(tit)
        if sc <= -0.55:
            alerta_cisne_negro = True
        if abs(sc) >= 0.25 and len(titulares_destacados) < 5:
            signo = "🟢" if sc > 0 else "🔴"
            titulares_destacados.append(f"{signo} ({sc:+.2f}) {tit}")

        puntajes_macro.append(sc)
        t_low = tit.lower()
        for tk, kws in KEYWORDS_ACTIVOS.items():
            if tk in cat or any(k in t_low for k in kws):
                puntajes_noticias_activo[tk].append(sc)

    media_noticias_macro = sum(puntajes_macro) / len(puntajes_macro) if puntajes_macro else 0.0
    llm_scores = _consultar_llm_sentimiento([n["titulo"] for n in noticias])

    por_activo: Dict[str, Dict[str, Any]] = {}
    for tk in PARES_BINANCE:
        lista_act = puntajes_noticias_activo[tk]
        media_act = (sum(lista_act) / len(lista_act)) if lista_act else media_noticias_macro
        score_combinado = 0.45 * score_fng + 0.55 * (media_act * 2.2)

        if llm_scores and tk in llm_scores:
            try:
                score_combinado = 0.50 * score_combinado + 0.50 * float(llm_scores[tk])
            except (ValueError, TypeError):
                pass

        score_final = round(max(-1.0, min(1.0, score_combinado)), 4)
        if score_final >= 0.20:
            etiqueta = "ALCISTA_IA"
        elif score_final <= -0.25:
            etiqueta = "BAJISTA_IA"
        else:
            etiqueta = "NEUTRAL_IA"

        por_activo[tk] = {
            "Score_Sentimiento_IA": score_final,
            "Etiqueta_IA": etiqueta,
            "Menciones_Noticias": len(lista_act),
            "Bloqueo_Cisne_Negro": alerta_cisne_negro and score_final < -0.35,
        }

    return {
        "fear_and_greed": fng,
        "alerta_cisne_negro": alerta_cisne_negro,
        "modo_motor_ia": "LLM + NLP Cuantitativo" if llm_scores else "NLP Financiero Cuantitativo + Fear&Greed (0 costo)",
        "titulares_destacados": titulares_destacados,
        "activos": por_activo,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    res = analizar_sentimiento_ia_completo()
    print("Fear & Greed:", res["fear_and_greed"])
    print("Modo IA:", res["modo_motor_ia"])
    for t in res["titulares_destacados"]:
        print("  ", t)
    for k, v in res["activos"].items():
        print(f"  [{k}] -> {v}")
