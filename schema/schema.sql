-- Flujo Cero · esquema DuckDB
-- Toda tabla de mercado lleva las SEIS columnas de procedencia (CLAUDE.md §3.1).

CREATE TABLE IF NOT EXISTS dim_comuna (
  comuna_id      VARCHAR PRIMARY KEY,   -- slug: 'san-miguel'
  nombre         VARCHAR NOT NULL,
  region         VARCHAR NOT NULL,
  provincia      VARCHAR,
  codigo_sii     VARCHAR,
  codigo_ine     VARCHAR,
  fase           INTEGER                -- 1,2,3 según config/zonas.yml
);

CREATE TABLE IF NOT EXISTS dim_microzona (
  microzona_id        VARCHAR PRIMARY KEY,  -- 'nunoa/plaza-egana'
  comuna_id           VARCHAR NOT NULL REFERENCES dim_comuna(comuna_id),
  nombre              VARCHAR NOT NULL,
  meli_neighborhood_id VARCHAR,             -- puente al vocabulario comercial
  centro_lat          DOUBLE,               -- centro del barrio segun MELI (T-014b)
  centro_lon          DOUBLE,
  geom                GEOMETRY,
  saturada            BOOLEAN DEFAULT FALSE, -- evidencia Tattersall; excluye del ranking
  fuente_saturacion   VARCHAR,
  poblacion_censo2024 INTEGER,
  hogares_censo2024   INTEGER,
  ingreso_proxy       DOUBLE,
  dist_metro_operativo_m  DOUBLE,
  dist_metro_construccion_m DOUBLE,
  metro_apertura_anio INTEGER
);

CREATE TABLE IF NOT EXISTS dim_proyecto (
  proyecto_id     VARCHAR PRIMARY KEY,
  nombre          VARCHAR NOT NULL,
  inmobiliaria    VARCHAR,               -- persona jurídica: OK persistir
  comuna_id       VARCHAR REFERENCES dim_comuna(comuna_id),
  microzona_id    VARCHAR REFERENCES dim_microzona(microzona_id),
  direccion       VARCHAR,
  lat DOUBLE, lon DOUBLE,
  estado          VARCHAR,               -- blanco | verde | entrega_inmediata
  fecha_entrega   DATE,
  total_unidades  INTEGER,
  acogido_dfl2    BOOLEAN,
  source_id VARCHAR, source_url VARCHAR, fetched_at TIMESTAMPTZ,
  parser_version VARCHAR, raw_blob_path VARCHAR, robots_snapshot_sha VARCHAR
);

-- SCD tipo 2: permite responder "¿cuándo bajó el precio de esta unidad?"
CREATE TABLE IF NOT EXISTS fact_unidad_venta (
  unidad_key      VARCHAR,               -- hash(proyecto_id, numero_unidad)
  proyecto_id     VARCHAR REFERENCES dim_proyecto(proyecto_id),
  -- Sin esto no hay yield: el arriendo comparable vive en `fact_arriendo_comp` por microzona,
  -- y una unidad en venta sin microzona no se puede cruzar con el. Llegar a la microzona por
  -- `dim_proyecto` solo funciona para obra nueva; un usado de portal no tiene proyecto.
  microzona_id    VARCHAR REFERENCES dim_microzona(microzona_id),
  numero_unidad   VARCHAR,
  tipologia       VARCHAR,               -- '1D1B','2D1B','2D2B','3D2B','studio'
  dormitorios     INTEGER, banos INTEGER,
  m2_utiles       DOUBLE, m2_terraza DOUBLE, m2_totales DOUBLE,
  piso            INTEGER, orientacion VARCHAR,
  -- D-015: el stock usado compite, pero no hereda el subsidio a la tasa. NULL = no se sabe,
  -- y no se rellena: el §3.2 prohibe imputar. En Portal Inmobiliario viene del breadcrumb
  -- ("Propiedades usadas" vs "Proyectos"), verificado en el 91% de una muestra de 400.
  es_vivienda_nueva BOOLEAN,
  antiguedad_anios  INTEGER,              -- desde la recepcion. Decide la ventana DFL2 (T-911)
  precio_uf       DECIMAL(12,2),
  -- Una venta publicada EN PESOS antes se tiraba: `precio_uf` era la unica columna de precio
  -- y el §11 prohibe que la capa de carga convierta (la UF del dia vive en otra tabla). El
  -- resultado es que el 6,1% de las ventas de la RM desaparecia con un `logging.info`, y una
  -- comuna entera podia esfumarse sin que nadie se enterara. Se guarda el peso como viene y
  -- la conversion pasa al emparejamiento, con la UF del dia del aviso — que es exactamente
  -- como ya funciona el arriendo. El valor convertido es `D` (§3.2), no `V`.
  precio_clp      DECIMAL(14,0),
  precio_estacionamiento_uf DECIMAL(12,2),
  precio_bodega_uf DECIMAL(12,2),
  descuento_pct   DOUBLE,
  disponible      BOOLEAN,
  evidence_level  VARCHAR CHECK (evidence_level IN ('V','D','E','ND')),
  sospechoso      BOOLEAN DEFAULT FALSE,
  valid_from      TIMESTAMPTZ NOT NULL,
  valid_to        TIMESTAMPTZ,           -- NULL = versión vigente
  source_id VARCHAR, source_url VARCHAR, fetched_at TIMESTAMPTZ,
  parser_version VARCHAR, raw_blob_path VARCHAR, robots_snapshot_sha VARCHAR
);

