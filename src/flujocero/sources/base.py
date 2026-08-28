"""Contrato común de las fuentes — CLAUDE.md §7.1.

Todo módulo en `sources/` implementa el protocolo `Source`. Este módulo aporta:

- las seis columnas de procedencia del §3.1, como un objeto que no se puede
  construir incompleto;
- la zona cruda del §3.6: `data/raw/{source_id}/{yyyy}/{mm}/{dd}/*.json.gz`,
  idempotente, se escribe ANTES de parsear;
- la verificación de robots.txt del §3.5, con el sha del snapshot que después
  viaja en cada fila.

Sin I/O de red en tiempo de importación: todo entra por argumento.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable
from urllib.parse import urlparse

LegalTier = Literal["api_oficial", "json_publico", "html_permitido", "html_prohibido"]
EvidenceLevel = Literal["V", "D", "E", "ND"]

RAIZ = Path(__file__).resolve().parents[3]
ZONA_CRUDA = RAIZ / "data" / "raw"

# Las seis del §3.1. La lista vive acá y el gate la lee de acá, no la repite.
COLUMNAS_PROCEDENCIA = (
    "source_id",
    "source_url",
    "fetched_at",
    "parser_version",
    "raw_blob_path",
    "robots_snapshot_sha",
)


class ProcedenciaIncompleta(ValueError):
    """Falta al menos una de las seis columnas. Regla dura: la fila no se inserta."""


@dataclass(frozen=True)
class Procedencia:
    """Las seis columnas del §3.1. Si no se pueden poblar las seis, no hay fila."""

    source_id: str
    source_url: str
    fetched_at: datetime
    parser_version: str
    raw_blob_path: str
    robots_snapshot_sha: str

    def __post_init__(self) -> None:
        faltan = [c for c in COLUMNAS_PROCEDENCIA if not getattr(self, c)]
        if faltan:
            raise ProcedenciaIncompleta(
                f"faltan columnas de procedencia: {', '.join(faltan)}. "
                "CLAUDE.md §3.1: sin las seis, la fila no se inserta."
            )
        if self.fetched_at.tzinfo is None:
            raise ProcedenciaIncompleta("fetched_at debe traer tzinfo=UTC (§11)")

    def as_dict(self) -> dict[str, Any]:
        return {c: getattr(self, c) for c in COLUMNAS_PROCEDENCIA}


@dataclass(frozen=True)
class RobotsVerdict:
    """Resultado de consultar robots.txt para un user-agent y una ruta."""

    allowed: bool
    url_robots: str
    snapshot_sha: str
    crawl_delay_s: float | None = None
    motivo: str = ""


@dataclass(frozen=True)
class Scope:
    """Qué le pedimos a un colector en esta corrida. Sin fechas del sistema: entran por argumento."""

    desde: str | None = None  # AAAA-MM
    hasta: str | None = None  # AAAA-MM
    comunas: tuple[str, ...] = ()
    limite_docs: int | None = None
    ahora: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class RawDoc:
    """Un documento tal como llegó, ya persistido en la zona cruda."""

    source_id: str
    url: str
    fetched_at: datetime
    ruta: Path
    contenido: bytes
    robots_snapshot_sha: str

    def json(self) -> Any:
        return json.loads(self.contenido.decode("utf-8"))


@dataclass
class SelfTestReport:
    """Resultado de `selftest()` — CLAUDE.md §7.1."""

    source_id: str
    ok: bool
    checks: dict[str, bool] = field(default_factory=dict)
    detalle: dict[str, str] = field(default_factory=dict)
    n_filas: int = 0
    n_filas_corrida_anterior: int | None = None

    @property
    def caida_pct(self) -> float | None:
        """Detector de parser roto: caída del conteo vs la última corrida exitosa."""
        anterior = self.n_filas_corrida_anterior
        if not anterior:
            return None
        return (anterior - self.n_filas) / anterior

    def fallar(self, check: str, detalle: str) -> None:
        self.ok = False
        self.checks[check] = False
        self.detalle[check] = detalle

    def pasar(self, check: str) -> None:
        self.checks.setdefault(check, True)


@runtime_checkable
class Source(Protocol):
    """El contrato del §7.1. Un módulo por fuente, slug igual al `source_id`."""

    id: str
    legal_tier: LegalTier
    parser_version: str

    def robots_ok(self) -> RobotsVerdict: ...
    def collect(self, scope: Scope) -> Any: ...
    def parse(self, doc: RawDoc) -> list[Any]: ...
    def selftest(self) -> SelfTestReport: ...


# --------------------------------------------------------------------------- zona cruda


def ruta_cruda(source_id: str, momento: datetime, nombre: str, raiz: Path | None = None) -> Path:
    """`data/raw/{source_id}/{yyyy}/{mm}/{dd}/{nombre}.json.gz` — §3.6."""
    base = (raiz or ZONA_CRUDA) / source_id / f"{momento:%Y}" / f"{momento:%m}" / f"{momento:%d}"
    seguro = re.sub(r"[^A-Za-z0-9._-]", "_", nombre)
    return base / f"{seguro}.json.gz"


def escribir_crudo(
    source_id: str,
    url: str,
    contenido: bytes,
    momento: datetime,
    robots_snapshot_sha: str,
    nombre: str | None = None,
    raiz: Path | None = None,
) -> RawDoc:
    """Persiste el documento ANTES de parsearlo. Re-ejecutar el mismo día sobrescribe
    el mismo archivo en vez de acumular duplicados (§3.6)."""
    etiqueta = nombre or _nombre_desde_url(url)
    destino = ruta_cruda(source_id, momento, etiqueta, raiz)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(destino, "wb") as fh:
        fh.write(contenido)
    return RawDoc(
        source_id=source_id,
        url=url,
        fetched_at=momento,
        ruta=destino,
        contenido=contenido,
        robots_snapshot_sha=robots_snapshot_sha,
    )


def leer_crudo(ruta: Path, source_id: str, url: str, momento: datetime, sha: str) -> RawDoc:
    """Relee un documento de la zona cruda. Es lo que hace posible `make rebuild`."""
    with gzip.open(ruta, "rb") as fh:
        contenido = fh.read()
    return RawDoc(source_id, url, momento, ruta, contenido, sha)


def _nombre_desde_url(url: str) -> str:
    partes = urlparse(url)
    cuerpo = f"{partes.path}_{partes.query}".strip("/")
    # La apikey nunca entra al nombre del archivo ni a los logs.
    cuerpo = re.sub(r"apikey=[^&]*", "apikey=OCULTA", cuerpo)
    return cuerpo or "index"


def sha_de(contenido: bytes) -> str:
    return hashlib.sha256(contenido).hexdigest()


def ocultar_secreto(texto: str) -> str:
    """Para logs y `source_url`: la apikey no se persiste nunca."""
    return re.sub(r"(apikey=)[^&\s]+", r"\1OCULTA", texto)
