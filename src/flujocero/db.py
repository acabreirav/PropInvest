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
