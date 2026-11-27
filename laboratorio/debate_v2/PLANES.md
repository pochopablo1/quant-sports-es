# Tablero del Debate V2 · Ineficiencias autónomas

Ronda 2 · 2026-11-27 13:03 UTC · lo mantiene Claude. Puntajes de 0 a 10 según `REGLAS_DEBATE_V2.md` (API 25%, ventaja sin ballenas 25%, rotación con US$300 25%, riesgo de pérdida/ban 25%). Columnas: puntaje más reciente de cada uno (entre paréntesis, el anterior).

Meta de referencia: US$2/día sobre US$300 = 0,67% diario (~240% anual simple). Solo pasan estrategias con rotación alta.

| # | Estrategia | Qué automatiza el bot | Por qué no entran las ballenas | Dry-run (48–72 hs) y umbral | Gemini | Claude | Estado |
|---|---|---|---|---|---|---|---|
| S1 | Cartas graduadas tokenizadas (Courtyard, Collector Crypt) | Listados nuevos vs FMV y ventas externas; compra 20–30% abajo y relista en USDC | Valuación de texto sucio de cartas; tickets de US$15–70 | 72 hs de listados vs FMV; ≥ 3 oportunidades/día con ≥ 10% neto que se revendieron en ≤ 7 días. **Dato verificado (ayuda oficial): la recompra al 90% del FMV es solo para cartas sacadas de Vending Machines, no para compras del marketplace** | 8 (7) | 5 (6) | vivo |
| S2 | Regalos de Telegram en TON (Portals, MRKT, Tonnel, Getgems) | Spreads entre mercados y atributos raros listados a precio piso | Mercado joven, liquidez partida en 4–5 plataformas | 48 hs de spreads netos de fee (~5%); los raros tienen que revenderse en < 24 hs y el margen sobrevivir a −5% de TON | 6 (7) | 5 (5) | vivo |
| C1 | Arbitraje de rescate (vault shares ERC-4626, LSTs chicos, tokens envueltos bajo su valor de rescate) | Escaneo de pools chicos en L2/Solana; compra bajo el valor de rescate y rescata | Cientos de pools de US$10–100 mil; cada uno pide entender su camino de rescate | 72 hs con `eth_call`, solo rescate instantáneo; ≥ US$2/día simulados | 7 (–) | 6 (6) | vivo |
| C2 | Acciones tokenizadas 24/7 vs precio real (xStocks y similares) | Desvío del token en DEX vs oráculo Pyth; entra y cierra al converger | Liquidez partida en cadenas y venues | 72 hs con un cierre de mercado; ≥ 5 desvíos/día > 1% neto que convergen en < 24 hs. Claude: fuera de horario es apuesta sobre el gap | 5 (–) | 4 (6) | vivo |
| C3 | Cruce de libros entre marketplaces de NFT chicos (ask < bid) | Compra el listado más barato y le vende al collection offer de otro marketplace | Cruces de US$1–5 que duran minutos, en cadenas distintas | 72 hs con APIs públicas; ≥ 10 cruces/día con ≥ US$0,50 neto (tras royalties) y > 60 s de duración | 5 (–) | 5 (5) | vivo |
| G1 | veNFTs de Aerodrome/Velodrome con descuento | Compra veNFTs rematados bajo el valor de los tokens bloqueados y cobra votos/fees | Capital bloqueado espanta a fondos | 72 hs de ventas de veNFT vs valor de tokens; ≥ 2 oportunidades/día con descuento > 60%. Claude: bloqueo de hasta 4 años = rotación cero; votos ≈ US$0,4/día con US$300 | 8 | 3 | vivo |
| G2 | Runes de Bitcoin entre marketplaces | Compra en un mercado y vende en otro cuando se desincronizan | Manejo de UTXOs; liquidez de US$5–20 mil por Rune | 48 hs de spread neto de fees de red; ≥ US$3/día. Claude: todos los mercados liquidan en Bitcoin L1, no hay "lado rápido" | 7 | 3 | vivo |
| G3 | Puntos pre-TGE en Whales Market vs futuros pre-lanzamiento | Desvíos entre precio de puntos y futuros (Hyperliquid/Aevo); órdenes mal puestas | Mercado OTC, tickets chicos, riesgo percibido alto | 72 hs; desvíos > 15% que duren > 10 min. Claude: tasa puntos→token desconocida; capital atado hasta el TGE | 6 | 4 | vivo |
| G4 | Meta-game en Parallel TCG (Base) | Cruza win-rate de cartas con el floor; compra las que suben de win-rate y relista 20% arriba | Fricción de dominio | 72 hs; ≥ 5 cartas/semana con desvío > 15%. Claude: apuesta direccional; libros finos | 7 | 4 | vivo |
| C5 | Relayer de intents cross-chain en transferencias chicas (Across, Relay, deBridge DLN) | Llena depósitos de US$5–100 entre L2 con capital propio; el protocolo le devuelve el capital en ~1–2 hs más la comisión | Comisión absoluta chica en rutas secundarias; la ventaja de capital no importa | 72 hs de eventos `FundsDeposited` en Base/Arbitrum/Optimism: comisión neta de gas, quién llenó y en cuántos segundos; ≥ US$2/día en depósitos que habríamos llenado primero | – | 6 | vivo |
| C6 | Comprador de subastas holandesas de fees (Euler Fee Flow y forks) | Valúa la canasta de fees, simula `buy()` y compra cuando el precio cae bajo el valor neto; vende la canasta al instante | Canastas de decenas a cientos de dólares en L2, llenas de tokens raros | 72 hs indexando subastas en 3–4 L2; ≥ 3 subastas/día con ≥ US$0,70 neto antes que el ganador real | – | 5 | vivo |

Finalistas: ninguno todavía (hace falta ≥ 8 de los dos en 2 rondas seguidas; máximo 4).

Propuesta de Claude para Pablo (ronda 1, sigue en pie): sumar la restricción 7, **legal en Argentina**, que era obligatoria en el V1. Ya hundió a S5 (Polymarket bloqueado por orden judicial).

## Descartados (≤ 4 de los dos)

- **S3** · Sorare: alineaciones vs ventas fijas viejas. Gemini: "al tacho" (sin número) · Claude: 4. Herramientas de alineaciones ganan la carrera; inventario que se deprecia.
- **S4** · TF2 / Backpack.tf: market making de atributos. Gemini: "al tacho" (sin número) · Claude: 4. Salir a dólares cuesta 10–15%.
- **S5** · Polymarket: market making + Liquidity Rewards. Gemini: muere (sin número) · Claude: 2. Bloqueado en AR por orden judicial (art. 301 bis CP, marzo 2026).
- **C4** · Keeper dust en L2. Gemini: 4 · Claude: 4 (5). Keepers en Rust ya optimizados; techo bajo.
