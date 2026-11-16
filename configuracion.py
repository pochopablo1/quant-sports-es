"""
Configuración Central, DoH Anti-Bloqueo y Motor Exacto de Comisiones 2026 (`configuracion.py`).
===============================================================================================
Implementa exactamente la tabla de comisiones dinámicas 2026:
  fee_pct_del_stake = k * (1 - p)
Donde:
  - p = precio del contrato/share (1 / cuota_bruta)
  - SX Bet (simples): k = 0.00 (0% Taker, 0% Maker)
  - Overtime Markets: k = 0.00 (0% fee adicional, margen incluido en cuota)
  - Predict.fun (BNB): k = 0.04 (hasta 2% en 50/50 -> 0.04 * p * (1-p) por share; Maker 0%)
  - Myriad (On-Chain): k = 0.02 (Maker 0%)
  - Limitless (Base L2): k = 0.05 (5% * (1 - p) del monto; Maker 0% + rebate)
  - Polymarket (Polygon):
      * Modo Tabla 2026 Conservador: k = 0.05 (5% * (1 - p) del monto; Maker 0% + rebate 15%)
      * Modo On-Chain Real: lee `fee_rate_bps` en vivo de cada contrato (`/book` / `/clob-markets`)
  - Kalshi (EE.UU. CFTC): k = 0.07 (7% * (1 - p) del monto; Maker 0% en la mayoría)
  - Smarkets / Matchbook: 2.0% sobre ganancia neta (Maker 0% en Matchbook)
  - Futuur: 6.0% sobre ganancia neta
"""
import os
from pathlib import Path
import socket
from typing import Dict, Any, Tuple
from dotenv import load_dotenv

# Bypass automático de bloqueo DNS de ISP (ej. 127.9.9.9 en Argentina para Polymarket) usando Cloudflare DoH (1.1.1.1)
_ORIG_GETADDRINFO = socket.getaddrinfo
_CACHE_DOH_IPS: dict[str, str] = {
    "gamma-api.polymarket.com": "3.170.170.96",
    "clob.polymarket.com": "104.18.34.105",
}
_EN_RESOLUCION_DOH = False


def _resolver_via_cloudflare_doh(host: str) -> str | None:
    global _EN_RESOLUCION_DOH
    if host in _CACHE_DOH_IPS:
        return _CACHE_DOH_IPS[host]
    if _EN_RESOLUCION_DOH:
        return None
    _EN_RESOLUCION_DOH = True
    try:
        import requests

        resp = requests.get(
            "https://1.1.1.1/dns-query",
            params={"name": host, "type": "A"},
            headers={"Accept": "application/dns-json"},
            timeout=4,
        )
        if resp.status_code == 200:
            for ans in resp.json().get("Answer", []):
                ip = str(ans.get("data", ""))
                partes = ip.split(".")
                if len(partes) == 4 and all(p.isdigit() for p in partes) and not ip.startswith("127."):
                    _CACHE_DOH_IPS[host] = ip
                    return ip
    except Exception:
        pass
    finally:
        _EN_RESOLUCION_DOH = False
    return None


def _getaddrinfo_con_doh(host, port, family=0, type=0, proto=0, flags=0):
    host_str = str(host)
    if host_str in _CACHE_DOH_IPS:
        return _ORIG_GETADDRINFO(_CACHE_DOH_IPS[host_str], port, family, type, proto, flags)
    try:
        res = _ORIG_GETADDRINFO(host, port, family, type, proto, flags)
        if host_str not in ("localhost", "127.0.0.1", "::1") and res:
            ip_local = str(res[0][4][0])
            if ip_local.startswith("127.") or ip_local == "0.0.0.0":
                ip_real = _resolver_via_cloudflare_doh(host_str)
                if ip_real:
                    return _ORIG_GETADDRINFO(ip_real, port, family, type, proto, flags)
        return res
    except socket.gaierror:
        if host_str not in ("localhost", "127.0.0.1", "::1"):
            ip_real = _resolver_via_cloudflare_doh(host_str)
            if ip_real:
                return _ORIG_GETADDRINFO(ip_real, port, family, type, proto, flags)
        raise


