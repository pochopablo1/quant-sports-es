"""
Oráculo Cuantitativo de Flujo de Órdenes (Orderflow) y Volatilidad en Tiempo Real (Binance Spot + Futuros).
Extrae sin API Key (100% gratuito):
1. Precio Spot exacto al milisegundo ($S_0$).
2. Desbalance del Libro de Órdenes (Orderbook Imbalance - OBI) en las primeras 25 puntas Bid/Ask.
3. Flujo Agresivo Comprador vs Vendedor (Taker Buy Volume Ratio y CVD en velas de 15m y 1h).
4. Volatilidad Realizada Horaria y Anualizada (σ para modelo Black-Scholes Digital).
5. Indicadores de Agotamiento Estadístico: Connors RSI(2), RSI(14), Z-Score(20) y Tendencia EMA(50/200).
6. Tasa de Fondeo (Funding Rate) de Futuros Perpetuos.
"""
import logging
import math
from typing import Dict, Any, List
import numpy as np
import pandas as pd
import requests

from configuracion import PARES_BINANCE

logger = logging.getLogger("OraculoBinanceOrderflow")

URLS_BINANCE_SPOT = [
    "https://api.binance.com/api/v3",
    "https://api1.binance.com/api/v3",
    "https://data-api.binance.vision/api/v3",
]
URL_BINANCE_FUTURES = "https://fapi.binance.com/fapi/v1"


