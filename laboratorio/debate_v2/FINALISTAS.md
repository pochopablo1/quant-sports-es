# Finalistas del Debate V2 · Laboratorio Quant

Cierre: 27/11/2026, 14:00 hora argentina (17:00 UTC). Lo escribió Claude con los puntajes finales de los dos (ronda 9 de Gemini y cierre de Claude, ver `PLANES.md` y `turnos/20261127_1705_claude.md`).

> **⚠️ Todo esto es investigación, en modo lectura.** Cada finalista pasa primero por un **dry-run de 48–72 hs que no firma transacciones, no manda órdenes y no necesita fondos**. No se pone un peso ni un dólar real hasta que su dry-run muestre esperanza positiva **después** de comisiones, slippage y gas. Si el dry-run no pasa el umbral, la idea muere (regla 4).

## Cómo se eligieron

- **Por regla (≥ 8 de los dos en 2 rondas seguidas): ninguna.** La más cerca fue C1 (Gemini 8 en seis rondas seguidas, Claude 7).
- **Completadas por suma** del último puntaje de cada uno, salteando las descartadas:

| Puesto | # | Estrategia | Gemini | Claude | Suma |
|---|---|---|---|---|---|
| 1 | C1 | Arbitraje de rescate (modo taker atómico) | 8 | 7 | 15 |
| 2 | C8 | HyperCore spot vs AMMs de HyperEVM | 6 | 6 | 12 |
| 3 | C15 | "Dólar MEP" entre bonos soberanos por API | 6 | 6 | 12 |
| 4 | C14 | USDT/ARS entre exchanges argentinos con API | 5 | 6 | 11 |

- Afuera por poco: C5, C7, C10, C11, C12 (10 cada una) y G22 (7 + 3 = 10). G23 suma 9.
- **Mercados de predicción:** ninguna finalista lo es, así que la regla de "máximo 1" se cumple sola. La única que había (S5, Polymarket) ya estaba descartada y, además, **no podría ser finalista por razones legales**: Polymarket está bloqueado en Argentina por orden judicial (marzo de 2026). Lo mismo pasa con G14 (Azuro): apuestas sin licencia en AR.
- **Ojo con la lectura:** que no haya finalistas "por regla" significa que ninguna convenció del todo a los dos. Las 4 entran a dry-run para que **los datos decidan**, no porque estén aprobadas.

## Infraestructura común de los 4 dry-runs

- Python 3.11+, un proceso por estrategia, corriendo 72 hs seguidas (para C15, 3 días hábiles) en PythonAnywhere, un VPS chico o la compu de Pablo.
- Cada script guarda cada observación en **SQLite** (`dryrun_<id>.db`) y saca un **reporte diario** (`reporte_<id>_<fecha>.md`) con: oportunidades vistas, cuántas pasan el filtro, P&L neto simulado por día, mediana por operación, duración de las brechas y qué parte del edge sale de un solo par/token.
- **Supuestos conservadores siempre:** se ejecuta al peor precio del libro para el tamaño simulado; si una oportunidad dura menos que el tiempo realista de ejecución, no cuenta; si otro la tomó antes (on-chain), no cuenta.
- Ningún script tiene claves privadas ni permisos de trading. Las API keys de exchanges/brokers, si hacen falta, se crean **solo con permiso de lectura**.

---

## 1. C1 · Arbitraje de rescate (modo taker atómico)

**Qué automatiza el bot.** Busca tokens que cotizan en un DEX por debajo de lo que se puede rescatar en el protocolo emisor, y hace **compra + rescate en la misma transacción** desde un contrato propio. Si el rescate falla o no deja ganancia mínima, toda la transacción revierte: nunca queda inventario. Rutas a vigilar:
- Stables de forks de Liquity V2: **feUSD (Felix, HyperEVM)** y **USND (Nerite, Arbitrum)**. Compra si `precio_DEX < 1 − comisión_de_canje − gas`.
- PSM de Spark en Base (USDC ↔ USDS/sUSDS 1:1). Muy competido: sirve de control.
- Migraciones con tasa fija leída on-chain (ej.: MKR→SKY con su penalidad) y vault shares ERC-4626 con `redeem` instantáneo.

**De dónde sale la plata.** De vendedores apurados que venden el stable o el token por debajo de su valor de rescate en pools chicos (pánico, salidas de farmeo, desequilibrios del pool). El bot cobra la diferencia entre el precio del DEX y el valor de rescate.

**Por qué no entran las ballenas.** Cientos de pools de US$10–100 mil, cada uno con su propio camino de rescate (contratos distintos, comisiones variables como la `baseRate` de Liquity). El techo por evento es chico (0,1–0,5% sobre montos acotados por la liquidez del pool) y aparecen pocas veces: no paga un equipo, sí paga un script.

