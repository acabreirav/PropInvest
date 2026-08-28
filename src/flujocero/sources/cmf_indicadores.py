"""Colector CMF — UF, UTM e IPC. Tarea T-010, capa 6.

Fuente: API de la Comisión para el Mercado Financiero, `api-sbifv3`.
`legal_tier: api_oficial` — API pública con apikey bajo registro gratuito. No es scraping.

Forma de la respuesta, según la documentación oficial
(https://api.cmfchile.cl/documentacion/UF.html):

    {"UFs": [{"Fecha": "2010-01-01", "Valor": "20.939,49"}]}

La clave de nivel superior cambia por serie: `UFs`, `UTMs`, `IPCs`. El valor viene en
formato chileno — punto de miles, coma decimal — y es texto, no número.

Rutas verificadas contra la documentación:
    /uf?apikey=&formato=json                        valor de hoy
    /uf/periodo/{a1}/{a2}?apikey=&formato=json      rango de años
    /uf/periodo/{a1}/{m1}/{a2}/{m2}?...             rango de meses

ESTABILIDAD DE LA FUENTE: medido con `cli probe` el 28-ago-2026 contra la API real, el
servidor **corta la conexion al azar** (`RemoteProtocolError: Server disconnected without
sending a response`), sin relacion con el tamano del rango pedido: la misma URL de 32 meses
fallo y minutos despues devolvio 974 registros. Por eso `_pedir` reintenta con backoff
exponencial. El endpoint sin periodo (`/uf` a secas, el valor de hoy) fallo en esa misma
medicion; se desconoce si es el mismo corte intermitente o si esta roto.

ADVERTENCIA DE PROCEDENCIA: la forma de arriba está tomada de la documentación oficial de
la CMF, pero NO ha sido verificada todavía contra una respuesta viva — el entorno donde se
escribió este módulo tiene bloqueado el egreso hacia `api.cmfchile.cl`. Por eso `selftest()`
distingue explícitamente entre la fixture derivada de la documentación y una muestra viva,
y sólo declara `forma_verificada` cuando ha visto una respuesta real. Ver docs/adr/001.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field, field_validator
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from flujocero.sources.base import (
    LegalTier,
    Procedencia,
    RawDoc,
    RobotsVerdict,
    Scope,
    SelfTestReport,
    escribir_crudo,
    ocultar_secreto,
    sha_de,
)

BASE = "https://api.cmfchile.cl/api-sbifv3/recursos_api"
PARSER_VERSION = "cmf_indicadores/1.1.0"
TIMEOUT = 30.0

# §5 del contrato: backoff exponencial con jitter. Estos son los fallos que SI vale
# reintentar — la conexion se corto o expiro. Un 401 o un 404 no se reintentan nunca:
# reintentar un error de credencial solo consigue que te bloqueen.
TRANSITORIOS = (
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.ReadError,
)
INTENTOS = 4

# MEDIDO el 28-ago-2026 con `cli probe` desde la maquina del usuario, contra la API real:
# 1 mes, 8 meses, 1 ano y 32 meses devolvieron HTTP 200 sin problema (974 registros el mas
# largo). La MISMA peticion de 32 meses habia fallado minutos antes con
# `RemoteProtocolError`. O sea: el corte es INTERMITENTE, no depende del tamano del rango.
# La hipotesis inicial —que el rango largo era la causa— quedo desmentida por la medicion.
#
# El troceado se conserva igual, por dos razones que si se sostienen: cada ventana reintenta
# por separado, asi que un corte no obliga a rehacer los 32 meses; y respuestas mas chicas
# son mas amables con un servidor que ya demostro ser inestable. Lo que arregla el fallo son
# los reintentos de `_pedir`, no esto.
MESES_POR_PETICION = 12

# serie interna -> (ruta del recurso, clave del envoltorio JSON, unidad)
SERIES: dict[str, tuple[str, str, str]] = {
    "uf": ("uf", "UFs", "CLP"),
    "utm": ("utm", "UTMs", "CLP"),
    "ipc_var_m": ("ipc", "IPCs", "pct"),
}

# Rangos de plausibilidad del §7.1, aplicados a lo que sabemos de estas series.
# La UF nace en 1967; entre 2024 y 2026 se mueve en decenas de miles de pesos.
PLAUSIBLE: dict[str, tuple[Decimal, Decimal]] = {
    "uf": (Decimal("20000"), Decimal("100000")),
    "utm": (Decimal("40000"), Decimal("200000")),
    "ipc_var_m": (Decimal("-5"), Decimal("5")),
}


class ErrorDeFuente(RuntimeError):
    """La fuente respondió algo que no podemos interpretar. Nunca se traga en silencio (§11)."""


class Indicador(BaseModel):
    """Una observación de una serie financiera, con su procedencia completa."""

    fecha: date
    serie: str
    valor: Decimal
    unidad: str
    evidence_level: str = Field(default="V")

    source_id: str
    source_url: str
    fetched_at: datetime
    parser_version: str
    raw_blob_path: str
    robots_snapshot_sha: str

    @field_validator("evidence_level")
    @classmethod
    def _nivel_valido(cls, v: str) -> str:
        if v not in {"V", "D", "E", "ND"}:
            raise ValueError(f"evidence_level inválido: {v}")
        return v


def ventanas(desde: str, hasta: str, meses: int = MESES_POR_PETICION) -> list[tuple[str, str]]:
    """Parte un rango AAAA-MM en tramos de a lo mas `meses`, alineados al ano calendario.

    NO existe porque los rangos largos fallen: se midio y 32 meses responden bien. Existe
    para que un corte de conexion —que en esta API ocurre al azar— cueste rehacer una
    ventana y no el periodo entero. Es pura y testeable.
    """
    a1, m1 = (int(x) for x in desde.split("-"))
    a2, m2 = (int(x) for x in hasta.split("-"))
    if (a1, m1) > (a2, m2):
        raise ValueError(f"el rango {desde}..{hasta} esta invertido")
    salida: list[tuple[str, str]] = []
    ay, am = a1, m1
    while (ay, am) <= (a2, m2):
        total = (ay * 12 + am - 1) + meses - 1
        by, bm = divmod(total, 12)
        bm += 1
        if (by, bm) > (a2, m2):
            by, bm = a2, m2
        salida.append((f"{ay:04d}-{am:02d}", f"{by:04d}-{bm:02d}"))
        total = by * 12 + bm  # mes siguiente
        ay, am = divmod(total, 12)
        am += 1
    return salida


def a_decimal(texto: str) -> Decimal:
    """Convierte el formato chileno de la CMF a Decimal: '20.939,49' -> 20939.49.

    Es puro y determinístico a propósito: es el punto donde un cambio silencioso de
    formato en el origen se convierte en un error visible en vez de en un número mal leído.
    """
    limpio = texto.strip()
    if not limpio:
        raise ErrorDeFuente("valor vacío")
    # En el formato chileno el punto es SIEMPRE separador de miles y la coma es SIEMPRE
    # separador decimal. No se decide caso a caso: tratar "40.804" como cuarenta coma ocho
    # en vez de cuarenta mil ochocientos cuatro es un error de mil veces sobre el valor que
    # convierte todo el modelo a pesos, y es silencioso.
    limpio = limpio.replace(".", "").replace(",", ".")
    try:
        return Decimal(limpio)
    except InvalidOperation as exc:
        raise ErrorDeFuente(f"no se pudo interpretar el valor {texto!r}") from exc


class CmfIndicadores:
    """Colector de UF, UTM e IPC desde la CMF. Cumple el protocolo `Source` del §7.1."""

    id = "cmf_indicadores"
    legal_tier: LegalTier = "api_oficial"
    parser_version = PARSER_VERSION

    def __init__(
        self,
        apikey: str,
        user_agent: str,
        series: tuple[str, ...] = ("uf", "utm", "ipc_var_m"),
        cliente: httpx.Client | None = None,
        raiz_cruda: Path | None = None,
        pausa_s: float = 0.35,
    ) -> None:
        desconocidas = set(series) - set(SERIES)
        if desconocidas:
            raise ValueError(f"series desconocidas: {sorted(desconocidas)}")
        self.apikey = apikey
        self.user_agent = user_agent
        self.series = series
        self._cliente = cliente
        self.raiz_cruda = raiz_cruda
        self.pausa_s = pausa_s

    # ------------------------------------------------------------------ legalidad

    def robots_ok(self) -> RobotsVerdict:
        """API oficial con credencial propia: el acceso lo gobierna el registro y los
        términos del servicio, no robots.txt. Igual se consulta y se guarda el snapshot,
        porque el §3.1 exige un `robots_snapshot_sha` en cada fila."""
        from flujocero.sources import robots_check

        return robots_check.verificar(
            f"{BASE}/uf",
            self.user_agent,
            source_id=self.id,
            cliente=self._cliente,
            raiz_cruda=self.raiz_cruda,
        )

    # ------------------------------------------------------------------ recolección

    def url(self, serie: str, desde: str | None = None, hasta: str | None = None) -> str:
        recurso = SERIES[serie][0]
        if desde and hasta:
            a1, m1 = desde.split("-")
            a2, m2 = hasta.split("-")
            ruta = f"{BASE}/{recurso}/periodo/{a1}/{m1}/{a2}/{m2}"
        else:
            ruta = f"{BASE}/{recurso}"
        return f"{ruta}?apikey={self.apikey}&formato=json"

    def _pedir(self, cliente: httpx.Client, destino: str) -> httpx.Response:
        """GET con backoff exponencial y jitter (§5). Solo reintenta fallos transitorios."""

        @retry(
            retry=retry_if_exception_type(TRANSITORIOS),
            stop=stop_after_attempt(INTENTOS),
            wait=wait_exponential_jitter(initial=1, max=20),
            reraise=True,
        )
        def _intento() -> httpx.Response:
            return cliente.get(destino, headers={"User-Agent": self.user_agent})

        return _intento()

    def collect(self, scope: Scope) -> Iterator[RawDoc]:
        """Descarga y persiste en la zona cruda ANTES de parsear (§3.6).

        El periodo se trocea en ventanas de a lo mas un ano para que un corte cueste
        rehacer una ventana y no todo. El corte en si lo absorbe `_pedir` con reintentos.
        """
        veredicto = self.robots_ok()
        if not veredicto.allowed or not veredicto.snapshot_sha:
            # §3.5: la verificación de robots pasa ANTES de recolectar. Y sin snapshot_sha
            # no hay procedencia completa, así que la fila no podría insertarse igual (§3.1).
            raise ErrorDeFuente(
                f"no se recolecta: verificación de robots.txt no superada — {veredicto.motivo}"
            )
        tramos: list[tuple[str | None, str | None]]
        if scope.desde and scope.hasta:
            tramos = list(ventanas(scope.desde, scope.hasta))  # type: ignore[arg-type]
        else:
            tramos = [(None, None)]

        cliente = self._cliente or httpx.Client(timeout=TIMEOUT, follow_redirects=True)
        propio = self._cliente is None
        enviadas = 0
        try:
            for serie in self.series:
                for desde, hasta in tramos:
                    if scope.limite_docs is not None and enviadas >= scope.limite_docs:
                        return
                    destino = self.url(serie, desde, hasta)
                    if enviadas and self.pausa_s:
                        time.sleep(self.pausa_s)
                    try:
                        resp = self._pedir(cliente, destino)
                    except httpx.HTTPError as exc:
                        raise ErrorDeFuente(
                            f"no se pudo alcanzar {ocultar_secreto(destino)} tras "
                            f"{INTENTOS} intentos: {type(exc).__name__}: {exc}"
                        ) from exc
                    if resp.status_code != 200:
                        raise ErrorDeFuente(
                            f"{ocultar_secreto(destino)} respondió {resp.status_code}: "
                            f"{resp.text[:200]}"
                        )
                    enviadas += 1
                    yield escribir_crudo(
                        source_id=self.id,
                        url=ocultar_secreto(destino),
                        contenido=resp.content,
                        momento=scope.ahora,
                        robots_snapshot_sha=veredicto.snapshot_sha,
                        nombre=f"{serie}_{desde or 'hoy'}_{hasta or ''}",
                        raiz=self.raiz_cruda,
                    )
        finally:
            if propio:
                cliente.close()

    # ------------------------------------------------------------------ parseo

    def parse(self, doc: RawDoc) -> list[Indicador]:
        datos = doc.json()
        serie, envoltorio = self._identificar(datos, doc)
        crudas = datos[envoltorio]
        if not isinstance(crudas, list):
            raise ErrorDeFuente(f"{envoltorio} no es una lista en {doc.ruta}")

        unidad = SERIES[serie][2]
        proc = Procedencia(
            source_id=self.id,
            source_url=doc.url,
            fetched_at=doc.fetched_at,
            parser_version=self.parser_version,
            raw_blob_path=str(doc.ruta),
            robots_snapshot_sha=doc.robots_snapshot_sha,
        )
        filas: list[Indicador] = []
        for cruda in crudas:
            if "Fecha" not in cruda or "Valor" not in cruda:
                raise ErrorDeFuente(f"registro sin Fecha/Valor en {doc.ruta}: {cruda!r}")
            filas.append(
                Indicador(
                    fecha=date.fromisoformat(cruda["Fecha"]),
                    serie=serie,
                    valor=a_decimal(str(cruda["Valor"])),
                    unidad=unidad,
                    evidence_level="V",
                    **proc.as_dict(),
                )
            )
        return filas

    def _identificar(self, datos: Any, doc: RawDoc) -> tuple[str, str]:
        """Deduce la serie desde la clave de nivel superior del JSON, no desde la URL:
        si la CMF renombra el envoltorio, queremos un error, no una fila mal etiquetada."""
        if not isinstance(datos, dict):
            raise ErrorDeFuente(f"la respuesta de {doc.ruta} no es un objeto JSON")
        for serie, (_, envoltorio, _u) in SERIES.items():
            if envoltorio in datos:
                return serie, envoltorio
        raise ErrorDeFuente(
            f"ninguna clave conocida {[v[1] for v in SERIES.values()]} en {doc.ruta}; "
            f"encontradas: {sorted(datos)}"
        )

    # ------------------------------------------------------------------ selftest

    def selftest(
        self,
        fixture: RawDoc | None = None,
        muestra_viva: list[RawDoc] | None = None,
        n_filas_corrida_anterior: int | None = None,
    ) -> SelfTestReport:
        """Los cuatro checks del §7.1.

        `muestra_viva` es opcional a propósito: donde no hay salida de red, el selftest
        corre contra la fixture y deja `forma_verificada` en falso, en vez de fingir que
        vio una respuesta real.
        """
        rep = SelfTestReport(source_id=self.id, ok=True)
        rep.n_filas_corrida_anterior = n_filas_corrida_anterior

        docs = [d for d in ([fixture] if fixture else []) + (muestra_viva or [])]
        if not docs:
            rep.fallar("hay_documentos", "sin fixture ni muestra viva que verificar")
            return rep

        filas: list[Indicador] = []
        for doc in docs[:6]:  # el §7.1 pide muestra viva de ≤5 documentos
            try:
                filas.extend(self.parse(doc))
            except (ErrorDeFuente, ValueError) as exc:
                rep.fallar("parseo", f"{doc.ruta}: {type(exc).__name__}: {exc}")
                return rep
        rep.pasar("parseo")
        rep.n_filas = len(filas)

        # 1 · campos requeridos ≥95%
        requeridos = ("fecha", "serie", "valor", "unidad", *Procedencia.__dataclass_fields__)
        completos = sum(
            1 for f in filas if all(getattr(f, c, None) not in (None, "") for c in requeridos)
        )
        cobertura = completos / len(filas) if filas else 0.0
        if cobertura < 0.95:
            rep.fallar("campos_requeridos", f"cobertura {cobertura:.1%} < 95%")
        else:
            rep.pasar("campos_requeridos")

        # 2 · rangos plausibles
        for f in filas:
            lo, hi = PLAUSIBLE[f.serie]
            if not (lo <= f.valor <= hi):
                rep.fallar(
                    "rangos_plausibles",
                    f"{f.serie} {f.fecha} = {f.valor} fuera de [{lo}, {hi}]",
                )
                break
        else:
            rep.pasar("rangos_plausibles")

        # 3 · detector de parser roto: caída >30% vs la última corrida exitosa
        caida = rep.caida_pct
        if caida is not None and caida > 0.30:
            rep.fallar(
                "conteo_estable",
                f"el conteo cayó {caida:.0%} vs la corrida anterior "
                f"({rep.n_filas_corrida_anterior} → {rep.n_filas})",
            )
        else:
            rep.pasar("conteo_estable")

        # 4 · robots coherente con el legal_tier declarado
        if muestra_viva:
            v = self.robots_ok()
            if not v.allowed:
                rep.fallar("robots", v.motivo)
            else:
                rep.pasar("robots")
            rep.checks["forma_verificada"] = True
        else:
            rep.checks["forma_verificada"] = False
            rep.detalle["forma_verificada"] = (
                "sin muestra viva: la forma proviene de la documentación oficial de la CMF "
                "y no ha sido confirmada contra una respuesta real (ver docs/adr/001)."
            )
        return rep


def fila_a_sql(f: Indicador) -> tuple[Any, ...]:
    """Orden de columnas de `dim_tiempo_financiero`."""
    return (
        f.fecha,
        f.serie,
        f.valor,
        f.unidad,
        f.evidence_level,
        f.source_id,
        f.source_url,
        f.fetched_at,
        f.parser_version,
        f.raw_blob_path,
        f.robots_snapshot_sha,
    )


UPSERT = """
INSERT INTO dim_tiempo_financiero
  (fecha, serie, valor, unidad, evidence_level,
   source_id, source_url, fetched_at, parser_version, raw_blob_path, robots_snapshot_sha)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (fecha, serie) DO UPDATE SET
  valor = excluded.valor, unidad = excluded.unidad,
  evidence_level = excluded.evidence_level,
  source_id = excluded.source_id, source_url = excluded.source_url,
  fetched_at = excluded.fetched_at, parser_version = excluded.parser_version,
  raw_blob_path = excluded.raw_blob_path,
  robots_snapshot_sha = excluded.robots_snapshot_sha
"""


def cargar_en_duckdb(conexion: Any, filas: list[Indicador]) -> int:
    """Idempotente por clave natural (§3.6): re-ejecutar el mismo día no duplica."""
    for f in filas:
        conexion.execute(UPSERT, fila_a_sql(f))
    return len(filas)


def desde_entorno(entorno: dict[str, str], **kw: Any) -> CmfIndicadores:
    """Construye el colector desde variables de entorno ya cargadas. Sin leer .env acá:
    quién lee el entorno es la CLI, no el módulo."""
    apikey = entorno.get("CMF_APIKEY", "").strip()
    if not apikey:
        raise ErrorDeFuente("falta CMF_APIKEY en el entorno. Se obtiene gratis en api.cmfchile.cl.")
    ua = entorno.get("USER_AGENT", "").strip() or "FlujoCero-ResearchBot/1.0"
    return CmfIndicadores(apikey=apikey, user_agent=ua, **kw)


__all__ = [
    "BASE",
    "PARSER_VERSION",
    "SERIES",
    "CmfIndicadores",
    "ErrorDeFuente",
    "Indicador",
    "a_decimal",
    "cargar_en_duckdb",
    "desde_entorno",
    "sha_de",
]
