# Bots V2 · Dry-runs de las 4 finalistas

Estos son los scripts de **validación en frío** de las finalistas del Debate V2 (ver `../debate_v2/FINALISTAS.md`).

> **🔒 Modo lectura, siempre.** Ningún script tiene claves privadas, ni firma transacciones, ni manda órdenes, ni mueve plata. Solo leen precios de APIs públicas (o de tu broker, con permiso de lectura) y anotan qué habría pasado. **No pongas plata real en ninguna estrategia hasta que su reporte diga ✅ PASA.** Y aun así, arrancá con tickets chicos.

| Estrategia | Carpeta | Necesita | Se puede correr ya |
|---|---|---|---|
| **C14** · USDT/ARS entre exchanges | `c14_usdt_ars/` | Nada (APIs públicas) | ✅ Sí |
| **C8** · HyperCore vs HyperEVM | `c8_hypercore_evm/` | Direcciones del DEX en `config.yaml` | ⚠️ Completar 3 direcciones |
| **C1** · Arbitraje de rescate | `c1_rescate/` | Direcciones de Felix/Nerite en `config.yaml` (la ruta de control de Spark ya viene cargada) | ⚠️ Parcial |
| **C15** · MEP entre bonos | `c15_mep_bonos/` | Cuenta en IOL con API + tarifario de bonos | ⚠️ Cuenta y tarifario |

Orden recomendado: **C14 primero** (no necesita nada), después C8 y C1 a medida que completes direcciones, y C15 cuando tengas la API de IOL.

## Instalación en Windows (una sola vez)

1. Instalá **Python 3.11 o más nuevo** desde [python.org](https://www.python.org/downloads/). En el instalador, marcá **"Add python.exe to PATH"**.
2. Bajá esta carpeta: en GitHub, rama `laboratorio` → botón **Code → Download ZIP**, y descomprimilo. (Si usás git: `git clone -b laboratorio https://github.com/pochopablo1/quant-sports-es.git`.)
3. Entrá a `laboratorio\bots_v2` y hacé doble clic en **`instalar.bat`**. Crea el entorno, instala lo necesario, copia `config.ejemplo.yaml` como `config.yaml` y corre los tests (tienen que salir todos en verde).

## Cómo se usa cada uno

Para cada estrategia hay tres `.bat`:

- **`probar_cXX.bat`**: hace una sola pasada y te muestra qué leyó y qué brechas ve en este momento. Usalo primero para confirmar que todo conecta.
- **`correr_cXX.bat`**: arranca el dry-run de verdad (72 hs por defecto) y, al terminar, imprime el reporte. Podés cortarlo con **Ctrl+C**: guarda lo que tenía abierto.
- **`reporte_cXX.bat`**: imprime el reporte con lo juntado hasta ahora (se puede usar mientras el dry-run sigue corriendo, en otra ventana).

Todo queda en la carpeta `datos\`: la base `dryrun_cXX.db`, el log `cXX.log` y el reporte `reporte_cXX.md`.

**Para que corra 72 hs:** en Windows, *Configuración → Sistema → Inicio/apagado y suspensión* → poné "Suspender" en **Nunca** mientras corre. Si se corta, volvé a lanzarlo: los datos anteriores se conservan y el reporte los suma.

## Qué completar en `config.yaml`

Abrilo con el Bloc de notas. Lo marcado con `COMPLETAR` o `VERIFICAR` es tuyo.

### C14 (listo para correr)
- Revisá las comisiones taker de `binance`, `bitso` y `ripioexchange` contra la tabla oficial de cada uno (la de Ripio Trade es un dato de Gemini que no pude confirmar).
- `probar_c14.bat` te lista qué exchanges devuelve CriptoYa. Los que no están en `exchanges:` se toman como **sin API** (no suman al veredicto, solo se informan).

### C8 (HyperCore vs HyperEVM)
- `dex.factory` y `dex.quoter`: dirección del Factory y del QuoterV2 de un DEX de HyperEVM con interfaz Uniswap V3 (por ejemplo, HyperSwap V3), **sacadas de la documentación oficial del DEX**.
- `tokens_quote`: dirección de WHYPE (y de USDT0, si querés) en HyperEVM.
- Después corré `python -m c8_hypercore_evm.dryrun --descubrir` (con el entorno activado) para ver qué tokens y pools encuentra.

### C1 (arbitraje de rescate)
- La ruta `spark-psm-base` ya trae direcciones que **hay que verificar**: corré `python -m c1_rescate.dryrun --verificar` y fijate que cada una diga `código=sí` y el símbolo esperado (USDC, USDS…). Es la ruta de control: casi nunca va a dar oportunidades, sirve para confirmar que el script lee bien.
- Para Nerite (USND) y Felix (feUSD), completá el token, el `CollateralRegistry` y el quoter del DEX donde está el pool, **desde la documentación oficial de cada protocolo**. Las rutas con `COMPLETAR` se desactivan solas.
- Recomendado: RPCs propios gratis (Alchemy o QuickNode) en lugar de los públicos, que limitan las consultas.

### C15 (MEP entre bonos)
1. Abrí una cuenta comitente en InvertirOnline (o usá la tuya) y **habilitá la API** desde la web de IOL.
2. Cargá usuario y clave como variables de entorno (no en archivos). En una ventana de PowerShell:
   ```
   setx IOL_USUARIO "tu_usuario"
   setx IOL_CLAVE "tu_clave"
   ```
   Cerrá y volvé a abrir la ventana para que tomen efecto.
3. Poné en `c15.comision_por_pata` la comisión **real** de tu broker para bonos (fracción: 0,1% = `0.001`). **Si el ciclo de 4 patas cuesta más de 0,4%, el script se niega a correr**: así está definido en las reglas.
4. Corré `probar_c15.bat`: muestra la respuesta cruda de la API para AL30 y AL30D. Si las "puntas interpretadas" salen vacías, mandame esa respuesta y ajusto el lector.

## Cómo leer el reporte

El reporte compara contra los umbrales de `FINALISTAS.md` y da un veredicto **✅ PASA** o **❌ NO PASA**. Las reglas de conteo son conservadoras:

- Una brecha **solo cuenta si dura** el mínimo definido (60 s en C14, 30 s en C15, 10 s en C8, ~2 bloques en C1) y en ese momento sigue dejando el neto mínimo.
- Se cuenta **una sola vez**, con el neto del momento en que cumplió la duración (no el mejor momento).
- Si la misma brecha aparece con varios tamaños de ticket, cuenta solo el mejor (no se suma tres veces la misma plata).
- Ya vienen descontados comisiones, slippage, gas y el costo prorrateado de rebalancear.

Un ✅ no garantiza ganancia: dice que en esas 72 hs la oportunidad existió y era ejecutable en papel. Con plata real aparecen cosas que el dry-run no ve (órdenes que no se llenan, otros bots más rápidos).

## Tests

Con el entorno activado (`.venv\Scripts\activate`), `python -m pytest -q` corre los tests de la matemática de las 4 estrategias, sin conexión a internet.