socket.getaddrinfo = _getaddrinfo_con_doh

RUTA_BASE = Path(__file__).resolve().parent
DIRECTORIO_DATOS = RUTA_BASE / "datos"
DIRECTORIO_DATOS.mkdir(parents=True, exist_ok=True)
RUTA_CSV_CONSOLIDADO = DIRECTORIO_DATOS / "mercados_deportivos_consolidado.csv"
RUTA_SQLITE_DB = DIRECTORIO_DATOS / "mercados_deportivos.db"

# Cargar .env local o heredar credenciales de ../quant_sports_es/.env automáticamente
RUTA_ENV_LOCAL = RUTA_BASE / ".env"
RUTA_ENV_SPORTS = RUTA_BASE.parent / "quant_sports_es" / ".env"
if RUTA_ENV_LOCAL.exists():
    load_dotenv(RUTA_ENV_LOCAL, override=True)
elif RUTA_ENV_SPORTS.exists():
    load_dotenv(RUTA_ENV_SPORTS, override=False)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.getenv("CHAT_ID", "").strip()
SX_API_KEY = (os.getenv("SX_API_KEY") or os.getenv("SX_BET_API_KEY") or "").strip()
ODDS_API_KEYS = [k.strip() for k in os.getenv("ODDS_API_KEYS", "").split(",") if k.strip()]

COLUMNAS_ESQUEMA = [
    "Plataforma",
    "Deporte",
    "Liga",
    "Evento",
    "Inicio_UTC",
    "Tipo_Mercado",
    "Linea",
    "Lado_1",
    "Cuota_Taker_1",
    "Liquidez_1_USD",
    "Lado_2",
    "Cuota_Taker_2",
    "Liquidez_2_USD",
    "Overround_Libro_Pct",
    "ID_Mercado",
]

# Presupuesto de referencia por operación de Surebet (suma de las 2 o 3 patas)
STAKE_TOTAL_SUREBET_USD = float(os.getenv("STAKE_TOTAL_SUREBET_USD", "20.0"))
LIQUIDEZ_MINIMA_POR_PATA_USD = float(os.getenv("LIQUIDEZ_MINIMA_POR_PATA_USD", "15.0"))

# Coeficiente k para plataformas donde fee_pct_stake = k * (1 - p)
COEFICIENTE_K_TAKER_2026: Dict[str, float] = {
    "SX Bet": 0.00,
    "Overtime": 0.00,
    "Polymarket": 0.05,      # 5% * (1 - p) según tabla 2026 (2.5% en p=0.50); 0% en contratos con fee_rate_bps=0
    "Limitless": 0.05,       # 5% * (1 - p) desde 14/10/2026 (2.5% en p=0.50)
    "Kalshi": 0.07,          # 7% * (1 - p) (3.5% en p=0.50)
    "Predict.fun": 0.04,     # ~2% en p=0.50
    "Myriad": 0.02,          # ~1% en p=0.50
}

# Comisiones sobre ganancia neta tradicional: (cuota - 1) * (1 - comision)
COMISION_GANANCIA_NETA: Dict[str, float] = {
    "Smarkets": 0.02,
    "Matchbook": 0.02,
    "Betfair": 0.03,
    "Futuur": 0.06,
    "Manifold": 0.02,
}

# Rebates por operar como Maker (Post-Only en el libro de órdenes)
REBATE_MAKER_PCT_STAKE: Dict[str, float] = {
    "Polymarket": 0.0020,
    "Limitless": 0.0015,
    "SX Bet": 0.0000,
    "Kalshi": 0.0000,
    "Predict.fun": 0.0000,
    "Matchbook": 0.0000,
}