def _get_binance_spot(endpoint: str, params: Dict[str, Any], timeout: int = 8) -> Any:
    """Consulta los endpoints de Binance Spot con rotación automática a `data-api.binance.vision`."""
    ultimo_err = None
    for base in URLS_BINANCE_SPOT:
        try:
            r = requests.get(f"{base}{endpoint}", params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
        except Exception as exc:
            ultimo_err = exc
    raise RuntimeError(f"Error consultando Binance Spot {endpoint}: {ultimo_err}")


def calcular_rsi_serie(cierres: pd.Series, periodo: int = 14) -> pd.Series:
    """Calcula el RSI de Wilder para cualquier período (ej. RSI(2) de Connors o RSI(14))."""
    delta = cierres.diff()
    ganancia = delta.clip(lower=0.0)
    perdida = -delta.clip(upper=0.0)
    media_gan = ganancia.ewm(alpha=1.0 / periodo, min_periods=periodo, adjust=False).mean()
    media_per = perdida.ewm(alpha=1.0 / periodo, min_periods=periodo, adjust=False).mean()
    rs = media_gan / media_per.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


def descargar_velas_historicas(simbolo_par: str, intervalo: str = "15m", limite: int = 250) -> pd.DataFrame:
    """
    Descarga velas históricas reales de Binance (`klines`) incluyendo el volumen comprador Taker
    (`taker_buy_base`) para medir presión institucional real.
    """
    datos = _get_binance_spot("/klines", {"symbol": simbolo_par, "interval": intervalo, "limit": limite})
    filas = []
    for k in datos:
        vol_total = float(k[5])
        vol_taker_buy = float(k[9])
        vol_taker_sell = max(0.0, vol_total - vol_taker_buy)
        filas.append(
            {
                "timestamp_ms": int(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": vol_total,
                "quote_volume_usd": float(k[7]),
                "trades": int(k[8]),
                "taker_buy_vol": vol_taker_buy,
                "taker_sell_vol": vol_taker_sell,
                "cvd_delta": vol_taker_buy - vol_taker_sell,
            }
        )
    df = pd.DataFrame(filas)
    if df.empty:
        return df

    df["ret_log"] = np.log(df["close"] / df["close"].shift(1)).fillna(0.0)
    df["ema_20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema_50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema_200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["std_20"] = df["close"].rolling(20).std().bfill()
    df["z_score_20"] = ((df["close"] - df["ema_20"]) / df["std_20"].replace(0, np.nan)).fillna(0.0)
    df["rsi_2"] = calcular_rsi_serie(df["close"], periodo=2)
    df["rsi_14"] = calcular_rsi_serie(df["close"], periodo=14)
    df["taker_buy_ratio"] = (df["taker_buy_vol"] / df["volume"].replace(0, np.nan)).fillna(0.5)
    return df


def extraer_orderbook_imbalance(simbolo_par: str, niveles: int = 25) -> Dict[str, float]:
    """
    Calcula el Orderbook Imbalance (OBI) en las primeras `niveles` puntas del libro de Binance:
      OBI = (Vol_Bid_USD - Vol_Ask_USD) / (Vol_Bid_USD + Vol_Ask_USD)  en [-1.0, +1.0]
    Un OBI > +0.15 indica fuerte pared compradora absorbiendo ventas.
    """
    try:
        libro = _get_binance_spot("/depth", {"symbol": simbolo_par, "limit": niveles})
        bids = libro.get("bids", [])[:niveles]
        asks = libro.get("asks", [])[:niveles]
        if not bids or not asks:
            return {"obi": 0.0, "spread_bps": 0.0, "bid_usd": 0.0, "ask_usd": 0.0}

        mejor_bid = float(bids[0][0])
        mejor_ask = float(asks[0][0])
        mid = (mejor_bid + mejor_ask) / 2.0
        spread_bps = ((mejor_ask - mejor_bid) / mid) * 10000.0 if mid > 0 else 0.0

        # Ponderar más los niveles cercanos al precio actual (decay exponencial suave)
        bid_usd = sum(float(p) * float(q) * math.exp(-0.08 * i) for i, (p, q) in enumerate(bids))
        ask_usd = sum(float(p) * float(q) * math.exp(-0.08 * i) for i, (p, q) in enumerate(asks))
        total_usd = bid_usd + ask_usd
        obi = ((bid_usd - ask_usd) / total_usd) if total_usd > 0 else 0.0

        return {
            "obi": round(obi, 4),
            "spread_bps": round(spread_bps, 2),
            "bid_usd": round(bid_usd, 2),
            "ask_usd": round(ask_usd, 2),
        }
    except Exception as exc:
        logger.warning("No se pudo extraer depth para %s: %s", simbolo_par, exc)
        return {"obi": 0.0, "spread_bps": 0.0, "bid_usd": 0.0, "ask_usd": 0.0}


def extraer_funding_rate(simbolo_par: str) -> float:
    """Obtiene la tasa de fondeo actual (%) en Binance Futures si está disponible."""
    try:
        r = requests.get(f"{URL_BINANCE_FUTURES}/premiumIndex", params={"symbol": simbolo_par}, timeout=4)
        if r.status_code == 200:
            datos = r.json()
            return round(float(datos.get("lastFundingRate", 0.0)) * 100.0, 4)
    except Exception:
        pass
    return 0.0


def extraer_estado_orderflow_completo() -> Dict[str, Dict[str, Any]]:
    """
    Extrae la radiografía cuantitativa completa en tiempo real de todos los activos (`BTC`, `ETH`, `SOL`, `XRP`, `POL`).
    """
    resultado: Dict[str, Dict[str, Any]] = {}
    for ticker, par in PARES_BINANCE.items():
        try:
            df_15m = descargar_velas_historicas(par, intervalo="15m", limite=220)
            if df_15m.empty:
                continue

            ult = df_15m.iloc[-1]
            precio_actual = float(ult["close"])

            # Volatilidad realizada en ventana de 24h (96 velas de 15m)
            ret_24h = df_15m["ret_log"].tail(96)
            sigma_15m = float(ret_24h.std()) if len(ret_24h) > 10 else 0.005
            sigma_horaria = sigma_15m * math.sqrt(4.0)
            sigma_diaria = sigma_horaria * math.sqrt(24.0)
            sigma_anual = sigma_diaria * math.sqrt(365.0)

            # Flujo comprador agresivo reciente (últimas 4 velas de 15m = 1h y última vela de 15m)
            ult_4 = df_15m.tail(4)
            vol_1h = float(ult_4["volume"].sum())
            taker_buy_ratio_1h = float(ult_4["taker_buy_vol"].sum() / vol_1h) if vol_1h > 0 else 0.50
            taker_buy_ratio_15m = float(ult["taker_buy_ratio"])

            # Cambio porcentual 1h y 24h
            precio_hace_1h = float(df_15m["close"].iloc[-5]) if len(df_15m) >= 5 else precio_actual
            precio_hace_24h = float(df_15m["close"].iloc[-97]) if len(df_15m) >= 97 else float(df_15m["close"].iloc[0])
            cambio_1h_pct = ((precio_actual / precio_hace_1h) - 1.0) * 100.0
            cambio_24h_pct = ((precio_actual / precio_hace_24h) - 1.0) * 100.0

            ema_50 = float(ult["ema_50"])
            ema_200 = float(ult["ema_200"])
            if precio_actual > ema_50 > ema_200:
                regimen_tendencia = "ALCISTA_FUERTE"
            elif precio_actual > ema_200:
                regimen_tendencia = "ALCISTA_MODERADA"
            elif precio_actual < ema_50 < ema_200:
                regimen_tendencia = "BAJISTA_FUERTE"
            else:
                regimen_tendencia = "RANGO_LATERAL"

            info_libro = extraer_orderbook_imbalance(par, niveles=25)
            funding_pct = extraer_funding_rate(par)

            # Puntaje compuesto de presión de Orderflow (-1.0 a +1.0)
            # Combina OBI del libro en vivo + Taker Buy Ratio 15m + Taker Buy Ratio 1h
            presion_taker = ((taker_buy_ratio_15m - 0.50) * 3.0) + ((taker_buy_ratio_1h - 0.50) * 2.0)
            score_orderflow = max(-1.0, min(1.0, round(0.55 * info_libro["obi"] + 0.45 * presion_taker, 4)))

            resultado[ticker] = {
                "Ticker": ticker,
                "Par_Binance": par,
                "Precio_Spot": round(precio_actual, 4 if precio_actual < 10 else 2),
                "Cambio_1h_Pct": round(cambio_1h_pct, 2),
                "Cambio_24h_Pct": round(cambio_24h_pct, 2),
                "Regimen_Tendencia": regimen_tendencia,
                "EMA_50": round(ema_50, 4 if precio_actual < 10 else 2),
                "EMA_200": round(ema_200, 4 if precio_actual < 10 else 2),
                "RSI_2_Connors": round(float(ult["rsi_2"]), 2),
                "RSI_14": round(float(ult["rsi_14"]), 2),
                "Z_Score_20": round(float(ult["z_score_20"]), 2),
                "OBI_25_Niveles": info_libro["obi"],
                "Liquidez_Bid_Top25_USD": info_libro["bid_usd"],
                "Liquidez_Ask_Top25_USD": info_libro["ask_usd"],
                "Taker_Buy_Ratio_15m": round(taker_buy_ratio_15m, 4),
                "Taker_Buy_Ratio_1h": round(taker_buy_ratio_1h, 4),
                "Funding_Rate_Pct": funding_pct,
                "Sigma_Horaria": round(sigma_horaria, 5),
                "Sigma_Diaria": round(sigma_diaria, 5),
                "Sigma_Anualizada": round(sigma_anual, 4),
                "Score_Orderflow": score_orderflow,
            }
        except Exception as exc:
            logger.error("Error procesando oráculo Binance para %s: %s", ticker, exc)

    return resultado


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    datos = extraer_estado_orderflow_completo()
    for tk, info in datos.items():
        print(f"[{tk}] Spot=${info['Precio_Spot']} | Tendencia={info['Regimen_Tendencia']} | RSI2={info['RSI_2_Connors']} | OBI={info['OBI_25_Niveles']} | ScoreFlow={info['Score_Orderflow']}")
