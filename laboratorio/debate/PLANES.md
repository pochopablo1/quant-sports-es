# Tablero de planes

Ronda 8 · 2026-11-27 00:09 UTC · lo mantiene Claude. Puntajes de 0 a 10 según REGLAS_DEBATE.md. Columnas: puntaje más reciente de cada uno (entre paréntesis, el anterior).

| # | Plan | Qué se automatiza | Cómo genera plata | Prueba sin plata | Claude | Gemini | Estado |
|---|---|---|---|---|---|---|---|
| P2 | Radar de licitaciones municipales y provinciales (nicho: alimentos/viandas escolares y limpieza/higiene, municipios de 1ª y 3ª sección) | Lectura de PBAC, COMPR.AR y boletines municipales, con resumen por rubro | Suscripción US$15–40/mes a PyMEs proveedoras | PDF con 5 licitaciones vigentes del nicho a 10 PyMEs con adjudicaciones en 12 meses (elegidas antes, 1 email); pasa si ≥ 2 piden pliego o precio | 8 (8) | 8 (8) | **finalista** |
| C9 | Monitor de cartera de clientes para mayoristas y distribuidoras (repuestos de autos y materiales de construcción, Luján/Rodríguez/Mercedes) + módulo de edictos de concursos, quiebras y sucesiones (ex G9) | Consulta diaria (con caché) de los CUITs en la API pública de la Central de Deudores del BCRA + edictos (BO nacional y PBA) | Suscripción US$15–25/mes por 100–200 CUITs | API con 50 CUITs (≥ 45 responden; ≥ 10% con señal en 6 meses) + reporte de muestra a 10 distribuidoras (pasa si ≥ 2 piden cargar su lista) + 5 llamadas (pasa si ≥ 3 se enteran "cuando les rebota"); confirmar condiciones de uso de la API, art. 26 Ley 25.326 e inscripción en la AAIP | 8 (8) | 8 (8) | **finalista** |
| C11 | Vigilancia de marcas para agentes de propiedad industrial (Res. INPI 583/2025: el INPI ya no examina de oficio la confusión; oposición en 30 días) | Bajada del Boletín de Marcas, filtro fonético/por clase, LLM solo sobre candidatos; fecha límite de oposición | US$50–100/mes por estudio chico; 6–12 estudios = US$600/mes | Bajar el último boletín; comparar 30 marcas de la zona (pasa si ≥ 1 conflicto plausible); email a 10 agentes matriculados (pasa si ≥ 2 piden probar con su cartera) | 8 (8) | 8 (8) | **finalista** |
| C8 | Listas de precios "sucias" del mayorista (PDF/Excel) → archivo importable en Tiendanube, con parseo por IA; arranca como servicio manual pago y después app en la tienda de Tiendanube | Parser con IA + app chica vía API oficial | Primero $5.000 por archivo convertido; después suscripción cobrada por Tiendanube | (1) Reseñas y precios de apps de importación existentes; (2) 1 email a 20 tiendas (al contacto público, sin seguimiento insistente) ofreciendo el servicio manual: pasa si ≥ 3 mandan su lista y ≥ 1 paga | 8 (8) | 8 (8) | **finalista** |
| G12 | Fichas técnicas/compatibilidades para vendedores de autopartes en Mercado Libre | Detecta publicaciones incompletas y genera el archivo de edición masiva (el cliente lo sube; sin acceso a su cuenta) | $10.000 por cada 500 publicaciones | Vendedores de la zona con fichas incompletas, contactados por su web/email (nunca por mensajes de ML); pasa si ≥ 2 aceptan 10 gratis | 6 | 8 | vivo · nuevo (Claude: la IA inventa compatibilidades y es trabajo de una sola vez; propone mantenimiento mensual con catálogos del fabricante) |
| C15 | Actualización de alquileres para inmobiliarias chicas (post DNU 70/2023: cada contrato con su índice y período) | Carga única de contratos; índices oficiales (BCRA: ICL, CER; INDEC: IPC); cálculo y email a inquilino y propietario | US$15–25/mes por inmobiliaria; 25–40 inmobiliarias | Fuentes abiertas; relevar si los sistemas (Tokko, etc.) ya lo traen; 5 llamadas (pasa si ≥ 3 usan Excel y ≥ 2 aceptan la prueba gratis de diciembre) | 6 (6) | 6 | vivo |
| G13 | Certificados de asistencia automáticos para talleristas y cursos no formales | Google Form → PDF con plantilla → email | US$10 por evento | Ofrecer gratis en grupos de talleristas; pasa si ≥ 3 lo piden | 4 | 7 | vivo · nuevo (Claude: Autocrat, autoCerts y CertifySimple lo hacen gratis) |
| C17 | Canal automático de ofertas reales de Mercado Libre con el Programa de Afiliados (hasta 15%) | Seguimiento de precios con historial propio; publica bajas reales en Telegram + web estática | Comisión por venta (~US$1,5–2); 10–15 ventas/día | Términos del programa (¿canales automáticos?); 500 productos seguidos en el día (pasa si ≥ 10 bajas reales ≥ 15%); relevar 5 canales de ofertas | 5 | – | vivo · nuevo |
| C18 | Informe satelital mensual para dueños de campo que arriendan (Sentinel-2 gratis: NDVI y agua) | Lote dibujado una vez; PDF mensual "sembrado / anegado / quemado" por email | US$8–15/mes por campo o US$20 por informe de devolución; reventa vía corredores rurales | NDVI de 6 meses de un lote de Luján (pasa si se ven siembra/cosecha y las nubes tapan ≤ 1 de 3 pasadas); 3 corredores + 3 dueños (pasa si ≥ 2 pagarían) | 5 | – | vivo · nuevo |
| C16 | Libros de actividades en español generados por código en Amazon KDP | Interior y portada por script; subida manual | Regalías ~US$2–3 por libro; catálogo de 50–100 títulos | Cobro de KDP en Argentina, política de low content, rankings de la competencia, 1 libro en el día | 4 (5) | 5 | vivo (los dos lo ven lento sin publicidad) |

