"""Reporte de un dry-run y veredicto contra los umbrales de FINALISTAS.md.

Uso (desde la carpeta bots_v2):
    python reporte.py c14        # imprime y guarda datos/reporte_c14.md
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from comun.registro import DATOS
from comun.utiles import cargar_config

AR = timezone(timedelta(hours=-3))


def analizar(estrategia: str, cfg_rep: dict, ruta_db=None) -> tuple[str, bool]:
    ruta_db = ruta_db or DATOS / f"dryrun_{estrategia}.db"
    if not ruta_db.exists():
        return f"# Reporte {estrategia}\n\nNo hay datos: todavía no corriste el dry-run de {estrategia}.\n", False
    con = sqlite3.connect(ruta_db)
    lat = con.execute("SELECT MIN(ts), MAX(ts), COUNT(*), SUM(ok) FROM latidos").fetchone()
    if not lat or not lat[2]:
        return f"# Reporte {estrategia}\n\nSin datos todavía.\n", False
    t_ini, t_fin, n_lat, n_ok = lat
    filas = con.execute(
        "SELECT grupo, direccion, con_api, inicio, duracion_s, neto_usd, neto_pct, contada FROM oportunidades"
    ).fetchall()
    toques = con.execute("SELECT COUNT(*) FROM eventos WHERE tipo='maker_toque'").fetchone()[0]

    horas = (t_fin - t_ini) / 3600
    dias = max(horas / 24, 1e-9)
    if cfg_rep.get("por_dia_habil"):  # C15: solo hay latidos en horario de mercado
        fechas = {datetime.fromtimestamp(r[0], AR).date() for r in con.execute("SELECT ts FROM latidos")}
        dias = max(len(fechas), 1)
    contadas = [f for f in filas if f[7] and f[2]]          # cumplen duración/neto y tienen API
    sin_api = [f for f in filas if f[7] and not f[2]]
    pnl = sum(f[5] for f in contadas)
    pnl_dia = pnl / dias

    por_dia = defaultdict(float)
    for f in contadas:
        por_dia[datetime.fromtimestamp(f[3], AR).date().isoformat()] += f[5]
    por_grupo = Counter()
    for f in contadas:
        por_grupo[f[0]] += f[5]
    conc = (max(por_grupo.values()) / pnl) if pnl > 0 else 0.0
    dirs = Counter(f[1] for f in contadas)
    edge_sin_api = sum(f[5] for f in sin_api)
    share_sin_api = edge_sin_api / (edge_sin_api + pnl) if (edge_sin_api + pnl) > 0 else 0.0

    checks = []
    checks.append((f"P&L neto simulado ≥ US${cfg_rep['meta_usd_dia']}/día", pnl_dia >= cfg_rep["meta_usd_dia"],
                   f"US${pnl_dia:.2f}/día"))
    if "max_concentracion" in cfg_rep:
        checks.append((f"Ningún grupo aporta > {cfg_rep['max_concentracion']:.0%} del edge",
                       conc <= cfg_rep["max_concentracion"], f"máx {conc:.0%}"))
    if "min_share_direccion" in cfg_rep:
        # Agrupa direcciones opuestas por par (A->B vs B->A)
        lados = Counter()
        for d, n in dirs.items():
            a, _, b = d.partition("->")
            lados["ida" if a < b else "vuelta"] += n
        tot = sum(lados.values())
        menor = min(lados.get("ida", 0), lados.get("vuelta", 0)) / tot if tot else 0.0
        checks.append((f"≥ {cfg_rep['min_share_direccion']:.0%} de los cruces en cada dirección",
                       menor >= cfg_rep["min_share_direccion"], f"lado menor {menor:.0%}"))
    if "max_share_sin_api" in cfg_rep:
        checks.append((f"≤ {cfg_rep['max_share_sin_api']:.0%} del edge en exchanges sin API",
                       share_sin_api <= cfg_rep["max_share_sin_api"], f"{share_sin_api:.0%}"))
    if horas < cfg_rep.get("horas_minimas", 48):
        checks.append((f"Al menos {cfg_rep.get('horas_minimas', 48)} hs de datos", False, f"{horas:.1f} hs"))
    pasa = all(ok for _, ok, _ in checks)

    netos = [f[5] for f in contadas]
    out = [f"# Reporte dry-run {estrategia}",
           "",
           f"Período: {datetime.fromtimestamp(t_ini, AR):%d/%m %H:%M} → {datetime.fromtimestamp(t_fin, AR):%d/%m %H:%M} (hora AR), {horas:.1f} hs.",
           f"Consultas: {n_lat} ({(n_ok or 0) / n_lat:.0%} sin errores).",
           "",
           f"**Veredicto: {'✅ PASA' if pasa else '❌ NO PASA'}**",
           "",
           "| Condición | Cumple | Valor |", "|---|---|---|"]
    out += [f"| {n} | {'sí' if ok else 'no'} | {v} |" for n, ok, v in checks]
    out += ["",
            f"- Oportunidades vistas (neto > 0 en algún momento): {len(filas)}",
            f"- Que cuentan (duraron lo mínimo, con neto mínimo y con API): {len(contadas)}",
            f"- P&L neto simulado total: US${pnl:.2f}",
            f"- Mediana por operación: US${statistics.median(netos):.3f}" if netos else "- Mediana por operación: –",
            f"- Duración mediana de las que cuentan: {statistics.median([f[4] for f in contadas]):.0f} s" if contadas else "",
            ]
    if toques:
        out.append(f"- Toques del rango maker (solo informativo, no suma al veredicto): {toques}")
    out += ["", "## P&L por día (AR)", "", "| Día | US$ |", "|---|---|"]
    out += [f"| {d} | {v:.2f} |" for d, v in sorted(por_dia.items())]
    out += ["", "## Top grupos", "", "| Grupo | US$ |", "|---|---|"]
    out += [f"| {g} | {v:.2f} |" for g, v in por_grupo.most_common(10)]
    out += ["", "## Direcciones", ""] + [f"- {d}: {n}" for d, n in dirs.most_common()]
    out += ["", "_Dry-run en modo lectura: no se operó. Un PASA habilita a pensar en plata real con tickets chicos, no la garantiza._"]
    return "\n".join(x for x in out if x is not None) + "\n", pasa


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("c1", "c8", "c14", "c15"):
        sys.exit("Uso: python reporte.py c1|c8|c14|c15")
    e = sys.argv[1]
    cfg = cargar_config()[e]["reporte"]
    texto, _ = analizar(e, cfg)
    (DATOS / f"reporte_{e}.md").write_text(texto, encoding="utf-8")
    print(texto)
    print(f"(guardado en {DATOS / f'reporte_{e}.md'})")


if __name__ == "__main__":
    main()
