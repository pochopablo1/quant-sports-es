# Bitácora del laboratorio

Cada entrada: fecha · experimento · qué se vio · decisión. La más nueva va al final.

## 2026-11-26 03:30 UTC · exp001_clv_polymarket v1 · inicio
- Idea: medir si el favorito en moneylines de Polymarket (NBA, NHL, NFL, NCAA, MLB) deriva de forma sistemática entre T-24h y el inicio. Si sí, comprar temprano y vender al inicio.
- Usa el historial de precios del CLOB, así cada corrida suma casos de las últimas 72 h sin esperar.
- Costo asumido: 1 centavo por lado. Umbral: +1% neto, n ≥ 30, t ≥ 2, solo partidos después de FECHA_CONGELADO (2026-11-26 04:00 UTC).
- Decisión: arrancar. Primer objetivo: confirmar que el endpoint prices-history devuelve datos y que se juntan casos.
