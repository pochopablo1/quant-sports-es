"""Registro en SQLite de latidos (cada consulta) y oportunidades cerradas."""
import json
import sqlite3
import time
from pathlib import Path

DATOS = Path(__file__).resolve().parent.parent / "datos"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS latidos (
    ts REAL, estrategia TEXT, ok INTEGER, detalle TEXT
);
CREATE TABLE IF NOT EXISTS oportunidades (
    estrategia TEXT,
    clave TEXT,            -- identifica la oportunidad (par, dirección, tamaño)
    grupo TEXT,            -- para medir concentración (token, par de bonos, ruta)
    direccion TEXT,
    con_api INTEGER,       -- 1 si se puede ejecutar por API (C14); 1 por defecto
    inicio REAL, fin REAL, duracion_s REAL,
    tam_usd REAL,
    neto_usd REAL,         -- neto en el momento en que cumplió la duración mínima
    neto_pct REAL,
    neto_max_usd REAL,
    contada INTEGER,       -- 1 si cumplió duración y neto mínimos
    detalle TEXT
);
CREATE TABLE IF NOT EXISTS eventos (
    ts REAL, estrategia TEXT, tipo TEXT, detalle TEXT
);
"""


class Registro:
    def __init__(self, estrategia: str, ruta: Path | None = None):
        DATOS.mkdir(exist_ok=True)
        self.estrategia = estrategia
        self.ruta = ruta or DATOS / f"dryrun_{estrategia}.db"
        self.con = sqlite3.connect(self.ruta)
        self.con.executescript(ESQUEMA)
        self.con.commit()

    def latido(self, ok: bool, detalle: str = ""):
        self.con.execute(
            "INSERT INTO latidos VALUES (?,?,?,?)",
            (time.time(), self.estrategia, int(ok), detalle[:500]),
        )
        self.con.commit()

    def evento(self, tipo: str, detalle: dict):
        self.con.execute(
            "INSERT INTO eventos VALUES (?,?,?,?)",
            (time.time(), self.estrategia, tipo, json.dumps(detalle, default=str)),
        )
        self.con.commit()

    def oportunidad(self, fila: dict):
        self.con.execute(
            "INSERT INTO oportunidades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                self.estrategia, fila["clave"], fila.get("grupo", ""),
                fila.get("direccion", ""), int(fila.get("con_api", True)),
                fila["inicio"], fila["fin"], fila["fin"] - fila["inicio"],
                fila.get("tam_usd", 0.0), fila.get("neto_usd"),
                fila.get("neto_pct"), fila.get("neto_max_usd", 0.0),
                int(fila.get("contada", False)),
                json.dumps(fila.get("detalle", {}), default=str),
            ),
        )
        self.con.commit()
