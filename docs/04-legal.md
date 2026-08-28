# 04 · Marco legal, robots y ética de recolección

## 1. Ley 21.719 — nueva Ley de Datos Personales

- Publicada 13-dic-2024. **Entra en plena vigencia el 1 de diciembre de 2026** — a tres meses de hoy.
- Deroga y reemplaza la Ley 19.628 (1999). Crea la **Agencia de Protección de Datos Personales**
  con facultades de investigación y sanción.
- **Multas**: leves hasta 5.000 UTM · graves hasta 10.000 UTM · gravísimas hasta 20.000 UTM ·
  reincidencia: **2–4% de los ingresos anuales en Chile**.
- Ocho principios: licitud y lealtad, finalidad, proporcionalidad, calidad, responsabilidad,
  seguridad, transparencia e información, confidencialidad.
- Aplica a cualquier organización que trate datos de residentes chilenos, **independiente del origen
  del dato**. → **Que un dato sea público no lo saca del ámbito de la ley.** Este es el cambio de
  régimen respecto de la 19.628, que trataba con laxitud las "fuentes de acceso público".

**Consecuencia operativa (CLAUDE.md §3.4):** nombre, email, teléfono y RUT de personas naturales
son el ~90% de nuestra exposición legal y el ~2% de nuestro valor analítico. **No se persisten.**
Los contactos de outreach viven fuera de la base analítica, cifrados, con opt-out registrado.

## 2. Otras vías de reclamo

- **Ley 17.336** (propiedad intelectual) y **Ley 20.169** (competencia desleal) son las vías típicas
  por las que un portal reclama contra un scraper: reproducción sustancial de base de datos ajena.
- Chile **no tiene** un derecho *sui generis* de bases de datos al estilo europeo.
- **Corte Suprema Rol 15.245-2019** (06-mar-2019): recurso de protección sobre scraping del sitio del
  Poder Judicial; define scraping como *"técnica utilizada mediante programas de software para
  extraer información de sitios web"*. El fundamento sustantivo está tras paywall — **no verificado**.
- Contexto vivo (ago-2026): disputa entre el Poder Judicial y una empresa de jurisprudencia por
  acceso masivo a datos judiciales.

## 3. robots.txt por fuente — lo verificado

**Portal Inmobiliario** (es MercadoLibre):
```
Disallow: /propiedades/  /vip/  /perfil/vendedor/  /catalogo/*  /*.php  /*.html
Allow:    /*_Desde_      ← autoriza explícitamente la paginación
```
→ Permiten listados paginados, prohíben el detalle. **Un scraper de fichas viola robots.**
Además hay WAF con 403 desde datacenter. La ruta correcta es la API oficial.

**MercadoLibre T&C**: la propia página de términos está bloqueada por el robots.txt de MELI.
Los T&C de MELI en LatAm prohíben robots/spiders y la reproducción de la base de datos —
**el texto chileno vigente no fue verificado**. Léelo antes de decidir.

**Assetplan**: **permite explícitamente `ClaudeBot`, `Claude-User`, `GPTBot`, `PerplexityBot`,
`CCBot`, `Google-Extended`**. Restringe query params solo a Googlebot/Bingbot.
`/cdn-cgi/` confirma Cloudflare. Es la fuente más amigable del catálogo.

**Chilepropiedades**: `Allow: /` con **`Crawl-delay: 2`** y sitemap index declarado.
Respetar el crawl-delay es literalmente tu argumento de buena fe.

**Yapo**: el más permisivo, `Allow: /` sin restricción sobre listados.

**Goplaceit**: `Disallow: /cl/mapa?*` — justo donde vive la API. Conflicto directo.
**Doomos**: `Disallow: /ws/` (sus web services).
**TOCTOC**: devuelve 403 incluso al leer robots.txt; su API interna requiere interceptar sesión.

## 4. Buenas prácticas obligatorias

1. **API oficial primero, siempre.** El costo de montar OAuth es una tarde; el de un cease-and-desist
   es el proyecto.
2. **Separa datos de inmueble de datos de persona.** Precio, m², dormitorios, comuna, piso,
   orientación: sí. Nombre, email, teléfono, RUT: no.
3. **Rate limiting:** ≤1 req/s por host para HTML; `Crawl-delay: 2` en Chilepropiedades;
   **máx. 9 req/10 s en Gael Cloud (excederlo = ban de 1 hora)**. Backoff exponencial con jitter.
4. **User-Agent honesto e identificable:**
   `FlujoCero-ResearchBot/1.0 (+https://tu-dominio.cl/bot; contacto@tu-dominio.cl)`.
   Un UA identificable convierte "acceso no autorizado" en "crawler que puedes bloquear si quieres".
   Es tu mejor defensa reputacional.
5. **Proxies residenciales chilenos:** solo harían falta para Portal Inmobiliario y TOCTOC — y son
   **la señal más incriminatoria de intención de evasión**. Si llegaste a necesitarlos, replantea:
   usa la API oficial o compra el dato. Para Assetplan, Yapo, Chilepropiedades, wp-json y las
   fuentes públicas no hacen falta.
6. **Ventanas horarias:** cargas grandes entre 02:00 y 06:00 CLT, incrementales por `lastmod`.
7. **Caché agresivo y delta.** Nunca re-descargues lo que no cambió.
8. **Registro de procedencia por fila** (`source`, `fetched_at`, `robots_snapshot_sha`).
   Bajo la 21.719, el principio de responsabilidad exige poder demostrar el origen lícito de cada dato.

## 5. Outreach — el estándar que nos autoimponemos

Ver CLAUDE.md §9. Lo esencial: **aprobación humana por lote**, identificación honesta, 40 envíos/día,
un recordatorio, opt-out permanente, y el cuerpo del email nunca entra a la base analítica.
Suplantar a un corredor o insinuar un mandato inexistente está prohibido, aunque suba la tasa de respuesta.
