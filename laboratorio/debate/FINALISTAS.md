# Finalistas del Laboratorio Quant

Debate Claude ↔ Gemini cerrado en la ronda 18 (2026-11-27 10:09 UTC). Los 6 llegaron a 8 y 8 en dos rondas seguidas (regla de `REGLAS_DEBATE.md`). Ninguno usa plata: todos son servicios o abonos B2B que se cobran por adelantado, con costo casi cero por cliente.

## Reglas comunes para el día de prueba

1. **Orden:** primero las pruebas que se matan con datos, sin hablar con nadie (**C24 → C9 → C11 → P2**); después las de contacto (**C8 → C15**), y los emails de C24, C9, C11 y P2 solo si su prueba de datos pasó. Un plan que muere por datos no se manda a nadie.
2. **Precio escrito desde el primer mensaje.** Un "qué interesante" no cuenta. **Positivo = mandan su archivo o cartera real, o piden medio de pago o factura.**
3. **Canal doble:** además del email, llamada o WhatsApp al número público a **3 de los 10** destinatarios. Si 0/10 responden el email pero ≥ 1/3 muestra interés por teléfono, el plan **no muere**: se repite por teléfono el lunes.
4. **Contacto prolijo:** un solo email por destinatario, al contacto público de la empresa, con forma de darse de baja. Sin seguimiento insistente.
5. **Al final del día** se ordenan por (1) plata cobrada o pedido de medio de pago, (2) positivos sobre el umbral, (3) horas manuales por cliente. Se dejan de lado los que den 0 positivos.
6. **Si pasan ≥ 2:** se trabaja solo en esos hasta cobrar (o 7 días sin respuesta). **Si pasan 0 o 1:** el siguiente día hábil se prueba el suplente **G15** (backup cifrado para comercios: 5 comercios de Luján, pasa si ≥ 3 no tienen copia diaria externa y aceptan prueba de 15 días, con restauración probada).

---

## 1. C24 · Feed semanal de sociedades nuevas y transferencias de fondo de comercio

- **Qué automatiza:** bajada diaria del Boletín Oficial nacional (2.ª sección) y del BO de PBA; extracción con IA de razón social, objeto, domicilio del local y fecha; filtro por partido y rubro; Excel semanal por email. Incluye los edictos de transferencia de fondo de comercio (Ley 11.867): locales que cambian de dueño y tienen que recontratar seguro, alarma, software y proveedores.
- **Cómo genera plata:** abono de US$15–25/mes a productores de seguros, empresas de alarmas, software de gestión, coworkings, imprentas. 30–40 abonos ≈ US$600/mes.
- **Prueba sin plata:** (1) correr el script sobre una semana de boletines y contar movimientos en GBA oeste + CABA (y aparte Luján, Rodríguez, Mercedes, Pilar y Moreno); (2) buscar quién ya vende esa lista y a qué precio; (3) si pasa (1), Excel de muestra a 15 posibles compradores con el precio del abono escrito.
- **Métrica y umbral:** **≥ 20 movimientos/semana** contados por el script (si no, salta a escala provincial o muere antes del primer email) **y ≥ 2 de 15** preguntan por el medio de pago o piden factura.
- **Pablo a mano:** elegir los 15 destinatarios, mandar los emails y las 3 llamadas, responder. Sin DNI ni domicilios particulares de socios en el feed.

## 2. C9 · Monitor de cartera de clientes para mayoristas y distribuidoras

- **Qué automatiza:** consulta (con caché) de los CUITs de clientes de la distribuidora en la API pública de la Central de Deudores del BCRA + edictos de concursos, quiebras y sucesiones (BO nacional y PBA). Alerta cuando un cliente empeora su situación o aparece en un edicto.
- **Cómo genera plata:** abono de US$15–25/mes por 100–200 CUITs, a distribuidoras de repuestos y materiales de construcción de Luján, Rodríguez y Mercedes.
- **Prueba sin plata:** (1) consultar 50 CUITs de empresas reales (públicos, por ejemplo de proveedores del Estado) en la API; (2) leer condiciones de uso de la API, art. 26 de la Ley 25.326 y el trámite de inscripción en la AAIP; (3) si pasa (1), reporte de muestra a 10 distribuidoras + 5 llamadas.
- **Métrica y umbral:** **≥ 45 de 50** CUITs responden y **≥ 10%** tiene alguna señal en 6 meses; **≥ 2 de 10** distribuidoras mandan su archivo real con ≥ 50 CUITs en la semana; **≥ 3 de 5** llamadas confirman que se enteran "cuando les rebota".
- **Pablo a mano:** las llamadas y los emails; inscripción en la AAIP y política de datos **antes del cliente n.º 5**. Riesgo de escala: cupo de la API (consultar mensual, diario solo para la lista "en observación").

## 3. C11 · Vigilancia de marcas para agentes de propiedad industrial