-- CAPA 1 · Censo 2024 por manzana-entidad (T-014). Subconjunto DECLARADO de las 189
-- variables del INE: la llave, la demografia base y las que alimentan `riesgo_microzona`
-- (desocupacion de viviendas, profundidad del mercado de arriendo, densidad vertical).
-- Las 189 completas viven en la zona cruda: agregar una columna es una linea aqui, otra
-- en el INSERT de sources/ine_censo2024.py, y `cli ingerir-censo` de nuevo.
-- Los conteos chicos vienen enmascarados con '*' por privacidad: entran como NULL (ND),
-- jamas como 0 — un cero inventado sesgaria toda tasa calculada encima (§3.2).
CREATE TABLE IF NOT EXISTS dim_manzana (
  manzent         VARCHAR PRIMARY KEY,   -- id manzana-entidad del INE, llave del censo
  cut             INTEGER,               -- codigo unico territorial de la comuna
  comuna          VARCHAR,
  region          VARCHAR,
  tipo_mz         VARCHAR,               -- URBANO | RURAL
  n_personas      INTEGER,
  n_hogares       INTEGER,
  prom_personas_hogar DOUBLE,
  prom_edad       DOUBLE,
  prom_escolaridad18 DOUBLE,
  n_viviendas     INTEGER,               -- viviendas particulares
  n_viv_ocupadas  INTEGER,
  n_viv_desocupadas INTEGER,             -- el numerador de la desocupacion censal
  n_viv_depto     INTEGER,
  n_viv_casa      INTEGER,
  n_hog_arrienda_contrato INTEGER,
  n_hog_arrienda_sin_contrato INTEGER,
  n_hog_propia_pagada INTEGER,
  n_hog_propia_pagandose INTEGER,
  n_hog_unipersonales INTEGER,
  lat DOUBLE, lon DOUBLE,                -- centroide (EPSG:4326), para distancias rapidas
  geom_wkb        BLOB,                  -- poligono WKB; BLOB a proposito: legible con y
                                         -- sin la extension spatial de DuckDB
  source_id VARCHAR, source_url VARCHAR, fetched_at TIMESTAMPTZ,
  parser_version VARCHAR, raw_blob_path VARCHAR, robots_snapshot_sha VARCHAR
);

CREATE TABLE IF NOT EXISTS fact_arriendo_comp (
  comp_id         VARCHAR PRIMARY KEY,
  microzona_id    VARCHAR REFERENCES dim_microzona(microzona_id),
  tipologia       VARCHAR,
  dormitorios INTEGER, banos INTEGER,
  m2_utiles       DOUBLE,
  arriendo_clp    DECIMAL(14,0),
  arriendo_uf     DECIMAL(10,3),
  gastos_comunes_clp DECIMAL(12,0),
  estacionamiento BOOLEAN, bodega BOOLEAN, amoblado BOOLEAN,
  edificio_multifamily BOOLEAN,
  publicado_en    DATE,
  dias_en_mercado INTEGER,
  activo          BOOLEAN,
  evidence_level  VARCHAR,
  sospechoso      BOOLEAN DEFAULT FALSE,
  source_id VARCHAR, source_url VARCHAR, fetched_at TIMESTAMPTZ,
  parser_version VARCHAR, raw_blob_path VARCHAR, robots_snapshot_sha VARCHAR
);

-- T-014b · el puente: cada manzana censal asignada a su barrio MELI mas cercano dentro
-- de su comuna (Voronoi sobre centros — aproximacion DECLARADA, ver docs/adr/009).
-- Derivado puro: se recalcula entero en cada corrida de `cli puente-censo`.
CREATE TABLE IF NOT EXISTS map_microzona_manzana (
  manzent       VARCHAR PRIMARY KEY,
  microzona_id  VARCHAR NOT NULL,
  distancia_m   DOUBLE,                    -- del centroide de la manzana al centro del barrio
  calculado_en  TIMESTAMPTZ
);

