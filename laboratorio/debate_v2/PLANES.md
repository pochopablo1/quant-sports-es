# Tablero del Debate V2 · Ineficiencias autónomas

Ronda 4 · 2026-11-27 14:08 UTC · lo mantiene Claude. Puntajes de 0 a 10 según `REGLAS_DEBATE_V2.md` (API 25%, ventaja sin ballenas 25%, rotación con US$300 25%, riesgo de pérdida/ban 25%). Columnas: puntaje más reciente de cada uno (entre paréntesis, el anterior).

Meta de referencia: US$2/día sobre US$300 = 0,67% diario (~240% anual simple). Solo pasan estrategias con rotación alta.

| # | Estrategia | Qué automatiza el bot | Por qué no entran las ballenas | Dry-run (48–72 hs) y umbral | Gemini | Claude | Estado |
|---|---|---|---|---|---|---|---|
| C1 | Arbitraje de rescate (vault shares ERC-4626, LSTs chicos, tokens envueltos, stables con PSM 1:1, **contratos de migración V1→V2**) | Escaneo de pools chicos en L2/Solana; compra bajo el valor de rescate y rescata al instante | Cientos de pools de US$10–100 mil; cada uno pide entender su camino de rescate | 72 hs con `eth_call`, solo rescate instantáneo; ≥ US$2/día simulados, contando solo operaciones con ≥ US$0,30 neto de gas. Absorbe la versión con PSM de G6 y (propuesta de Claude) las rutas de migración de G8; tasa de conversión leída on-chain (ej.: penalidad MKR→SKY) | 7 (6) | 7 (6) | vivo |
| C5 | Relayer de intents cross-chain en transferencias chicas (Across, Relay, deBridge DLN) | Llena depósitos de US$5–100 entre L2 con capital propio; reembolso en ~1–2 hs en la cadena elegida (`repaymentChainId`); rebalanceo de USDC por CCTP | Comisión absoluta chica en rutas secundarias | 72 hs de eventos `FundsDeposited` en Base/Arbitrum/Optimism (+ variante de Gemini: rutas de cadenas recién lanzadas): comisión neta de gas, quién llenó y en cuántos segundos; ≥ US$2/día en depósitos que habríamos llenado primero. Comisión 0,05–0,1% → US$0,01–0,08 por llenado | 5 (7) | 5 (5) | vivo |
| G5 | PTs de Pendle en L2 (Arbitrum, Mantle) | Compra PTs con tasa implícita > 40% y vende cuando vuelve a 15–20% | Pools de LRT chicos, irrelevantes para fondos | 72 hs de tasa implícita; ≥ 2 desvíos/día con spread neto ≥ 1% en < 6 hs; el desvío no puede coincidir con depeg > 0,5% del subyacente. Gemini cita PT-rsETH en Mantle (feb. 2026, 18%→34% por 4 hs); Claude pide dirección del mercado y hora para verificar con `api-v2.pendle.finance` | 6 (8) | 5 (5) | vivo |
| C7 | Nombres ENS vencidos: fin de la prima holandesa (21 días) vs ofertas de colección | Registra el nombre cuando prima + renta + gas < mejor oferta firmada y le vende al instante | Cruces de US$1–20, valuación semántica de nombres, nicho que no escala | 72 hs con subgraph de ENS + ofertas de OpenSea/Grails; ≥ 2 nombres/día con ≥ US$1,50 neto que nadie registró antes, y ≥ US$2/día; no opera con gas base > 3 gwei. Disputa: Gemini calcula US$5–15 de gas; Claude, ~320 mil de gas ≈ US$0,30–1,30 con gas de 2026 | 2 (–) | 5 (5) | vivo |
| C8 | HyperCore spot (libro) vs AMMs de HyperEVM en tokens de cola larga | Compra en un venue y vende en el otro con inventario en ambos; rebalancea con la transferencia nativa Core ↔ EVM | Profundidad de US$5–50 mil por token; dos stacks técnicos | 72 hs con `info` (`spotMeta`, `l2Book` cada 2 s) + `eth_call` al quoter; ≥ US$2/día en brechas netas ≥ 0,4% que duren ≥ 10 s, sin los 5 tokens más líquidos | 6 (–) | 6 (5) | vivo |
| G8 | Migración de tokens V1→V2 en pools viejos | Compra V1 con descuento en DEX, migra por el contrato oficial y vende V2 | Pools de US$500–2.000, imposibles para una ballena | 72 hs de contratos de migración activos vs DEXes; ≥ 2 oportunidades/día con margen neto > 1% post-gas. Claude: es una ruta de C1; ganancia por cierre ≈ TVL × descuento² / 8 (pool de US$1.000 con 5% → US$0,10–0,25); gaps de un solo tiro; muchos contratos en L1 | 8 (–) | 4 (–) | vivo |
| G9 | Cola de salida de LSTs (rETH, stETH) | Compra LST con descuento vs valor de rescate y vende a ofertas "a mitad de camino" en agregadores | Capital bloqueado días, poco atractivo para fondos | 72 hs de spread NAV vs mercado en LSTs de L2; spread > 0,5% con volumen de salida comprobado. Claude: en L2 no hay rescate; colas de semanas en L1; descuentos solo en pánico | 7 (–) | 3 (–) | vivo |
| G10 | Rebates de gas en L2 (Blast) + JIT | Liquidez JIT alrededor de swaps grandes para cobrar el rebate de gas | Fondos grandes moverían el mercado | 48 hs midiendo gas de swaps de US$100–500 en Blast; US$2/día en rebates netos. Claude: el rebate es del gas del propio contrato y no supera lo pagado; JIT sin control del orden en L2 | 6 (–) | 2 (–) | vivo |
| C9 | Órdenes límite rezagadas (1inch Limit Order Protocol, KyberSwap) en L2 | Lee el libro público de órdenes, llena las que quedaron por debajo del precio de DEX y vende en la misma tx (atómico) | Órdenes de US$5–200 en tokens de cola larga; los resolvers grandes están en Fusion | 72 hs con Orderbook API de 1inch (Base, Arbitrum) cada 30 s + quoter y `eth_call` de fill+venta; ≥ US$2/día en órdenes con edge ≥ US$0,25 neto que siguieron sin llenar ≥ 15 s | – | 5 (–) | vivo |
| C10 | Arbitraje contra el AMM LLAMMA de mercados chicos de Llamalend (Curve) en L2 | Compara `get_dy` del LLAMMA vs DEX externo y hace las dos patas en una tx atómica | Mercados de US$100 mil–2 millones con garantías raras; no es liquidación (sin bono ni health factor) | 72 hs, cada bloque, `get_dy` para 3 tamaños vs cotización externa + eventos `TokenExchange`; ≥ US$2/día en edges ≥ US$0,30 netos que duren ≥ 2 bloques y nadie cerró antes | – | 5 (–) | vivo |

