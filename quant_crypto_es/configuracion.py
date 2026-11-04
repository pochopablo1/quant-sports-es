"""
Configuración Central del Motor Cuantitativo Cripto + IA (`quant_crypto_es`).
Diseñado para micro-operaciones de alta probabilidad (~68% a 78% Win Rate -> 7 de cada 10)
usando la misma billetera MetaMask / Polygon POS (Polymarket V2 Deposit Wallet + Uniswap V3).
"""
import os
from pathlib import Path
from dotenv import load_dotenv

RUTA_BASE = Path(__file__).resolve().parent
load_dotenv(RUTA_BASE.parent / ".env", override=False)
load_dotenv(RUTA_BASE / ".env", override=True)

DIRECTORIO_DATOS = RUTA_BASE / "datos"
DIRECTORIO_DATOS.mkdir(parents=True, exist_ok=True)

RUTA_CSV_RADAR_CRIPTO = DIRECTORIO_DATOS / "radar_cripto_consolidado.csv"
RUTA_CSV_OPORTUNIDADES_CRIPTO = DIRECTORIO_DATOS / "oportunidades_cripto_accionables.csv"
RUTA_CSV_HISTORIAL_CRIPTO = DIRECTORIO_DATOS / "historial_ejecuciones_cripto.csv"
RUTA_CSV_BACKTEST_CRIPTO = DIRECTORIO_DATOS / "auditoria_backtest_cripto.csv"

# Activos principales monitoreados en el Oráculo de Binance + Uniswap Polygon + Polymarket Cripto
PARES_BINANCE = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "XRP": "XRPUSDT",
    "POL": "POLUSDT",
}

# Direcciones de Tokens ERC-20 en Polygon POS (para Motor 2: Micro-Swaps en Uniswap V3)
TOKENS_POLYGON = {
    "USDC_E": {"address": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174", "decimals": 6},
    "PUSD": {"address": "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB", "decimals": 6},
    "WETH": {"address": "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619", "decimals": 18},
    "WBTC": {"address": "0x1BFD67037B42Cf73acF2047067bd4F2C47D9BfD6", "decimals": 8},
    "WPOL": {"address": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270", "decimals": 18},
}

# Gestión de Capital y Micro-Stakes (Ley de los Grandes Números)
BANKROLL_DIARIO_CRIPTO_USD = 90.0
MICRO_STAKE_MIN_USD = 2.50
MICRO_STAKE_MAX_USD = 5.50
LIQUIDEZ_MINIMA_LIBRO_USD = 50.0

# ═════════════════════════════════════════════════════════════════════════════
# REGLAS MATEMÁTICAS "7 DE 10" (68% - 82% Win Rate Objetivo)
# ═════════════════════════════════════════════════════════════════════════════

# MOTOR CRIPTO 1: Favoritos Digitales en Polymarket Cripto V2 (Black-Scholes + Orderflow + IA)
# - Solo entra cuando la probabilidad matemática real de ganar está entre 66% y 88% (Cuota Justa 1.14 a 1.51)
# - Exige que el libro de Polymarket pague al menos +3.5% de Ventaja Neta (EV) sobre la probabilidad real
PROB_MINIMA_MOTOR_1 = 0.66
PROB_MAXIMA_MOTOR_1 = 0.90
UMBRAL_EV_MOTOR_1_PCT = 3.5
MAX_EV_REALISTA_MOTOR_1_PCT = 35.0

# MOTOR CRIPTO 2: Micro-Scalping de Reversión / Impulso con Filtro IA + Orderflow (Uniswap V3 / Spot)
# - Busca agotamiento estadístico en velas de 15m/1h a favor de la tendencia macro (EMA 200)
# - Take-Profit corto y de alta probabilidad (+0.85% Neto) vs Stop-Loss Técnico (-1.15%) + Salida por Tiempo
TAKE_PROFIT_SCALPING_PCT = 0.85
STOP_LOSS_SCALPING_PCT = 1.15
MAX_VELAS_RETENCION = 8  # Salida automática por tiempo si en 8 velas ya está en ganancia

# API Keys Opcionales para Sentimiento IA con LLM (Funciona 100% gratis sin keys usando Fear&Greed + Lexicon)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