**Script de dry-run (72 hs).** `dryrun_c1.py`
- **Datos:** cada bloque (o cada 2–4 s), por RPC (`eth_call`, sin firmar):
  - Cotización de venta del DEX para **US$20 / 50 / 100** con el quoter de cada pool (ej.: `QuoterV2.quoteExactInputSingle` en pools tipo Uniswap V3; `get_dy` en Curve; el quoter de KittenSwap/HyperSwap en HyperEVM; Camelot en Arbitrum).
  - Comisión de canje vigente leída del protocolo (en Liquity V2: la función de tasa de canje con decaimiento del `CollateralRegistry`), precio del oráculo de la garantía, `TCR`.
  - Simulación completa de compra + `redeemCollateral` con `eth_call` desde una dirección cualquiera (o `eth_estimateGas`) para confirmar que la ruta ejecuta.
  - Gas: `eth_gasPrice` + estimación de gas; en Base/Optimism, el L1 fee del oráculo `GasPriceOracle` (`0x420000000000000000000000000000000000000F`); en Arbitrum, `NodeInterface.gasEstimateComponents`.
  - **Direcciones de contratos:** solo de la documentación oficial de cada protocolo o de su GitHub, verificadas en el explorador. Ninguna dirección del debate cuenta (hubo una que resultó ser el token UNI).
- **Registra:** bloque, ruta, tamaño, precio DEX, valor de rescate, comisión de canje, gas en USD, neto, y si en el bloque siguiente la brecha seguía abierta o alguien la cerró (eventos `Swap` del pool).
- **Descuenta:** comisión de canje real, slippage real del quoter para el tamaño, gas completo (L2 + L1 fee), y para canjes que pagan en garantía volátil (HYPE, UBTC, WETH), el costo de venderla (otra cotización del quoter).
- El **modo maker** (orden de rango entre 0,985 y 0,99) se registra aparte, solo como información, con una pérdida simulada de US$40 por cada protocolo con incidentes en los últimos 12 meses.

**Métrica y umbral para pasar.**
- P&L neto simulado del **modo taker** ≥ **US$2/día** de promedio en las 72 hs, contando solo operaciones con **≥ US$0,30 neto** que hayan seguido abiertas ≥ 2 bloques.
- Ninguna ruta aporta más del 80% del edge (si no, se evalúa esa ruta sola).
- **Si solo llega a US$2/día sumando el modo maker, no pasa.**

**Riesgos.** Que los eventos sean tan raros que en 72 hs no aparezca ninguno (entonces extender a 2 semanas antes de matarla); carrera con otros bots por la misma brecha; cambios de contratos o pausa del protocolo; riesgo del contrato propio (bug), que se mitiga con tests en fork local antes de cualquier uso real.

**Qué hace Pablo a mano.**
- Para el dry-run: **solo una URL de RPC** de cada red (Arbitrum, Base, HyperEVM; Alchemy/Infura/QuickNode tienen planes gratis; HyperEVM tiene RPC público). No hace falta wallet ni fondos.
- Si pasa: crear una wallet nueva solo para esto (nunca la personal), cargar USDC chico en Arbitrum/HyperEVM, y desplegar el contrato atómico después de probarlo en un fork. Sin KYC (protocolos descentralizados).

---

## 2. C8 · HyperCore spot (libro) vs AMMs de HyperEVM

**Qué automatiza el bot.** Compara el libro spot de HyperCore (el exchange de Hyperliquid) con los pools de los DEX de HyperEVM para el mismo token de cola larga. Con inventario en los dos lados, compra donde está barato y vende donde está caro al mismo tiempo; cada tanto rebalancea con la transferencia nativa entre Core y EVM.

**De dónde sale la plata.** De la diferencia de precio entre dos venues que miran el mismo token pero tienen participantes distintos: traders del libro por un lado, swappers de AMM por otro. Cuando alguien mueve uno, el otro tarda en acomodarse.

**Por qué no entran las ballenas.** Profundidad de US$5–50 mil por token, dos stacks técnicos (API de HyperCore + contratos EVM) y un puente propio de Hyperliquid. Los arbitrajistas grandes miran los tokens top; en la cola larga una brecha de 0,5% sobre US$50 no les mueve la aguja.