Finalistas: **P2**, **C9**, **C11** y **C8**. Faltan 2. Cierre: 27/11 12:00 UTC; si no se llega, pasan los de mejor puntaje sumado (hoy, fuera de los finalistas: G12 14, C15 12, G13 11, C16 9, C17 5*, C18 5*; * sin puntaje de Gemini todavía).

Notas de Claude, ronda 8: C8 pasa a finalista. G10, G11, C13 y C14 descartados (≤ 4 de los dos). C17 (comisión por venta) y C18 (imágenes satelitales) responden al pedido de Gemini de mecanismos y procesamiento distintos.

## Descartados (≤ 4 de los dos)

- **G10** Patentes y multas para gestores (4/4): el libre deuda para transferir se eliminó en 2024; portales con captcha.
- **G11** SIRCREB preventivo (4/4): el padrón no es público; se consulta con clave fiscal.
- **C13** Subtítulos en Fiverr (4/4): algoritmo para vendedores nuevos y revisión manual.
- **C14** Alerta de monotributo con API de Mercado Pago (4/4): nadie da acceso OAuth a su cuenta.
- **G5** Radar de insumos para gastronómicos (4/4): el cliente compra a distribuidoras, no en mayoristas web.
- **G8** Registro de huéspedes (4/4): obligación no probada en PBA y fotos de DNI de terceros.
- **G9** Edictos sucesorios: fusionado como módulo de C9 (no descartado por malo).
- **C12** Newsletter en inglés para extranjeros (4/4): cobro en dólares caro y competencia gratis.
- **G6** Plugin de percepciones IIBB para WooCommerce (3/3): el agente ya tiene ERP; el que no es agente no lo necesita.
- **C10** API de datos públicos en marketplaces (4/4): compite con APIs gratis.
- **G3** Auditor de facturas a éxito (4/4): precios TIC desregulados, el success fee no se cobra.
- **G4** Calificador de leads por WhatsApp (4/4): automatizar WhatsApp por fuera de la API viola los términos de Meta.
- **P1** Radar de autos para agencieros (4/4) · **P5** Monitor de competencia en ML (4/3) · **G1** Centinela de CUITs para contadores (4/4) · **G2** Bot para servicios técnicos (4/4) · **P3** Subastas oficiales (4/4) · **P4** Inmuebles bajo precio (4/4) · **P6** Microherramientas con publicidad (4/4) · **P7** Canal de alertas de dólar (2/2).
