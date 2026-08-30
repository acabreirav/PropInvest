"""Creación y reconstrucción de la base DuckDB desde schema/schema.sql."""

from __future__ import annotations

from pathlib import Path

import duckdb

from flujocero.config import RAIZ


def ruta_db(raiz: Path | None = None) -> Path:
    d = (raiz or RAIZ) / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / "flujocero.duckdb"


def ruta_esquema(raiz: Path | None = None) -> Path:
    return (raiz or RAIZ) / "schema" / "schema.sql"


# Columnas agregadas al esquema DESPUES de que existieran bases en uso. `schema.sql` usa
# `CREATE TABLE IF NOT EXISTS`, asi que una base ya creada **nunca recibe una columna nueva**:
# el DDL se ejecuta sin error y sin efecto, y el primer INSERT que la mencione revienta.
# Paso el 30-ago-2026 con `m2_mediana` y habria roto la base del usuario, no solo la de
# desarrollo. Cada entrada es `(tabla, columna, tipo)` y se aplica de forma idempotente.
COLUMNAS_AGREGADAS: tuple[tuple[str, str, str], ...] = (
    ("agg_arriendo_microzona", "m2_mediana", "DECIMAL(10,2)"),
)


def migrar(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Agrega las columnas que `CREATE TABLE IF NOT EXISTS` no puede agregar sola.

    Idempotente: correrlo dos veces no hace nada la segunda. No borra ni renombra nada —
    para eso haria falta una migracion de verdad, con su decision escrita.
    """
    aplicadas: list[str] = []
    for tabla, columna, tipo in COLUMNAS_AGREGADAS:
        try:
            con.execute(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS {columna} {tipo}")
        except duckdb.Error:
            # La tabla todavia no existe (base recien creada): el DDL ya la trae completa.
            continue
        aplicadas.append(f"{tabla}.{columna}")
    return aplicadas


def aplicar_esquema(con: duckdb.DuckDBPyConnection, raiz: Path | None = None) -> list[str]:
    """Aplica el DDL sobre una conexión ya abierta. Lo usan `crear()` y los tests,
    para que ambos ejerciten exactamente el mismo esquema."""
    sql = ruta_esquema(raiz).read_text(encoding="utf-8")
    try:
        con.execute("INSTALL spatial; LOAD spatial;")
    except duckdb.Error:
        # Sin la extensión espacial, GEOMETRY se degrada a BLOB (WKB).
        sql = sql.replace("GEOMETRY", "BLOB")
    con.execute(sql)
    migrar(con)
    return [r[0] for r in con.execute("SHOW TABLES").fetchall()]


def crear(raiz: Path | None = None) -> Path:
    ruta = ruta_db(raiz)
    con = duckdb.connect(str(ruta))
    try:
        tablas = aplicar_esquema(con, raiz)
    finally:
        con.close()
    if len(tablas) < 10:
        raise RuntimeError(f"el esquema creó solo {len(tablas)} tablas: {tablas}")
    return ruta
