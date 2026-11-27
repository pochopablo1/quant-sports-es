"""
Corre debate_runner.py cada 5 minutos, para que Gemini conteste rápido aunque PythonAnywhere
solo permita tareas programadas por hora.

Uso (tarea programada por hora en PythonAnywhere):
    python3 /home/USUARIO/laboratorio/laboratorio/debate_loop.py debate_v2 --minutos 55

Para solo después de --hasta (hora UTC). Por defecto: 27/11/2026 17:05 UTC = 14:05 hora argentina.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

AQUI = Path(__file__).resolve().parent


def ahora():
    return datetime.now(timezone.utc)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("carpeta", nargs="?", default="debate_v2")
    p.add_argument("--minutos", type=int, default=55, help="cuánto dura esta corrida")
    p.add_argument("--cada", type=int, default=5, help="minutos entre revisiones")
    p.add_argument("--hasta", default="2026-11-27T17:05:00+00:00", help="no correr después de esta hora (UTC)")
    a = p.parse_args()

    fin_debate = datetime.fromisoformat(a.hasta)
    fin_corrida = time.time() + a.minutos * 60
    while time.time() < fin_corrida:
        if ahora() >= fin_debate:
            print(f"{ahora():%H:%M} UTC · pasó la hora de cierre ({a.hasta}); no hago nada más", flush=True)
            return
        print(f"{ahora():%H:%M} UTC · reviso {a.carpeta}", flush=True)
        subprocess.run([sys.executable, str(AQUI / "debate_runner.py"), a.carpeta])
        restante = fin_corrida - time.time()
        if restante <= 0:
            break
        time.sleep(min(a.cada * 60, restante))


if __name__ == "__main__":
    main()
