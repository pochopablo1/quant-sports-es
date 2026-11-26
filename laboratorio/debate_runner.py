"""
Turno de Gemini en el debate – corre en PythonAnywhere cada 1 hora.

git pull → si el último turno es de Claude, le pasa reglas + tablero + últimos turnos a Gemini →
guarda la respuesta en debate/turnos/<fecha>_gemini.md → git push.

Usa la misma configuración que lab_runner.py: ~/.lab_env con GEMINI_API_KEY (y GEMINI_MODEL opcional).
Uso: python3 ~/laboratorio/laboratorio/debate_runner.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lab_runner import RAMA, git, leer_env, log  # noqa: E402

DEBATE = Path(__file__).resolve().parent / "debate"
TURNOS = DEBATE / "turnos"


MODELOS_RESPALDO = ["gemini-flash-latest", "gemini-3-flash-preview", "gemini-2.5-flash", "gemini-flash-lite-latest"]


def llamar_gemini(clave, modelo, prompt):
    """Prueba el modelo pedido y, si no hay cupo o no existe, los modelos Flash gratuitos."""
    cuerpo = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0.7, "maxOutputTokens": 6000}}
    errores = []
    for m in [modelo] + [x for x in MODELOS_RESPALDO if x != modelo]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
        try:
            r = requests.post(url, params={"key": clave}, json=cuerpo, timeout=180)
        except Exception as e:
            errores.append(f"{m}: {e!r}")
            continue
        if r.status_code == 200:
            try:
                partes = r.json()["candidates"][0]["content"]["parts"]
                texto = "".join(p.get("text", "") for p in partes).strip()
                if texto:
                    return texto, m
            except Exception:
                pass
            errores.append(f"{m}: respuesta sin texto")
        else:
            errores.append(f"{m}: {r.status_code}")
    raise RuntimeError(" | ".join(errores))


def main():
    git("checkout", RAMA)
    git("pull", "--rebase", "origin", RAMA)
    if (DEBATE / "FINALISTAS.md").exists():
        log("debate terminado (FINALISTAS.md existe); nada que hacer")
        return
    turnos = sorted(TURNOS.glob("*.md"))
    if not turnos:
        log("no hay turnos todavía; espero a Claude")
        return
    if turnos[-1].stem.endswith("_gemini"):
        log("el último turno ya es de Gemini; espero a Claude")
        return

    env = leer_env()
    clave = env.get("GEMINI_API_KEY")
    if not clave:
        log("falta GEMINI_API_KEY en ~/.lab_env")
        return
    modelo = env.get("GEMINI_MODEL", "gemini-flash-latest")

    reglas = (DEBATE / "REGLAS_DEBATE.md").read_text(encoding="utf-8")
    tablero = (DEBATE / "PLANES.md").read_text(encoding="utf-8")
    ultimos = "\n\n---\n\n".join(t.read_text(encoding="utf-8") for t in turnos[-4:])
    prompt = f"""Sos Gemini y debatís con Claude para encontrarle a Pablo los mejores planes del mundo
para automatizar algo que genere plata. Sé exigente y concreto: tu trabajo es que solo sobrevivan los
planes realmente buenos, pero también proponer mejores. Nada de elogios vacíos.

REGLAS DEL DEBATE:
{reglas}

TABLERO ACTUAL:
{tablero}

ÚLTIMOS TURNOS (el más nuevo al final, es de Claude):
{ultimos}

Escribí tu turno en español rioplatense, en markdown, máximo 1000 palabras, con estas secciones:
1. **Ataques y defensas**: para cada plan vivo, el argumento más fuerte a favor o en contra (con datos o ejemplos concretos de Argentina cuando puedas).
2. **Planes nuevos** (hasta 4): de rubros o mecanismos distintos entre sí y de lo que ya hay en el tablero (nada de variantes del mismo plan). Buscá ideas originales, también fuera de los nichos ya discutidos. Dales un nombre y explicá qué se automatiza, cómo genera plata y cómo se prueba sin plata.
3. **Puntajes**: una tabla con columnas `Plan | Puntaje Gemini (0-10) | Motivo en una línea`, incluyendo tus planes nuevos (usá los ids P1, P2… del tablero; a los nuevos llamalos G1, G2…).
4. **Pregunta para Claude**: la duda más importante que querés que responda en su próximo turno.
"""
    ahora = datetime.now(timezone.utc)
    try:
        texto, usado = llamar_gemini(clave, modelo, prompt)
    except Exception as e:
        log(f"Gemini falló: {e}")
        return
    sello = ahora.strftime("%Y%m%d_%H%M")
    (TURNOS / f"{sello}_gemini.md").write_text(
        f"# Turno de Gemini · {ahora:%Y-%m-%d %H:%M} UTC · {usado}\n\n{texto}\n", encoding="utf-8")
    log(f"turno de Gemini guardado ({len(texto)} caracteres)")

    git("add", "laboratorio/debate")
    git("-c", "user.name=Gemini via PA", "-c", "user.email=lab@pythonanywhere",
        "commit", "-m", f"debate: turno de Gemini {sello}")
    for intento in range(3):
        try:
            git("pull", "--rebase", "origin", RAMA)
            git("push", "origin", RAMA)
            log("turno subido al repo")
            return
        except RuntimeError as e:
            log(f"push falló ({intento + 1}/3): {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ERROR debate: {e!r}")
        raise
