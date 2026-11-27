# Tablero del Debate V2 · Ineficiencias autónomas

Ronda 1 · 2026-11-27 12:38 UTC · lo mantiene Claude. Puntajes de 0 a 10 según `REGLAS_DEBATE_V2.md` (API 25%, ventaja sin ballenas 25%, rotación con US$300 25%, riesgo de pérdida/ban 25%). Columnas: puntaje más reciente de cada uno (entre paréntesis, el anterior).

Meta de referencia: US$2/día sobre US$300 = 0,67% diario (~240% anual simple). Solo pasan estrategias con rotación alta.

| # | Estrategia | Qué automatiza el bot | Por qué no entran las ballenas | Dry-run (48–72 hs) y umbral | Gemini | Claude | Estado |
|---|---|---|---|---|---|---|---|
| S1 | Cartas graduadas tokenizadas (Courtyard, Collector Crypt) | Listados nuevos vs FMV y ventas externas; compra 20–30% abajo y relista en USDC | Valuación de texto sucio de cartas; tickets de US$15–70 | 72 hs de listados vs FMV y reventa en 7 días; ≥ 3 oportunidades/día con ≥ 10% neto que se vendieron. Confirmar si la recompra al ~90% del FMV aplica a compras del marketplace | 7 | 6 | vivo |
| S2 | Regalos de Telegram en TON (Portals, MRKT, Tonnel, Getgems) | Spreads entre mercados y atributos raros listados a precio piso | Mercado joven, liquidez partida en 4–5 plataformas | 48 hs de spreads netos de fee (~5%) y tiempos de reventa; el margen tiene que sobrevivir a −5% de TON | 7 | 5 | vivo |
| S3 | Sorare: alineaciones vs ventas fijas viejas | Eventos de la API GraphQL vs alineaciones confirmadas | Ligas secundarias; chico para mesas grandes | 72 hs: suplentes confirmados con cartas ≥ 15% abajo del precio post-anuncio | 6 | 4 | vivo |
| S4 | TF2: market making de atributos (Backpack.tf) | Compra/venta 24/7 de ítems con atributos combinados | Bots open-source pelean centavos en ítems lisos | 48 hs de spread neto en 30 ítems, descontando pasar llaves a USDC (10–15%) | 6 | 4 | vivo |
| S5 | Polymarket: market making en libros chicos + Liquidity Rewards | Cotiza bid/ask en mercados lentos con `py-clob-client` | Techo de US$5–15/día | 72 hs de paper trading con llenado realista | 7 | 2 | vivo (Claude: bloqueado en AR por orden judicial, marzo 2026) |
| C1 | Arbitraje de rescate (vault shares ERC-4626, LSTs chicos, tokens envueltos bajo su valor de rescate) | Escaneo de pools chicos; compra bajo el valor de rescate y rescata | Cientos de pools de US$10–100 mil; cada uno pide entender su camino de rescate | 72 hs con `eth_call`, solo rescate instantáneo; ≥ US$2/día simulados | – | 6 | vivo |
| C2 | Acciones tokenizadas 24/7 vs precio real (xStocks y similares) | Desvío del token en DEX vs oráculo Pyth; entra y cierra al converger | Liquidez partida en cadenas y venues; pools de US$50–500 mil | 72 hs con un cierre de mercado; ≥ 5 desvíos/día > 1% neto que convergen en < 24 hs | – | 6 | vivo |
| C3 | Cruce de libros entre marketplaces de NFT chicos (ask < bid) | Compra el listado más barato y le vende al collection offer de otro marketplace | Cruces de US$1–5 que duran minutos, en cadenas distintas | 72 hs con APIs públicas; ≥ 10 cruces/día con ≥ US$0,50 neto y > 60 s de duración | – | 5 | vivo |
| C4 | Recompensas de llamador ("keeper dust") en L2 | Indexa funciones públicas con recompensa (harvest, épocas), simula y llama si paga más que el gas | Centavos desparramados en cientos de contratos | 72 hs en Base, Arbitrum y Optimism; ≥ US$2/día netos simulados | – | 5 | vivo |

Finalistas: ninguno todavía (hace falta ≥ 8 de los dos en 2 rondas seguidas; máximo 4).

Propuesta de Claude para Pablo (ronda 1): sumar la restricción 7, **legal en Argentina**, que era obligatoria en el V1. Hoy pesa sobre S5 (Polymarket bloqueado por orden judicial) y sobre cualquier mercado de predicción.

## Descartados (≤ 4 de los dos)

(ninguno todavía)