- **Qué automatiza:** bajada del Boletín de Marcas del INPI, filtro fonético y por clase contra la cartera del agente, IA solo sobre los candidatos, y aviso con la fecha límite de oposición (30 días). Desde la Res. INPI 583/2025 el INPI ya no examina de oficio la confusión: la vigilancia pasa a ser del titular.
- **Cómo genera plata:** US$50–100/mes por estudio chico; 6–12 estudios ≈ US$600/mes.
- **Prueba sin plata:** (1) bajar el último boletín y cruzarlo con 30 marcas de comercios de la zona; (2) email a 10 agentes matriculados con el precio desde el primer mensaje + 3 llamadas.
- **Métrica y umbral:** **≥ 1 conflicto plausible** entre las 30 marcas, y **≥ 2 de 10** agentes mandan su cartera o ≥ 10 marcas de clientes.
- **Pablo a mano:** revisar a ojo los candidatos del primer boletín (para calibrar el filtro), elegir agentes del listado de matriculados, mandar y responder.

## 4. P2 · Radar de licitaciones municipales y provinciales por nicho

- **Qué automatiza:** lectura de PBAC, COMPR.AR y boletines municipales; resumen por rubro (alimentos/viandas escolares y limpieza/higiene; módulo de obras para corralones y hormigoneras con impacto ambiental y Autoridad del Agua); módulo de último precio adjudicado por renglón.
- **Cómo genera plata:** abono de US$15–40/mes a PyMEs proveedoras del Estado (+US$15 por el módulo de precios).
- **Prueba sin plata:** (1) encontrar 5 licitaciones vigentes del nicho y, para cada una, si hay precio unitario adjudicado anterior; (2) PDF con las 5 a 10 PyMEs con adjudicaciones en los últimos 12 meses (elegidas antes), 1 email con el precio de diciembre escrito + 3 llamadas.
- **Métrica y umbral:** **≥ 2 de 10** piden el pliego o el precio y **≥ 1** acepta la prueba con precio conocido. Módulo de precios: **≥ 2 de 5** licitaciones con antecedente encontrable y **≥ 2 de 10** pagarían US$15 más.
- **Pablo a mano:** elegir las 10 PyMEs (de las adjudicaciones públicas), mandar y responder; revisar el primer resumen.

## 5. C8 · Listas de precios "sucias" del mayorista → archivo importable en Tiendanube

- **Qué automatiza:** parser con IA que convierte la lista del mayorista (PDF/Excel desordenado) en el CSV de importación de Tiendanube, con columna "revisar" para filas dudosas (precio fuera de rango, sin código). Primero servicio manual pago; después app en la tienda de Tiendanube. El negocio recurrente es que el mismo mayorista manda la misma lista todos los meses (plantilla reutilizable).
- **Cómo genera plata:** $5.000 por archivo convertido al principio; después suscripción cobrada por Tiendanube.
- **Prueba sin plata:** (1) relevar reseñas y precios de las apps de importación que ya existen; (2) 1 email a 20 tiendas (contacto público) ofreciendo el servicio + 3 llamadas/WhatsApp; al que manda su lista se le devuelve una muestra de 10 filas y la oferta de $5.000 por el archivo completo.
- **Métrica y umbral:** **≥ 3 de 20** mandan su lista y **≥ 1 paga**; el archivo pagado importa en Tiendanube sin errores con **≤ 1 hora** de corrección manual. **Control obligatorio:** antes de entregar, comparar el 10% de las filas contra el original; **un solo precio mal leído = no se cobra** y se corrige el parser.
- **Pablo a mano:** el control del 10%, la carga de prueba en una tienda de demo, cobrar. Riesgo de escala: horas de revisión por lista (un formato de proveedor a la vez).

## 6. C15 · Actualización de alquileres para inmobiliarias chicas

- **Qué automatiza:** carga única de los contratos; índices oficiales (BCRA: ICL, CER; INDEC: IPC); cálculo de cada actualización según su índice y período (post DNU 70/2023), aviso a inquilino y propietario y PDF de liquidación.
- **Cómo genera plata:** abono de US$15–25/mes por inmobiliaria; 25–40 inmobiliarias.
- **Prueba sin plata:** (1) relevar si los sistemas que usan las inmobiliarias (Tokko y otros) ya lo traen; (2) 5 llamadas a inmobiliarias chicas (30–50 contratos) de la zona, con la oferta de prueba gratis en diciembre y el precio de enero dicho.
- **Métrica y umbral:** **≥ 3 de 5** usan Excel y **≥ 2 de 5** aceptan la prueba (mandando al menos 5 contratos reales, sin datos personales que no hagan falta). Si < 3 de 5 usan Excel, el plan cae.
- **Pablo a mano:** las 5 llamadas; validar a mano el cálculo de los primeros 5 contratos contra la calculadora oficial del BCRA antes de mandar un aviso.

---

## Suplente

- **G15 · Backup cifrado diario para comercios con sistema de escritorio** (Claude 6 / Gemini 6). Se activa solo si pasan 0 o 1 de los 6 (ver regla común 6).
