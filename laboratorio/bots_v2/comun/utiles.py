"""Configuración, HTTP con reintentos y bucle de consulta."""
from __future__ import annotations

import logging
import signal
import time
from pathlib import Path

import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

RAIZ = Path(__file__).resolve().parent.parent

log = logging.getLogger("dryrun")


def configurar_log(nombre: str):
    (RAIZ / "datos").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(),
                  logging.FileHandler(RAIZ / "datos" / f"{nombre}.log", encoding="utf-8")],
    )


def cargar_config() -> dict:
    ruta = RAIZ / "config.yaml"
    if not ruta.exists():
        ruta = RAIZ / "config.ejemplo.yaml"
        log.warning("No hay config.yaml: uso config.ejemplo.yaml (copialo y completalo).")
    with open(ruta, encoding="utf-8") as f:
        return yaml.safe_load(f)


def sesion_http() -> requests.Session:
    s = requests.Session()
    reintentos = Retry(total=3, backoff_factor=1.0,
                       status_forcelist=(429, 500, 502, 503, 504),
                       allowed_methods=("GET", "POST"))
    s.mount("https://", HTTPAdapter(max_retries=reintentos))
    s.headers["User-Agent"] = "laboratorio-quant-dryrun/1.0 (solo lectura)"
    return s


class Parada:
    """Corta el bucle con Ctrl+C o al cumplirse las horas pedidas."""

    def __init__(self, horas: float):
        self.fin = time.time() + horas * 3600
        self.pedida = False
        signal.signal(signal.SIGINT, self._pedir)

    def _pedir(self, *_):
        log.info("Ctrl+C recibido: cierro prolijo y guardo lo abierto…")
        self.pedida = True

    def seguir(self) -> bool:
        return not self.pedida and time.time() < self.fin


def dormir_hasta(proximo: float, parada: Parada):
    while parada.seguir() and time.time() < proximo:
        time.sleep(min(0.5, max(0.0, proximo - time.time())))


def vwap(niveles: list[tuple[float, float]], monto_usd: float, precio_usd: float = 1.0):
    """Precio promedio para mover `monto_usd` recorriendo niveles (precio, cantidad).
    `precio_usd` convierte la moneda de cotización a USD (ej.: ARS por USD).
    Devuelve (precio_promedio, cantidad_total) o None si el libro no alcanza."""
    restante = monto_usd * precio_usd  # en moneda de cotización
    costo = 0.0
    cantidad = 0.0
    for precio, disp in niveles:
        if precio <= 0 or disp <= 0:
            continue
        valor_nivel = precio * disp
        tomar = min(valor_nivel, restante)
        costo += tomar
        cantidad += tomar / precio
        restante -= tomar
        if restante <= 1e-12:
            return costo / cantidad, cantidad
    return None
