"""
Runner del laboratorio – corre en PythonAnywhere.

Cada corrida: git pull → corre el experimento actual en papel → pide crítica a Gemini →
sube resultados y crítica al repo (rama laboratorio).

Configuración en ~/.lab_env (NO va al repo), una variable por línea:
    GEMINI_API_KEY=xxxxx
    GEMINI_MODEL=gemini-2.5-flash      (opcional)

Uso:
    python3 ~/laboratorio/laboratorio/lab_runner.py            # corre solo a las 00/06/12/18 UTC
    python3 ~/laboratorio/laboratorio/lab_runner.py --forzar   # corre ya
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

LAB = Path(__file__).resolve().parent
REPO = LAB.parent
RAMA = "laboratorio"
HORAS_UTC = {0, 6, 12, 18}
TIMEOUT_EXP = 20 * 60
ENV_FILE = Path.home() / ".lab_env"
LOG = Path.home() / "laboratorio.log"

# Barrera básica (no es un sandbox): el experimento no puede mencionar nada de esto.
PROHIBIDO = [r"\.env\b", r"lab_env", r"private[_ ]?key", r"PRIVATE_KEY", r"mnemonic", r"seed phrase",
             r"firmar_orden", r"py_clob_client", r"post_order", r"create_order", r"/order\b",
             r"os\.environ", r"getenv", r"subprocess", r"os\.system", r"shutil\.rmtree", r"eth_account",
             r"web3", r"\.ssh", r"expanduser", r"Path\.home", r"__import__", r"\beval\(", r"\bexec\("]


def log(msg):
    linea = f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z | {msg}"
    print(linea, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(linea + "\n")


def git(*args, check=True):
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=120)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def leer_env():
    vals = {}
    if ENV_FILE.exists():
        for linea in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in linea and not linea.strip().startswith("#"):
                k, v = linea.split("=", 1)
                vals[k.strip()] = v.strip()
    return vals


def revisar_codigo(codigo):
    return [p for p in PROHIBIDO if re.search(p, codigo, flags=re.IGNORECASE)]


def correr_experimento(ruta):
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONIOENCODING": "utf-8"}
    t0 = time.time()
    try:
        r = subprocess.run([sys.executable, "-I", str(ruta)], cwd=str(LAB), env=env,
                           capture_output=True, text=True, timeout=TIMEOUT_EXP)
        salida, error, codigo = r.stdout, r.stderr, r.returncode
    except subprocess.TimeoutExpired as e:
        salida, error, codigo = (e.stdout or ""), "TIMEOUT", -9
        salida = salida if isinstance(salida, str) else salida.decode("utf-8", "ignore")
    dur = round(time.time() - t0, 1)
    resultado = None
    for linea in reversed(salida.strip().splitlines()):
        try:
            resultado = json.loads(linea)
            break
        except Exception:
            continue
    return {"returncode": codigo, "segundos": dur, "resultado": resultado,
            "stdout_cola": salida[-3000:], "stderr_cola": (error or "")[-3000:]}


def ultimas(carpeta, patron, n=1):
    archivos = sorted(carpeta.glob(patron))
    return archivos[-n:]


def pedir_critica(clave, modelo, reglas, codigo, corrida, bitacora):
    prompt = f"""Sos un revisor cuantitativo escéptico. Evaluás experimentos de trading/apuestas EN PAPEL
de un proyecto con capital de ~US$37. Tu trabajo es encontrar errores, sesgos (sobreajuste, sesgo de
supervivencia, look-ahead, costos subestimados, muestras chicas) y decir si vale la pena seguir.

REGLAS DEL LABORATORIO:
{reglas}

ÚLTIMAS ENTRADAS DE LA BITÁCORA (decisiones de Claude):
{bitacora}

CÓDIGO DEL EXPERIMENTO:
```python
{codigo[:15000]}
```

RESULTADO DE ESTA CORRIDA:
```json
{json.dumps(corrida, ensure_ascii=False)[:8000]}
```

