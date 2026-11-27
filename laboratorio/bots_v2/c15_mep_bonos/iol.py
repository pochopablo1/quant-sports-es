"""Cliente mínimo de la API de InvertirOnline (solo lectura de cotizaciones).

Importante: la documentación oficial está en https://api.invertironline.com (Swagger).
Los nombres de campos de abajo son los que usa la API v2 para cotizaciones con puntas;
si en tu cuenta vienen distintos, corré `python -m c15_mep_bonos.dryrun --probar`, mirá
la respuesta cruda y ajustá `_puntas()`.
"""
from __future__ import annotations

import time

BASE = "https://api.invertironline.com"


class IOL:
    def __init__(self, sesion, usuario: str, clave: str, mercado: str = "bCBA", plazo: str = "t0"):
        self.s = sesion
        self.usuario, self.clave = usuario, clave
        self.mercado, self.plazo = mercado, plazo
        self.token = None
        self.refresh = None
        self.vence = 0.0

    def _login(self):
        if self.refresh and time.time() < self.vence + 600:
            datos = {"refresh_token": self.refresh, "grant_type": "refresh_token"}
        else:
            datos = {"username": self.usuario, "password": self.clave, "grant_type": "password"}
        r = self.s.post(f"{BASE}/token", data=datos, timeout=15)
        if r.status_code != 200 and "refresh_token" in datos:
            self.refresh = None
            return self._login()
        r.raise_for_status()
        j = r.json()
        self.token = j["access_token"]
        self.refresh = j.get("refresh_token")
        self.vence = time.time() + int(j.get("expires_in", 900)) - 60

    def _get(self, ruta: str, params: dict | None = None):
        if not self.token or time.time() > self.vence:
            self._login()
        r = self.s.get(f"{BASE}{ruta}", params=params,
                       headers={"Authorization": f"Bearer {self.token}"}, timeout=15)
        if r.status_code == 401:
            self.token = None
            return self._get(ruta, params)
        r.raise_for_status()
        return r.json()

    def cotizacion_cruda(self, simbolo: str):
        return self._get(f"/api/v2/{self.mercado}/Titulos/{simbolo}/Cotizacion",
                         {"mercado": self.mercado, "simbolo": simbolo,
                          "model.simbolo": simbolo, "model.mercado": self.mercado,
                          "model.plazo": self.plazo})

    def puntas(self, simbolo: str) -> dict | None:
        return _puntas(self.cotizacion_cruda(simbolo))


def _puntas(j) -> dict | None:
    """Mejor punta de compra y de venta: {'bid','bid_q','ask','ask_q'}."""
    p = j.get("puntas") if isinstance(j, dict) else None
    if isinstance(p, dict):
        p = [p]
    if not p:
        return None
    top = p[0]
    try:
        return {"bid": float(top.get("precioCompra") or 0), "bid_q": float(top.get("cantidadCompra") or 0),
                "ask": float(top.get("precioVenta") or 0), "ask_q": float(top.get("cantidadVenta") or 0)}
    except (TypeError, ValueError):
        return None