ESTADO_ARGENTINA_PLATAFORMA: Dict[str, str] = {
    "SX Bet": "EJECUTABLE_WEB3 (0% Fee Simples | Sin KYC | EIP-712)",
    "Limitless": "EJECUTABLE_WEB3 (Base L2 CLOB | Sin KYC inicial | Maker 0%)",
    "Overtime": "EJECUTABLE_WEB3 (Optimism/Arbitrum AMM | 0% Fee extra | Sin KYC)",
    "Predict.fun": "EJECUTABLE_WEB3 (BNB Chain CLOB | Maker 0%)",
    "Myriad": "EJECUTABLE_WEB3 (On-Chain EIP-712 | Sin KYC)",
    "Polymarket": "EJECUTABLE_CON_RUTEO (Polygon CLOB | Bloqueo IP AR | Maker 0%)",
    "Futuur": "VERIFICAR (USDC | Fee ~6%)",
    "Kalshi": "SOLO_REFERENCIA_CLOB (Requiere KYC Residente EE.UU.)",
    "Smarkets": "SOLO_REFERENCIA_UK (Requiere KYC + Geo UK/EU)",
}


def calcular_overround_pct(cuota_1: float, cuota_2: float) -> float:
    """Calcula el margen (overround) porcentual de un libro de 2 vías."""
    if not cuota_1 or not cuota_2 or cuota_1 <= 1.0 or cuota_2 <= 1.0:
        return 0.0
    return round(((1.0 / cuota_1) + (1.0 / cuota_2) - 1.0) * 100.0, 2)


def calcular_fee_pct_stake_2026(
    plataforma: str,
    precio_share: float,
    es_maker: bool = False,
    usar_tabla_conservadora_poly: bool = True,
    poly_fee_bps_vivo: int = 0,
) -> float:
    p = max(0.01, min(0.99, float(precio_share)))
    if es_maker:
        rebate = REBATE_MAKER_PCT_STAKE.get(plataforma, 0.0)
        return round(-rebate * 100.0, 4)

    if plataforma == "Polymarket" and not usar_tabla_conservadora_poly:
        if poly_fee_bps_vivo <= 0:
            return 0.0
        k_real = float(poly_fee_bps_vivo) / 10000.0
        return round(k_real * (1.0 - p) * 100.0, 4)

    if plataforma in COEFICIENTE_K_TAKER_2026:
        k = COEFICIENTE_K_TAKER_2026[plataforma]
        return round(k * (1.0 - p) * 100.0, 4)

    if plataforma in COMISION_GANANCIA_NETA:
        c_gan = COMISION_GANANCIA_NETA[plataforma]
        return round(c_gan * (1.0 - p) * 100.0, 4)

    return 0.0


def calcular_cuota_efectiva_neta(
    cuota_bruta: float,
    plataforma: str,
    es_maker: bool = False,
    usar_tabla_conservadora_poly: bool = True,
    poly_fee_bps_vivo: int = 0,
) -> Tuple[float, float, float]:
    if cuota_bruta <= 1.005:
        return 1.0, 1.0, 0.0

    p = 1.0 / float(cuota_bruta)
    fee_pct_stake = calcular_fee_pct_stake_2026(
        plataforma=plataforma,
        precio_share=p,
        es_maker=es_maker,
        usar_tabla_conservadora_poly=usar_tabla_conservadora_poly,
        poly_fee_bps_vivo=poly_fee_bps_vivo,
    )
    fee_fraccion = fee_pct_stake / 100.0

    if plataforma in COMISION_GANANCIA_NETA and not es_maker:
        com_gan = COMISION_GANANCIA_NETA[plataforma]
        cuota_neta = 1.0 + (cuota_bruta - 1.0) * (1.0 - com_gan)
        costo_efectivo = 1.0 / cuota_neta
        return round(cuota_neta, 4), round(costo_efectivo, 5), round(fee_pct_stake, 3)

    costo_efectivo = p * (1.0 + fee_fraccion)
    costo_efectivo = max(0.005, min(0.999, costo_efectivo))
    cuota_neta = 1.0 / costo_efectivo
    return round(cuota_neta, 4), round(costo_efectivo, 5), round(fee_pct_stake, 3)
