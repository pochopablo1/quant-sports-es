# Reporte dry-run c14

Período: 27/11 15:44 → 28/11 09:36 (hora AR), 17.9 hs.
Consultas: 2070 (100% sin errores).

**Veredicto: ❌ NO PASA**

| Condición | Cumple | Valor |
|---|---|---|
| P&L neto simulado ≥ US$2.0/día | no | US$1.37/día |
| ≥ 30% de los cruces en cada dirección | no | lado menor 0% |
| ≤ 50% del edge en exchanges sin API | no | 96% |
| Al menos 48 hs de datos | no | 17.9 hs |

- Oportunidades vistas (neto > 0 en algún momento): 230
- Que cuentan (duraron lo mínimo, con neto mínimo y con API): 3
- P&L neto simulado total: US$1.02
- Mediana por operación: US$0.340
- Duración mediana de las que cuentan: 450 s

## P&L por día (AR)

| Día | US$ |
|---|---|
| 2026-11-27 | 1.02 |

## Top grupos

| Grupo | US$ |
|---|---|
| binance-ripioexchange | 0.70 |
| binance-bitso | 0.33 |

## Direcciones

- ripioexchange->binance: 2
- bitso->binance: 1

_Dry-run en modo lectura: no se operó. Un PASA habilita a pensar en plata real con tickets chicos, no la garantiza._

(guardado en /home/runner/work/quant-sports-es/quant-sports-es/repo/laboratorio/bots_v2/datos/reporte_c14.md)