**Script de dry-run (72 hs).** `dryrun_c8.py`
- **Datos:**
  - HyperCore: `POST https://api.hyperliquid.xyz/info` con `{"type":"spotMeta"}` (lista de tokens y pares spot) y `{"type":"l2Book","coin":"@<índice>"}` cada 2 s para cada par elegido.
  - HyperEVM: `eth_call` al quoter de los DEX (HyperSwap, KittenSwap u otros con pool del mismo token) para US$20/50, por el RPC `https://rpc.hyperliquid.xyz/evm`.
  - Universo: tokens con par spot en HyperCore **y** pool en HyperEVM, **excluyendo los 5 más líquidos**.
- **Registra:** timestamp, token, precio ejecutable en cada venue para cada tamaño, brecha bruta y neta, cuánto dura, dirección.
- **Descuenta:** comisión taker de HyperCore (tabla oficial vigente; supuesto conservador de nivel base), comisión del pool del AMM y slippage del quoter, gas de HyperEVM, y el costo prorrateado de rebalancear inventario Core ↔ EVM.

**Métrica y umbral para pasar.** ≥ **US$2/día** en brechas netas **≥ 0,4%** que duren **≥ 10 s**, con ≥ 30% en cada dirección (si no, el inventario se acumula de un lado), y que ningún token aporte más del 50% del edge.

**Riesgos.** Riesgo de inventario: se sostienen tokens de cola larga en los dos lados (pueden caer 30% en un día; tope de US$30–50 por token); riesgo de plataforma de Hyperliquid (validadores concentrados, incidentes previos); la transferencia Core ↔ EVM puede cambiar o demorarse.

**Nota legal.** Hyperliquid no está bloqueado en Argentina ni hay orden judicial en su contra (a diferencia de Polymarket), pero tampoco está registrado como PSAV ante la CNV. Usarlo como usuario de un exchange descentralizado no tiene hoy un problema legal claro, pero es una zona gris; las tenencias se declaran igual. No soy abogado: si pasa el dry-run, conviene consultarlo antes de poner plata.

**Qué hace Pablo a mano.** Para el dry-run: nada (la API de `info` es pública). Si pasa: wallet EVM nueva, depositar USDC en Hyperliquid (vía Arbitrum) y pasar una parte a HyperEVM. Sin KYC.

---

## 3. C15 · "Dólar MEP" entre bonos soberanos por API de broker

**Qué automatiza el bot.** El MEP implícito (precio en pesos ÷ precio en dólares) es distinto según el bono. El bot compra MEP por el bono barato (compra X en pesos y vende X en dólares, sufijo D) y lo vende por el caro (compra Y en dólares y vende Y en pesos): **4 patas en contado inmediato** dentro del mismo ALyC. Termina con los mismos pesos y dólares, más la diferencia. Desde abril de 2025 no hay "parking" para personas humanas, así que se puede hacer en el día.

**De dónde sale la plata.** De la dispersión del MEP entre bonos menos líquidos (AL35, GD35, AE38, GD38) frente a los más líquidos, sobre todo en días movidos (licitaciones, datos de inflación). Minoristas que compran MEP "por el bono que tienen a mano" y no por el más barato.

**Por qué no entran las ballenas.** Mercado exclusivamente argentino, cuenta comitente con CUIT, montos chicos en bonos secundarios. Los fondos globales no operan esto. Las mesas locales sí arbitran AL30/GD30: el nicho que queda son los bonos secundarios y los picos de volatilidad.

**Script de dry-run (3 días hábiles, 11 a 17 hs).** `dryrun_c15.py`
- **Datos:** cada 10 s, puntas (bid/ask y cantidades) en pesos y en dólares MEP, contado inmediato, de `AL30, GD30, AL35, GD35, AE38, GD38` (y sus `…D`).
  - Con InvertirOnline: token en `POST https://api.invertironline.com/token`, y cotización con puntas por título en el endpoint `GET /api/v2/bCBA/Titulos/{símbolo}/Cotizacion` (o el de cotización detallada). Hay que habilitar la API en la cuenta.
  - Alternativa: un ALyC que dé acceso a la API de Primary (pyRofex) con market data.
- **Registra:** para cada par de bonos (X, Y): MEP comprando por X = `ask_X$ ÷ bid_XD` y MEP vendiendo por Y = `bid_Y$ ÷ ask_YD`, el cruce neto, el tamaño que soportan las 4 puntas y cuánto dura.
- **Descuenta:** comisión real del broker × 4 patas, derechos de mercado, IVA sobre comisión y derechos, y **1 tick de slippage por pata**.

**Métrica y umbral para pasar.** ≥ **US$2/día hábil** en cruces netos **≥ 0,25%** que duren **≥ 30 s** con **≥ US$50 de profundidad en las 4 puntas**.
- **Compuerta previa (muere sin correr):** si la comisión total del ciclo (4 patas + derechos + IVA) supera **0,4%**. Gemini afirmó que Cocos Capital cobra 0% en bonos soberanos; hay que confirmarlo en su tarifario vigente y confirmar que ese broker da API de trading. Si el broker con comisión baja no tiene API, y el que tiene API cobra caro, muere.
- **Muere** también si más del 70% del edge sale de un solo par de bonos.

