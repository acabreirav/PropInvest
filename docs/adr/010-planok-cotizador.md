# ADR 010 · Cotizador PlanOK: la API completa, y dónde está la línea

**Fecha**: 02-sep-2026 · **Estado**: lectura aprobada; **cotización masiva DESCARTADA
el 02-sep-2026** (ver adenda) · **Tarea**: T-925

## Qué se investigó y cómo

Cinco rondas de `cli probar-planok` desde la máquina del inversionista (el entorno remoto
no alcanza el host), cada respuesta a la zona cruda. `robots.txt` **permite** el acceso.
Sin auth, sin tokens, sin anti-bot. El único ❓ de docs/01-fuentes.md B.1 quedó resuelto.

## La API real (verificada contra `inmobiliariagpr` / subagrupación 52)

Base de datos: el input oculto `xservercot` del index → `https://cotizador.saladeventasdigital.com/rest`.
Todos GET, JSON envuelto en paréntesis (JSONP sin callback — se pelan antes de parsear).
Parámetros comunes: `api_key={key}&portal=&id_subagrupaciones={id}`.

| Endpoint | Devuelve | Costo |
|---|---|---|
| `Informacion_proyecto.php` | nombre, **dirección**, descripción, id_proyecto | lectura pura |
| `Modelos.php` | tipologías con id y orientación (glosa tipo "1D 1B - Tipo I (0m2)") | lectura pura |
| `Productos.php` + `tipo_devolucion=solo_productos&id_modelo={m}` | **unidades**: glosa ("DEPARTAMENTO 101"), id, pack, orientación, reserva_en_línea | lectura pura |
| `Secundarios.php` + `proceso=tipos/getSecundarios/getPack` + id_proyecto/id_etapas | estacionamientos/bodegas | lectura pura |
| `GenerarCotizacion.php` + producto={id_unidad}... | id_cotizacion, nombre_pdf → `ficha.php` **con el PRECIO** | **crea un registro de cotización en el CRM de la inmobiliaria** |

Trampas verificadas: `tipo_devolucion` dice QUÉ devolver (`orientacion` devuelve
orientaciones, no unidades); el m² de la glosa puede venir vacío ("(0m2)"); `Secundarios`
sin `proceso` responde `check:true` vacío.

## La línea: leer es gratis, cotizar deja huella

Enumerar proyectos, tipologías y unidades disponibles es **lectura pública pura** — mismo
tier que un sitemap. Aprobado y sin drama.

El **precio** solo aparece al generar una cotización. Es anónima en esta etapa
(`id_cliente=0`, `new_client=false`, ningún dato personal), y es exactamente lo que hace
cualquier visitante del cotizador — el §9 declara este canal como el PREFERIDO del
proyecto. Pero automatizado a escala (cientos de unidades × decenas de proyectos) genera
cientos de registros en CRMs ajenos por corrida. El §8.4 manda detenerse y preguntar, y
esta es la pregunta. Opciones presentadas al inversionista el 02-sep-2026:

- **(a) Piloto acotado**: cotizaciones automáticas SOLO para proyectos de comunas del
  alcance, tope diario (25 unidades/día, espejo del tope de 40 emails/día del §9), pausa
  de cortesía entre llamadas. Recomendada.
- **(b) Solo lectura**: enumerar unidades y stock sin precio; el precio via outreach §9
  (cola aprobada a mano) o listas PDF.
- **(c) No usar el cotizador** — descartada: es la fuente declarada de la capa 3.

## Lo que falta resuelto o no por esta ADR

- **Enumeración de proyectos**: descubrir los pares `(key, id_subagrupaciones)` de la RM.
  No vive en el cotizador; se cosecha de los sitios de inmobiliarias y portales de
  proyectos nuevos (Pabellón/Enlace, docs/01 #8). Tarea aparte (T-925b).
- El proyecto de ejemplo es de Puerto Montt: sirvió para la ingeniería, no para el dato.


## Adenda 02-sep-2026 · La cotización NO es anónima — el piloto (a) se descarta

El inversionista verificó el flujo real en el navegador: al apretar "Continuar", el
cotizador **pide los datos personales del cliente ANTES de generar la cotización** (por eso
`GenerarCotizacion` fallaba en `Get_Insert_Eventos_Personales1`: falta la persona). No hay
cotización sin identificarse.

Consecuencia directa: cotizar en masa exigiría (i) entregar los datos reales del
inversionista decenas de veces al día — cada una un lead que gatilla seguimiento comercial —
o (ii) inventar identidades, que el §9 prohíbe sin ambigüedad. **Ninguna es aceptable; la
opción (a) aprobada horas antes asumía anonimato y queda sin efecto.**

Lo que queda en pie de esta fuente:
- **Lectura** (proyectos, dirección, modelos, unidades disponibles, stock): aprobada,
  útil como censo de oferta nueva y señal de disponibilidad. Sin precio.
- **Cotizador como canal de outreach del §9**: uno a uno, con identidad real, para
  proyectos que de verdad interesen — que es exactamente lo que el §9 declaró preferido.

**El precio masivo de proyectos nuevos cambia de ruta** a la #3 del orden de ataque de
docs/01 — `wp-json/wp/v2/proyecto` + JSON-LD de las inmobiliarias (Socovesa publica
priceCurrency "CLF" = UF), JSON público sin formularios, esfuerzo muy bajo, riesgo muy
bajo — complementada por Pabellón/Enlace (#8) y listas PDF vía outreach. Tarea: T-925c.
