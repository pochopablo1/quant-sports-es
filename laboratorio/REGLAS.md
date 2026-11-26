# Reglas del laboratorio

Loop automático: PythonAnywhere corre el experimento y pide crítica a Gemini (cada 6 h, 00/06/12/18 UTC).
Claude lee resultados + crítica, ajusta o cambia de idea y sube el experimento siguiente (cada 6 h, ~3,5 h después).

## Reglas fijas (nadie las cambia sin OK de Pablo)

1. **Solo papel.** Ningún experimento envía órdenes, firma transacciones, ni lee claves, `.env`, wallets o archivos fuera de `laboratorio/`.
2. **Umbral fijo, definido antes de mirar datos.** Cada experimento declara en su código `UMBRAL` y `N_MINIMO`. Una idea **PASA** solo si:
   - ganancia media neta de costos (comisiones + spread) ≥ el umbral del experimento (por defecto **+1%** por operación),
   - con **n ≥ 30** casos,
   - con estadístico **t ≥ 2**,
   - **medido fuera de muestra**: solo con casos posteriores a `FECHA_CONGELADO` del experimento.
3. **Cambiar la hipótesis o un parámetro = versión nueva** con `FECHA_CONGELADO` nueva. La muestra fuera de muestra vuelve a cero. Prohibido mover la fecha hacia atrás.
4. **Máximo 3 ajustes por idea.** Si no pasa, se descarta y se prueba otra.
5. **Capital real disponible: ~US$37.** Ideas que necesiten más capital o competir contra bots en milisegundos no sirven.
6. Ideas ya medidas y descartadas (no repetir sin un ángulo nuevo): surebets entre casas, barrido de partidos terminados en Polymarket, mercados vencidos, sumas de fútbol 3 vías, arbitraje USDT entre exchanges argentinos, triangular, estables, funding, rulo oficial→USDT.

## Contrato de un experimento

- Archivo en `laboratorio/experimentos/expNNN_nombre.py`, corre con `python3 -I`, sin argumentos, en menos de 20 min.
- Puede leer/escribir solo en `laboratorio/datos/`.
- Su **última línea de stdout** es un JSON con al menos:
  `{"experimento": str, "version": str, "hipotesis": str, "n_total": int, "n_fuera_muestra": int, "ganancia_media_neta": float, "t": float, "pasa_umbral": bool, "detalle": {...}}`
- `laboratorio/estado/experimento_actual.txt` tiene la ruta del experimento que corre.

## Veredictos

SEGUIR (juntar más datos) · AJUSTAR (versión nueva) · DESCARTAR (idea nueva) · PASA (avisar a Pablo, nada se opera sin su OK).