**Riesgos.** Riesgo de ejecución entre patas (una se llena y otra no, quedando expuesto al precio del bono); solo ~6 hs por día hábil; que la CNV vuelva a poner parking; límites de la API del broker. Impuestos: el resultado de compraventa de bonos y el MEP tienen tratamiento impositivo propio; conviene consultarlo con un contador antes de operar.

**Qué hace Pablo a mano.** Abrir (si no la tiene) una cuenta comitente en un ALyC con API (KYC con DNI y CUIT), habilitar la API y pasarle al script credenciales que solo lean cotizaciones. Bajar el tarifario oficial de bonos de ese broker y cargarlo en la config del script.

---

## 4. C14 · USDT/ARS entre exchanges argentinos con API

**Qué automatiza el bot.** Con USDT y pesos ya depositados dentro de 2–3 exchanges registrados como PSAV (Binance + Ripio Trade y/o Bitso), compra USDT en el más barato y lo vende en el más caro **al mismo tiempo**. Los USDT se rebalancean entre exchanges por una red barata (Polygon); **los pesos nunca pasan por el banco**: si la brecha va siempre para el mismo lado, la estrategia se frena en vez de rebalancear por banco (regla 5).

**De dónde sale la plata.** De la diferencia de precio del "dólar cripto" entre exchanges locales, que aparece cuando el flujo minorista entra desbalanceado en uno de ellos.

**Por qué no entran las ballenas.** KYC argentino en cada exchange, par exclusivamente local y pesos atrapados en cada plataforma. Los fondos globales no entran; las mesas locales se quedan con las brechas grandes y deja las chicas.

**Script de dry-run (72 hs).** `dryrun_c14.py`
- **Datos:** cada 30 s:
  - CriptoYa: `GET https://criptoya.com/api/usdt/ars/<monto>` para 20, 50 y 80 USDT (`ask`, `totalAsk`, `bid`, `totalBid` por exchange).
  - Libros propios de los exchanges con API de trading: Binance `GET https://api.binance.com/api/v3/depth?symbol=USDTARS`; Ripio Trade (libro de órdenes según `apidocs.ripio.com`); Bitso (libro de USDT/ARS en `api.bitso.com/v3/order_book`, si el par está disponible).
- **Registra:** cada cruce `bid_A − ask_B > 0` entre exchanges **con API de trading**, tamaño que soporta el libro, duración y dirección (A→B o B→A).
- **Descuenta:** comisión taker de las dos patas según la tabla oficial de cada exchange (Bitso en ARS: 0,60% taker / 0,45% maker en el tramo bajo; Ripio Trade y Binance: cargar su tabla vigente), **0,1% de slippage extra**, y el retiro de USDT prorrateado (Polygon ~0,01 USDT; evitar Tron). Se mide también la variante con una pata como orden límite (maker), anotando cuántas veces se habría llenado.

**Métrica y umbral para pasar.** ≥ **US$2/día** en cruces netos **≥ 0,4%** (≥ 0,8% si una pata es Bitso taker) que duren **≥ 60 s**, con **≥ 30% de los cruces en cada dirección**.
- **Muere** si más del 50% del edge sale de exchanges sin API de trading, o si no hay al menos una segunda pata con API además de Binance.

**Riesgos.** Brechas unidireccionales (los pesos se acumulan en un exchange y la estrategia se frena: es la objeción fuerte de Gemini); riesgo de contraparte del exchange (tope de US$100 por exchange); cambios de comisiones o de términos de API; demoras en retiros de USDT. Comprar y vender USDT en PSAV registrados es legal; las ganancias igual se declaran.

**Qué hace Pablo a mano.** Para el dry-run: nada (CriptoYa y los libros son públicos). Si pasa: KYC en los exchanges elegidos, crear API keys **sin permiso de retiro** para el bot, y hacer el depósito inicial de pesos en cada uno (una sola vez, a mano).

---

## Próximos pasos sugeridos

1. Escribir los 4 scripts de dry-run en `laboratorio/debate_v2/dryrun/` (todavía no existen).
2. Correr C8 y C14 primero: no necesitan cuentas ni claves, solo APIs públicas.
3. C1 en paralelo apenas haya URLs de RPC; C15 después de confirmar tarifario y API del broker.
4. A las 72 hs, comparar los reportes contra los umbrales de arriba. **Plata real solo para las que pasen.**
