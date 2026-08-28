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
  numero_unidad   VARCHAR,
  tipologia       VARCHAR,               -- '1D1B','2D1B','2D2B','3D2B','studio'
  dormitorios     INTEGER, banos INTEGER,
  m2_utiles       DOUBLE, m2_terraza DOUBLE, m2_totales DOUBLE,
  piso            INTEGER, orientacion VARCHAR,
  precio_uf       DECIMAL(12,2),
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

CREATE TABLE IF NOT EXISTS agg_arriendo_microzona (
  microzona_id VARCHAR, tipologia VARCHAR, rango_m2 VARCHAR,
  n INTEGER,
  arriendo_uf_p25 DECIMAL(10,3),
  arriendo_uf_mediana DECIMAL(10,3),
  arriendo_uf_p75 DECIMAL(10,3),
  arriendo_uf_m2_mediana DECIMAL(10,4),
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