Respondé en español, en markdown, máximo 400 palabras, con estas secciones:
1. **Veredicto:** una sola palabra entre SEGUIR, AJUSTAR, DESCARTAR, PASA.
2. **Errores o sesgos en el código o el método** (concretos, con línea o función si aplica).
3. **Lectura de los números** (¿la muestra alcanza? ¿el resultado es creíble?).
4. **Siguiente paso concreto** (un ajuste o una idea nueva que respete las reglas).
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
    r = requests.post(url, headers={"x-goog-api-key": clave, "Content-Type": "application/json"},
                      json={"contents": [{"parts": [{"text": prompt}]}],
                            "generationConfig": {"temperature": 0.3}}, timeout=120)
    if r.status_code != 200:
        return f"**Error de Gemini** ({r.status_code}): {r.text[:500]}"
    try:
        partes = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in partes).strip()
    except Exception:
        return f"**Respuesta de Gemini sin texto:** {r.text[:500]}"


def main():
    forzar = "--forzar" in sys.argv
    ahora = datetime.now(timezone.utc)
    if not forzar and ahora.hour not in HORAS_UTC:
        return
    log("=== corrida del laboratorio ===")
    git("checkout", RAMA)
    git("pull", "--rebase", "origin", RAMA)

    rel = (LAB / "estado" / "experimento_actual.txt").read_text(encoding="utf-8").strip()
    ruta = (LAB / rel).resolve()
    if LAB not in ruta.parents or not ruta.exists():
        log(f"experimento inválido: {rel}")
        return
    codigo = ruta.read_text(encoding="utf-8")
    sello = ahora.strftime("%Y%m%d_%H%M")
    nombre = ruta.stem

    bloqueos = revisar_codigo(codigo)
    if bloqueos:
        corrida = {"bloqueado": True, "patrones": bloqueos}
        log(f"BLOQUEADO {nombre}: {bloqueos}")
    else:
        log(f"corriendo {nombre}")
        corrida = correr_experimento(ruta)
        r = corrida.get("resultado") or {}
        log(f"fin {nombre}: rc={corrida['returncode']} n={r.get('n_total')} "
            f"fuera={r.get('n_fuera_muestra')} media={r.get('ganancia_media_neta')} pasa={r.get('pasa_umbral')}")
    corrida.update({"experimento": nombre, "archivo": rel, "utc": ahora.isoformat(),
                    "commit": git("rev-parse", "--short", "HEAD")})
    ruta_res = LAB / "resultados" / f"{sello}_{nombre}.json"
    ruta_res.write_text(json.dumps(corrida, ensure_ascii=False, indent=2), encoding="utf-8")

    env = leer_env()
    clave = env.get("GEMINI_API_KEY")
    if clave:
        reglas = (LAB / "REGLAS.md").read_text(encoding="utf-8")
        bit = (LAB / "BITACORA.md").read_text(encoding="utf-8")[-4000:] if (LAB / "BITACORA.md").exists() else ""
        try:
            critica = pedir_critica(clave, env.get("GEMINI_MODEL", "gemini-2.5-flash"), reglas, codigo, corrida, bit)
        except Exception as e:
            critica = f"**Error llamando a Gemini:** {e!r}"
    else:
        critica = "**Sin crítica:** falta GEMINI_API_KEY en ~/.lab_env"
    (LAB / "criticas" / f"{sello}_{nombre}_gemini.md").write_text(
        f"# Crítica de Gemini – {nombre} – {ahora:%Y-%m-%d %H:%M} UTC\n\n{critica}\n", encoding="utf-8")
    log("crítica guardada")

    git("add", "laboratorio/resultados", "laboratorio/criticas", "laboratorio/datos")
    if git("status", "--porcelain", check=False):
        git("-c", "user.name=Laboratorio PA", "-c", "user.email=lab@pythonanywhere",
            "commit", "-m", f"lab: resultados {nombre} {sello}")
        for intento in range(3):
            try:
                git("pull", "--rebase", "origin", RAMA)
                git("push", "origin", RAMA)
                log("subido al repo")
                break
            except RuntimeError as e:
                log(f"push falló ({intento + 1}/3): {e}")
                time.sleep(10)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"ERROR: {e!r}")
        raise
