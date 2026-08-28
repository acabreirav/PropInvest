"""Bitácora de corridas y errores de parseo — CLAUDE.md §7.1 y §11.

Dos tablas del esquema existían sin que nadie las escribiera, y eso dejaba un gate del
contrato inoperante:

- **`run_log`**: el §7.1 exige que el `selftest` compare el conteo de filas contra
  *la última corrida exitosa* y falle si cayó más de 30% — el detector de parser roto.
  Sin persistir ese conteo, el detector recibía un `None` y nunca disparaba.
- **`parse_errors`**: el §11 prohíbe el `try/except: pass` y manda registrar todo error de
  parseo junto al documento crudo que lo produjo. Sin esta tabla, un error o mataba la
  corrida entera o se perdía.

Ambas guardan referencias a la zona cruda, nunca copias: el documento ya está en disco.
"""

from __future__ import annotations

import traceback
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CAIDA_QUE_DISPARA = 0.30


@dataclass
class Corrida:
    """Una ejecución de un colector. Se abre al empezar y se cierra al terminar."""

    run_id: str
    source_id: str
    inicio: datetime
    docs_recolectados: int = 0
    filas_insertadas: int = 0
    filas_actualizadas: int = 0
    selftest_ok: bool = False
    notas: str = ""


def abrir(source_id: str, ahora: datetime | None = None) -> Corrida:
    """Nueva corrida. `ahora` entra por argumento para que los tests sean deterministas."""
    return Corrida(
        run_id=uuid.uuid4().hex,
        source_id=source_id,
        inicio=ahora or datetime.now(UTC),
    )


def filas_de_la_ultima_corrida_exitosa(conexion: Any, source_id: str) -> int | None:
    """El conteo contra el que compara el detector de parser roto (§7.1).

    Solo cuentan las corridas con `selftest_ok`: comparar contra una corrida fallida
    convertiría un fallo en la nueva referencia y el detector dejaría de disparar.
    """
    fila = conexion.execute(
        "SELECT filas_insertadas FROM run_log "
        "WHERE source_id = ? AND selftest_ok AND fin IS NOT NULL "
        "ORDER BY fin DESC LIMIT 1",
        (source_id,),
    ).fetchone()
    return int(fila[0]) if fila and fila[0] is not None else None


def caida_pct(anterior: int | None, actual: int) -> float | None:
    """Fracción de caída del conteo. `None` si no hay con qué comparar."""
    if not anterior:
        return None
    return (anterior - actual) / anterior


def cerrar(
    conexion: Any,
    corrida: Corrida,
    ahora: datetime | None = None,
    filas_corrida_anterior: int | None = None,
) -> None:
    """Persiste la corrida. Se llama SIEMPRE, haya salido bien o mal."""
    fin = ahora or datetime.now(UTC)
    delta = caida_pct(filas_corrida_anterior, corrida.filas_insertadas)
    conexion.execute(
        "INSERT INTO run_log (run_id, source_id, inicio, fin, docs_recolectados, "
        "filas_insertadas, filas_actualizadas, selftest_ok, delta_vs_corrida_anterior, notas) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            corrida.run_id,
            corrida.source_id,
            corrida.inicio,
            fin,
            corrida.docs_recolectados,
            corrida.filas_insertadas,
            corrida.filas_actualizadas,
            corrida.selftest_ok,
            delta,
            corrida.notas,
        ),
    )


def registrar_error(
    conexion: Any,
    source_id: str,
    raw_blob_path: str | Path,
    error: Exception,
    ahora: datetime | None = None,
) -> str:
    """Guarda un error de parseo con su documento crudo (§11).

    No guarda el documento: guarda su ruta. El blob ya está en la zona cruda y duplicarlo
    en la base solo la haría crecer sin agregar nada auditable.
    """
    error_id = uuid.uuid4().hex
    conexion.execute(
        "INSERT INTO parse_errors (id, source_id, raw_blob_path, error, traceback, ocurrido_en) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            error_id,
            source_id,
            str(raw_blob_path),
            f"{type(error).__name__}: {error}",
            "".join(traceback.format_exception(type(error), error, error.__traceback__)),
            ahora or datetime.now(UTC),
        ),
    )
    return error_id


def errores_recientes(conexion: Any, source_id: str | None = None, limite: int = 20) -> list[Any]:
    if source_id:
        return conexion.execute(
            "SELECT ocurrido_en, source_id, raw_blob_path, error FROM parse_errors "
            "WHERE source_id = ? ORDER BY ocurrido_en DESC LIMIT ?",
            (source_id, limite),
        ).fetchall()
    return conexion.execute(
        "SELECT ocurrido_en, source_id, raw_blob_path, error FROM parse_errors "
        "ORDER BY ocurrido_en DESC LIMIT ?",
        (limite,),
    ).fetchall()


def historial(conexion: Any, source_id: str | None = None, limite: int = 10) -> list[Any]:
    if source_id:
        return conexion.execute(
            "SELECT inicio, source_id, docs_recolectados, filas_insertadas, selftest_ok, "
            "delta_vs_corrida_anterior FROM run_log WHERE source_id = ? "
            "ORDER BY inicio DESC LIMIT ?",
            (source_id, limite),
        ).fetchall()
    return conexion.execute(
        "SELECT inicio, source_id, docs_recolectados, filas_insertadas, selftest_ok, "
        "delta_vs_corrida_anterior FROM run_log ORDER BY inicio DESC LIMIT ?",
        (limite,),
    ).fetchall()
