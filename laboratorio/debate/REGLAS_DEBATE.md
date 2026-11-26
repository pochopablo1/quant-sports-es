# Reglas del debate (Claude ↔ Gemini)

Objetivo: llegar a **6 planes finalistas** para automatizar algo que genere valor (plata) para Pablo.
Mañana (27/11/2026) los 6 se ponen a prueba **sin plata** (en papel o con un MVP gratis).

## Cómo funciona

- Turnos de 1 hora alternados. Claude escribe `debate/turnos/<fecha>_claude.md`; Gemini responde en `debate/turnos/<fecha>_gemini.md` (vía PythonAnywhere).
- `debate/PLANES.md` es el tablero: lo mantiene Claude, con el puntaje de los dos.
- Cada turno: atacar los planes del otro (con argumentos concretos), defender o corregir los propios, proponer como máximo 2 planes nuevos y poner un puntaje de 0 a 10 a cada plan vivo.

## Contexto de Pablo

- Vive en Luján, Buenos Aires, Argentina. Capital disponible: ~US$37. Sin otra plata para sumar.
- Sabe programar con ayuda de IA; tiene PythonAnywhere pago, GitHub, Google Drive y arma webs y apps (Android) con publicidad.
- Meta: ~US$20/día, lo más automatizado posible, riesgo mínimo, legal.
- Ya medido y descartado con datos: surebets, barrido de partidos terminados en Polymarket, mercados vencidos, sumas de fútbol, arbitraje USDT entre exchanges, triangular, estables, funding, rulo oficial→USDT.

## Criterios de puntaje (cada uno de 0 a 2, total 10)

1. **Automatizable**: una vez armado, corre solo con poca intervención.
2. **Ingreso realista**: camino creíble a US$20/día en 1–3 meses.
3. **Capital y costo**: arranca con ≤ US$37 y costos mensuales bajos.
4. **Probable sin plata**: se puede validar mañana en papel o con un MVP gratis, con una métrica clara.
5. **Riesgo y legalidad**: legal en Argentina, respeta términos de servicio, sin riesgo de perder capital.

## Fin del debate

Un plan es **finalista** cuando los dos le dan ≥ 8 en dos turnos seguidos. El debate termina cuando hay 6 finalistas, o el **27/11/2026 a las 09:00 hora argentina**. En ese caso pasan los 6 con mejor puntaje sumado. Claude escribe entonces `debate/FINALISTAS.md` con, para cada plan, la prueba concreta sin plata y la métrica que define si pasa.
