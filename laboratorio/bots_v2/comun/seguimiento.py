"""Sigue cada oportunidad a lo largo de varias consultas y mide cuánto dura.

Una oportunidad "cuenta" (entra al P&L simulado) solo si sigue abierta al menos
`min_duracion_s` y en ese momento su neto es >= `min_neto_usd` y >= `min_neto_pct`.
Se cuenta UNA vez por vida: el neto que se suma es el del momento en que cumplió
la duración (no el máximo), que es lo que habría cobrado un bot que tarda eso en
ejecutar. Cuando desaparece, se cierra y se guarda en la base.
"""
from __future__ import annotations


def mejores(ops: list[dict]) -> dict[str, dict]:
    """Una oportunidad por clave: si la misma brecha aparece con varios tamaños de ticket,
    queda la de mayor neto en USD (no se cuenta tres veces la misma plata)."""
    out: dict[str, dict] = {}
    for o in ops:
        if o["clave"] not in out or o["neto_usd"] > out[o["clave"]]["neto_usd"]:
            out[o["clave"]] = o
    return out


class Seguidor:
    def __init__(self, registro, min_duracion_s: float, min_neto_usd: float = 0.0,
                 min_neto_pct: float = 0.0):
        self.registro = registro
        self.min_duracion_s = min_duracion_s
        self.min_neto_usd = min_neto_usd
        self.min_neto_pct = min_neto_pct
        self.abiertas: dict[str, dict] = {}

    def observar(self, ts: float, oportunidades: dict[str, dict]):
        """`oportunidades`: clave -> {neto_usd, neto_pct, tam_usd, grupo, direccion, con_api, detalle}.
        Pasar solo las que tienen neto > 0 (las demás se consideran cerradas)."""
        for clave, op in oportunidades.items():
            ab = self.abiertas.get(clave)
            if ab is None:
                ab = dict(op, clave=clave, inicio=ts, fin=ts, contada=False,
                          neto_max_usd=op["neto_usd"], neto_usd_cumplido=None,
                          neto_pct_cumplido=None)
                self.abiertas[clave] = ab
            ab["fin"] = ts
            ab["neto_max_usd"] = max(ab["neto_max_usd"], op["neto_usd"])
            ab["detalle"] = op.get("detalle", {})
            if (not ab["contada"] and ts - ab["inicio"] >= self.min_duracion_s
                    and op["neto_usd"] >= self.min_neto_usd
                    and op["neto_pct"] >= self.min_neto_pct):
                ab["contada"] = True
                ab["neto_usd_cumplido"] = op["neto_usd"]
                ab["neto_pct_cumplido"] = op["neto_pct"]
                ab["tam_usd"] = op.get("tam_usd", ab.get("tam_usd", 0.0))
        for clave in [c for c in self.abiertas if c not in oportunidades]:
            self._cerrar(clave)

    def cerrar_todo(self):
        for clave in list(self.abiertas):
            self._cerrar(clave)

    def _cerrar(self, clave: str):
        ab = self.abiertas.pop(clave)
        self.registro.oportunidad({
            "clave": clave, "grupo": ab.get("grupo", ""),
            "direccion": ab.get("direccion", ""), "con_api": ab.get("con_api", True),
            "inicio": ab["inicio"], "fin": ab["fin"], "tam_usd": ab.get("tam_usd", 0.0),
            "neto_usd": ab["neto_usd_cumplido"], "neto_pct": ab["neto_pct_cumplido"],
            "neto_max_usd": ab["neto_max_usd"], "contada": ab["contada"],
            "detalle": ab.get("detalle", {}),
        })