-- T-922 · estaciones de Metro (Santiago) y Biotren (Concepcion), desde OpenStreetMap
-- (ODbL, json publico). Las OPERATIVAS alimentan el catalizador directo; las EN
-- CONSTRUCCION solo cuentan si su linea tiene fecha creible <= 3 anios en config/metro.yml.
CREATE TABLE IF NOT EXISTS dim_estacion_metro (
  estacion_id     VARCHAR PRIMARY KEY,   -- id del nodo OSM
  nombre          VARCHAR,
  red             VARCHAR,               -- 'metro-santiago' | 'biotren' | otra
  linea           VARCHAR,               -- si OSM la declara; NULL si no
  estado          VARCHAR,               -- 'operativa' | 'construccion'
  lat DOUBLE, lon DOUBLE,
  source_id VARCHAR, source_url VARCHAR, fetched_at TIMESTAMPTZ,
  parser_version VARCHAR, raw_blob_path VARCHAR, robots_snapshot_sha VARCHAR
);

-- T-014b · los insumos de `riesgo_microzona`, agregados sobre las manzanas del puente.
-- Cada componente es `D` (calculo deterministico sobre el Censo y los avisos); el `riesgo`
-- final combina con pesos `E` declarados en params.yml (riesgo_microzona.*).
CREATE TABLE IF NOT EXISTS agg_riesgo_microzona (
  microzona_id         VARCHAR PRIMARY KEY,
  n_manzanas           INTEGER,
  desocupacion         DOUBLE,             -- viv desocupadas / (ocupadas + desocupadas), censal
  profundidad_arriendo DOUBLE,             -- hogares arrendatarios / hogares, censal
  hogares_arrendatarios INTEGER,
  avisos_arriendo      INTEGER,            -- activos hoy en la microzona (B2: proxy saturacion)
  saturacion           DOUBLE,             -- avisos / hogares arrendatarios
  riesgo               DOUBLE,             -- 0..1 combinado, min-max sobre el alcance
  -- T-922 · catalizador Metro por microzona (necesita centro de barrio + estaciones)
  dist_metro_m         DOUBLE,             -- a la estacion elegible mas cercana
  catalizador          DOUBLE,             -- 0..1; NULL = sin medir (sin estaciones cargadas)
  calculado_en         TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS agg_arriendo_microzona (
  microzona_id VARCHAR, tipologia VARCHAR, rango_m2 VARCHAR,
  n INTEGER,
  arriendo_uf_p25 DECIMAL(10,3),
  arriendo_uf_mediana DECIMAL(10,3),
  arriendo_uf_p75 DECIMAL(10,3),
  arriendo_uf_m2_mediana DECIMAL(10,4),
  -- La superficie MEDIANA de los comparables de la celda. No es decorativa: una banda como
  -- `0-35` esta dominada por sus unidades grandes (medido: 60% de los comparables 1D1B caen
  -- en 31-35 m2), asi que acreditarle esa mediana a un depto de 22 m2 le regala ~17% de
  -- arriendo — justo en el numerador del yield. Guardarla permite MEDIR ese desvio por
  -- unidad en vez de suponer que la banda es homogenea.
  m2_mediana DECIMAL(10,2),
  avisos_activos INTEGER,          -- proxy de saturación
  calculado_en TIMESTAMPTZ,
  PRIMARY KEY (microzona_id, tipologia, rango_m2)
);

CREATE TABLE IF NOT EXISTS fact_transaccion (
  transaccion_id VARCHAR PRIMARY KEY,
  rol_sii VARCHAR, comuna_id VARCHAR, microzona_id VARCHAR,
  fecha DATE, precio_uf DECIMAL(12,2), m2_utiles DOUBLE,
  fuente VARCHAR,
  source_id VARCHAR, source_url VARCHAR, fetched_at TIMESTAMPTZ,
  parser_version VARCHAR, raw_blob_path VARCHAR, robots_snapshot_sha VARCHAR
);

-- Formato largo, una fila por (fecha, serie). El formato ancho anterior era incompatible
-- con CLAUDE.md 3.1: UF, UTM, IPC y TPM vienen de endpoints distintos, y un solo juego de
-- seis columnas de procedencia por fila no puede describir cuatro origenes a la vez.
CREATE TABLE IF NOT EXISTS dim_tiempo_financiero (
  fecha DATE,
  serie VARCHAR,                 -- uf | utm | ipc_var_m | tpm | tasa_hipotecaria_promedio
  valor DECIMAL(18,6),
  unidad VARCHAR,                -- CLP | pct
  evidence_level VARCHAR CHECK (evidence_level IN ('V','D','E','ND')),
  source_id VARCHAR, source_url VARCHAR, fetched_at TIMESTAMPTZ,
  parser_version VARCHAR, raw_blob_path VARCHAR, robots_snapshot_sha VARCHAR,
  PRIMARY KEY (fecha, serie)
);

-- Vista de conveniencia con la forma ancha de siempre, para el motor y el dashboard.
CREATE OR REPLACE VIEW v_tiempo_financiero AS
SELECT fecha,
       MAX(CASE WHEN serie = 'uf'  THEN valor END) AS uf_clp,
       MAX(CASE WHEN serie = 'utm' THEN valor END) AS utm_clp,
       MAX(CASE WHEN serie = 'ipc_var_m' THEN valor END) AS ipc_var_m,
       MAX(CASE WHEN serie = 'tpm' THEN valor END) AS tpm,
       MAX(CASE WHEN serie = 'tasa_hipotecaria_promedio' THEN valor END) AS tasa_hipotecaria_promedio
FROM dim_tiempo_financiero
GROUP BY fecha;

CREATE TABLE IF NOT EXISTS dim_tasa_banco (
  fecha DATE, banco VARCHAR, con_subsidio BOOLEAN,
  tasa_anual DOUBLE, plazo_max_anios INTEGER, ltv_max DOUBLE,
  evidence_level VARCHAR CHECK (evidence_level IN ('V','D','E','ND')),
  source_id VARCHAR, source_url VARCHAR, fetched_at TIMESTAMPTZ,
  parser_version VARCHAR, raw_blob_path VARCHAR, robots_snapshot_sha VARCHAR,
  PRIMARY KEY (fecha, banco, con_subsidio)
);

-- Salida del motor: una fila por unidad × escenario
CREATE TABLE IF NOT EXISTS fact_evaluacion (
  unidad_key VARCHAR, escenario_id VARCHAR,
  con_subsidio BOOLEAN, pie_pct DOUBLE, dfl2 BOOLEAN, vacancia DOUBLE, tasa_anual DOUBLE,
  arriendo_estimado_uf DECIMAL(10,3), arriendo_n_comparables INTEGER,
  credito_uf DECIMAL(12,2), dividendo_uf DECIMAL(10,3), dividendo_total_uf DECIMAL(10,3),
  pgi_uf DECIMAL(12,3), egi_uf DECIMAL(12,3), noi_uf DECIMAL(12,3),
  rentabilidad_bruta DOUBLE, cap_rate DOUBLE, grm DOUBLE, dscr DOUBLE,
  btcf_mensual_uf DECIMAL(10,3), atcf_mensual_uf DECIMAL(10,3),
  cash_on_cash DOUBLE,
  arriendo_equilibrio_uf DECIMAL(10,3),
  pie_minimo_flujo_cero DOUBLE,
  break_even_occupancy DOUBLE,
  tir_real_10a DOUBLE, tir_real_20a DOUBLE, tir_real_30a DOUBLE, van_uf DECIMAL(14,2),
  score DOUBLE, score_desglose JSON,
  excluido BOOLEAN, motivo_exclusion VARCHAR,
  calculado_en TIMESTAMPTZ, params_version VARCHAR,
  PRIMARY KEY (unidad_key, escenario_id)
);

CREATE TABLE IF NOT EXISTS parse_errors (
  id VARCHAR PRIMARY KEY, source_id VARCHAR, raw_blob_path VARCHAR,
  error VARCHAR, traceback VARCHAR, ocurrido_en TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS run_log (
  run_id VARCHAR PRIMARY KEY, source_id VARCHAR,
  inicio TIMESTAMPTZ, fin TIMESTAMPTZ,
  docs_recolectados INTEGER, filas_insertadas INTEGER, filas_actualizadas INTEGER,
  selftest_ok BOOLEAN, delta_vs_corrida_anterior DOUBLE, notas VARCHAR
);

-- Migraciones idempotentes. `CREATE TABLE IF NOT EXISTS` no agrega columnas a una tabla que
-- ya existe, asi que una base creada antes de D-015 se quedaba sin estas dos y fallaba al
-- insertar. Correr el esquema completo tiene que dejar cualquier base al dia, no solo una nueva.
ALTER TABLE fact_unidad_venta ADD COLUMN IF NOT EXISTS microzona_id      VARCHAR;
ALTER TABLE fact_unidad_venta ADD COLUMN IF NOT EXISTS es_vivienda_nueva BOOLEAN;
ALTER TABLE fact_unidad_venta ADD COLUMN IF NOT EXISTS antiguedad_anios  INTEGER;
