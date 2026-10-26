"""
Configuración central y esquema estandarizado en español para el motor cuantitativo deportivo.
"""
import json
import os
from pathlib import Path
import socket
import urllib.request
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

# Cargar variables de entorno desde el archivo .env en la raíz del proyecto
RUTA_BASE = Path(__file__).resolve().parent
load_dotenv(RUTA_BASE / ".env")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
SX_API_KEY = os.getenv("SX_API_KEY", "")
ODDS_API_KEYS = [k.strip() for k in os.getenv("ODDS_API_KEYS", "").split(",") if k.strip()]

# Directorio de salida para CSVs y base de datos
DIRECTORIO_DATOS = RUTA_BASE / "datos"
DIRECTORIO_DATOS.mkdir(exist_ok=True)

RUTA_CSV_CONSOLIDADO = DIRECTORIO_DATOS / "mercados_deportivos_consolidado.csv"
RUTA_SQLITE_DB = DIRECTORIO_DATOS / "mercados_deportivos.db"

# Columnas obligatorias requeridas por la especificación
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


def calcular_overround_pct(cuota_1: float, cuota_2: float) -> float:
    """
    Calcula el porcentaje de overround (margen del libro) para un mercado de 2 vías.
    Overround % = ((1 / cuota_1 + 1 / cuota_2) - 1) * 100
    """
    if not cuota_1 or not cuota_2 or cuota_1 <= 1.0 or cuota_2 <= 1.0:
        return 0.0
    prob_implicita_total = (1.0 / cuota_1) + (1.0 / cuota_2)
    return round((prob_implicita_total - 1.0) * 100.0, 2)
