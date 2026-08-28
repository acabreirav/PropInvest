"""Creación y reconstrucción de la base DuckDB desde schema/schema.sql."""

from __future__ import annotations

from pathlib import Path

import duckdb

from flujocero.config import RAIZ


def ruta_db(raiz: Path | None = None) -> Path:
    d = (raiz or RAIZ) / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / "flujocero.duckdb"


def crear(raiz: Path | None = None) -> Path:
    ruta = ruta_db(raiz)
    sql = ((raiz or RAIZ) / "schema" / "schema.sql").read_text(encoding="utf-8")
    con = duckdb.connect(str(ruta))
    try:
        try:
            con.execute("INSTALL spatial; LOAD spatial;")
        except Exception:
            # Sin la extensión espacial, GEOMETRY se degrada a BLOB (WKB).
            sql = sql.replace("GEOMETRY", "BLOB")
        con.execute(sql)
        tablas = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    finally:
        con.close()
    if len(tablas) < 10:
        raise RuntimeError(f"el esquema creó solo {len(tablas)} tablas: {tablas}")
    return ruta