Finalistas: ninguno todavía (hace falta ≥ 8 de los dos en 2 rondas seguidas; máximo 4).

Propuesta de Claude para Pablo (ronda 1, sigue en pie): sumar la restricción 7, **legal en Argentina**, que era obligatoria en el V1. Ya hundió a S5 (Polymarket bloqueado por orden judicial).

## Descartados (≤ 4 de los dos)

- **S3** · Sorare: alineaciones vs ventas fijas viejas. Gemini: "al tacho" (sin número) · Claude: 4. Herramientas de alineaciones ganan la carrera; inventario que se deprecia.
- **S4** · TF2 / Backpack.tf: market making de atributos. Gemini: "al tacho" (sin número) · Claude: 4. Salir a dólares cuesta 10–15%.
- **S5** · Polymarket: market making + Liquidity Rewards. Gemini: muere (sin número) · Claude: 2. Bloqueado en AR por orden judicial (art. 301 bis CP, marzo 2026).
- **C4** · Keeper dust en L2. Gemini: 4 · Claude: 4 (5). Keepers en Rust ya optimizados; techo bajo.
- **C2** · Acciones tokenizadas 24/7 vs precio real. Gemini: "eliminada, no la defiendo" (antes 5) · Claude: 4. Fuera de horario es apuesta sobre el gap.
- **C3** · Cruce de libros entre marketplaces de NFT chicos. Gemini: "eliminada, no la defiendo" (antes 5) · Claude: 4 (5). Royalties + fees comen el margen.
- **G1** · veNFTs de Aerodrome/Velodrome. Gemini: "mueren hoy" (antes 8) · Claude: 3. Capital bloqueado hasta 4 años; votos ≈ US$0,4/día.
- **G2** · Runes de Bitcoin entre marketplaces. Gemini: "mueren hoy" (antes 7) · Claude: 3. Todo liquida en Bitcoin L1; fees de red.
- **G3** · Puntos pre-TGE en Whales Market. Gemini: "mueren hoy" (antes 6) · Claude: 4. Tasa puntos→token desconocida; capital atado hasta el TGE.
- **G4** · Meta-game en Parallel TCG. Gemini: "mueren hoy" (antes 7) · Claude: 4. Apuesta direccional; libros finos.
- **S1** · Cartas graduadas tokenizadas (Courtyard, Collector Crypt). Gemini: 4 (5) · Claude: 4 (5). Sin recompra garantizada fuera de las Vending Machines, es flipping con rotación de semanas.
- **S2** · Regalos de Telegram en TON. Gemini: 4 (5) · Claude: 4 (4). Sniper bots dominan; solo queda la cola de rarezas, la de peor salida.
- **C6** · Subastas holandesas de fees (Euler Fee Flow). Gemini: 4 (5) · Claude: 4 (4). Canastas de 10 tokens = 10 swaps; pago en EUL.
- **G6** · Depeg USDC.e vs USDC. Gemini: fundida en C1 (antes 7) · Claude: 3. Par hiperarbitrado sin rescate instantáneo; la versión con PSM vive en C1.
- **G7** · Incentivos Merkl en pools con poco TVL. Gemini: eliminada (antes 7) · Claude: 4. Sin volumen no hay fees ni premio; IL y flujo tóxico.
