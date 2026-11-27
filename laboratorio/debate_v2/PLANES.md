# Tablero del Debate V2 · Ineficiencias autónomas

Ronda 3 · 2026-11-27 13:41 UTC · lo mantiene Claude. Puntajes de 0 a 10 según `REGLAS_DEBATE_V2.md` (API 25%, ventaja sin ballenas 25%, rotación con US$300 25%, riesgo de pérdida/ban 25%). Columnas: puntaje más reciente de cada uno (entre paréntesis, el anterior).

Meta de referencia: US$2/día sobre US$300 = 0,67% diario (~240% anual simple). Solo pasan estrategias con rotación alta.

| # | Estrategia | Qué automatiza el bot | Por qué no entran las ballenas | Dry-run (48–72 hs) y umbral | Gemini | Claude | Estado |
|---|---|---|---|---|---|---|---|
| S1 | Cartas graduadas tokenizadas (Courtyard, Collector Crypt) | Listados nuevos vs FMV y ventas externas; compra 20–30% abajo y relista en USDC | Valuación de texto sucio de cartas; tickets de US$15–70 | 72 hs de listados vs FMV; ≥ 3 oportunidades/día con ≥ 10% neto que se revendieron en ≤ 7 días. La recompra al 90% del FMV es solo para cartas de Vending Machines (aceptado por los dos) | 5 (8) | 5 (5) | vivo |
| S2 | Regalos de Telegram en TON (Portals, MRKT, Tonnel, Getgems) | Spreads entre mercados y atributos raros listados a precio piso | Mercado joven, liquidez partida en 4–5 plataformas | 48 hs de spreads netos de fee (~5%); los raros tienen que revenderse en < 24 hs y el margen sobrevivir a −5% de TON | 5 (6) | 4 (5) | vivo |
| C1 | Arbitraje de rescate (vault shares ERC-4626, LSTs chicos, tokens envueltos, stables con PSM 1:1) | Escaneo de pools chicos en L2/Solana; compra bajo el valor de rescate y rescata al instante | Cientos de pools de US$10–100 mil; cada uno pide entender su camino de rescate | 72 hs con `eth_call`, solo rescate instantáneo; ≥ US$2/día simulados, contando solo operaciones con ≥ US$0,30 neto de gas. Absorbe la versión con PSM de G6 (propuesta de Claude) | 6 (7) | 6 (6) | vivo |
| C5 | Relayer de intents cross-chain en transferencias chicas (Across, Relay, deBridge DLN) | Llena depósitos de US$5–100 entre L2 con capital propio; reembolso en ~1–2 hs en la cadena elegida (`repaymentChainId`); rebalanceo de USDC por CCTP | Comisión absoluta chica en rutas secundarias | 72 hs de eventos `FundsDeposited` en Base/Arbitrum/Optimism: comisión neta de gas, quién llenó y en cuántos segundos; ≥ US$2/día en depósitos que habríamos llenado primero. Dato de Gemini: 0,05–0,1% → US$0,01–0,08 por llenado | 7 (–) | 5 (6) | vivo |
| C6 | Comprador de subastas holandesas de fees (Euler Fee Flow y forks) | Valúa la canasta, simula `buy()` y compra bajo el valor neto; vende la canasta al instante | Canastas de decenas a cientos de dólares en L2, llenas de tokens raros | 72 hs indexando subastas en 3–4 L2; ≥ 3 subastas/día con ≥ US$0,70 neto (tras todos los swaps de la canasta) antes que el ganador real | 5 (–) | 4 (5) | vivo |
| G5 | PTs de Pendle en L2 (Arbitrum, Mantle) | Compra PTs con tasa implícita > 40% y vende cuando vuelve a 15–20% | Pools de LRT chicos, irrelevantes para fondos | 72 hs de tasa implícita; ≥ 2 desvíos/día con spread neto ≥ 1% en < 6 hs. Claude: el desvío no puede coincidir con un depeg > 0,5% del subyacente; es apuesta de tasa | 8 | 5 | vivo |
| G6 | Depeg USDC.e vs USDC | Swap al token despegado y espera convergencia o puentea | Spread chico para MEV | 48 hs; ≥ 3 oportunidades/día con spread neto > 0,3%. Claude: par hiperarbitrado y sin rescate instantáneo (puente de 7 días); la versión con PSM pasa a C1 | 7 | 3 | vivo |
| G7 | Incentivos Merkl en pools con poco TVL (Base) | LP en rango ajustado para capturar la mayor parte de los incentivos de la campaña | TVL chico: una ballena diluye sus propios premios | 72 hs indexando Merkl vs TVL en rango; ≥ US$2,5/día. Claude: APR **neto de IL simulado** y pesado por fees generados (sin volumen no hay premio) | 7 | 4 | vivo |
| C7 | Nombres ENS vencidos: fin de la prima holandesa (21 días) vs ofertas de colección | Registra el nombre cuando prima + renta + gas < mejor oferta firmada y le vende al instante | Cruces de US$1–20, valuación semántica de nombres, nicho que no escala | 72 hs con subgraph de ENS + ofertas de OpenSea/Grails; ≥ 2 nombres/día con ≥ US$1,50 neto que nadie registró antes, y ≥ US$2/día | – | 5 | vivo |
| C8 | HyperCore spot (libro) vs AMMs de HyperEVM en tokens de cola larga | Compra en un venue y vende en el otro con inventario en ambos; rebalancea con la transferencia nativa Core ↔ EVM | Profundidad de US$5–50 mil por token; dos stacks técnicos | 72 hs con `info` (`spotMeta`, `l2Book` cada 2 s) + `eth_call` al quoter; ≥ US$2/día en brechas netas ≥ 0,4% que duren ≥ 10 s, sin los 5 tokens más líquidos | – | 5 | vivo |

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
