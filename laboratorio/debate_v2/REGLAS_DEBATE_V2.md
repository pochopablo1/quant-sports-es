# Reglas del Debate V2 · Laboratorio de Ineficiencias Autónomas

## Objetivo
Encontrar y depurar estrategias 100% autónomas (código + APIs / on-chain) que generen **≥ US$2/día netos (~US$60/mes)** con una banca de **US$300 rotativos**, con potencial de escalar reinvirtiendo ganancias.

## Restricciones duras (eliminación inmediata si falla una)
1. **Cero ventas humanas:** prohibido mandar emails en frío, hacer llamadas, atender clientes B2B, armar SaaS o agencias. El sistema compra/vende/opera contra mercados, APIs o smart contracts.
2. **Banca exacta de US$300:** la estrategia debe poder rotar con tickets chicos (US$5–80) y absorber fees, gas y spread sin morir.
3. **Filtro anti-ballenas obligatorio:** toda propuesta debe explicar *por qué un fondo quant o un bot millonario NO está barriendo esa ineficiencia hoy* (techo de ganancia chico, valuación semántica "sucia", liquidez fragmentada, fricción de dominio o barrera local).
4. **Validación en frío (Dry-Run 48–72 hs):** antes de poner un dólar real, debe existir un script en modo lectura que registre oportunidades reales, descuente comisiones/slippage y pruebe esperanza matemática positiva. Si el dry-run no da positivo, la idea muere.
5. **100% digital y sin logística física:** nada de envíos, stock en casa ni depender de cuentas bancarias locales que se bloqueen por volumen de transferencias.
6. **Regla de diversidad:** Polymarket / mercados de predicción están permitidos como competidores reales, pero **como máximo 1 estrategia de mercados de predicción** puede entrar a la final, para obligar al debate a explorar también ecosistemas distintos.

## Zonas prohibidas
- Apuestas direccionales ("adivinar quién gana") en Polymarket o deportes sin ventaja medible de microestructura o datos.
- Liquidaciones DeFi / MEV estándar en Aave, Morpho, Compound (monopolizados por bots de bloque).
- Arbitraje spot simple CEX-CEX en pares top (BTC/ETH/SOL) o funding rate básico con US$300.
- Surebets tradicionales en casas sin API abierta y con limitación rápida de cuentas.
- Cualquier negocio de contenido, SEO, YouTube, afiliados o apps que requieran audiencia previa.

## La lógica buscada (patrón común)
Buscamos **mercados raros, semi-fungibles, fragmentados o con valuación "sucia"** donde:
- Humanos apurados o desinformados ponen precios a ojo, o dejan órdenes rezagadas.
- Un bot en Python (con reglas, datos externos o un LLM barato para parsear texto/atributos) tiene ventaja sobre los humanos, y el tamaño chico del nicho mantiene afuera a los bots institucionales.

## Dinámica y puntaje (0 a 10)
- Cada ronda tiene 2 partes: (1) **Ataque duro** a las ideas vivas (fees ocultos, iliquidez real, riesgo de inventario, APIs cerradas, riesgo de ban) y (2) **Propuestas nuevas** que respeten el patrón común.
- **Puntaje 0–10** basado en: factibilidad técnica de la API (25%), ventaja real sin ballenas (25%), velocidad de rotación con US$300 (25%), riesgo neto de pérdida/ban (25%).
- ≤ 4 de ambos = **descartada**.
- ≥ 8 de ambos en 2 rondas seguidas = **finalista** (máximo 4 finalistas para pasar directo a script dry-run de 48 hs).
