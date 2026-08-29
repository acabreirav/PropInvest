"""Colector Gael Cloud — segunda fuente de UF y UTM. Tarea T-908, capa 6.

Existe por una razon medida, no por gusto: la API de la CMF **corta la conexion al azar**
(§ del modulo `cmf_indicadores`: la misma URL de 32 meses fallo y minutos despues devolvio
974 registros). Los reintentos con backoff absorben el corte, pero mientras la CMF sea la
unica fuente, un dia malo deja el modelo sin el valor de la UF — y sin UF no se convierte
ni un arriendo en pesos.

`legal_tier: api_oficial` — endpoint publico documentado, sin autenticacion ni scraping.

    https://api.gael.cloud/general/public/monedas          todas las series
    https://api.gael.cloud/general/public/monedas/{codigo} una serie

LIMITE DURO, y es la parte peligrosa de esta fuente
-----------------------------------------------------------------------------------
Mas de **9 peticiones en 10 segundos** y la IP queda **baneada una hora**
(`docs/04-legal.md` §65, `config/fuentes.yml`). Dos consecuencias en el codigo:

1. `Limitador` frena del lado del cliente ANTES de pedir, con margen: 6 peticiones por
   ventana de 10 s, no 9. El margen existe porque no sabemos si el servidor cuenta la
   ventana igual que nosotros.
2. Un **HTTP 429 no se reintenta jamas**. Reintentar un baneo solo lo prolonga. Es la
   diferencia central con `cmf_indicadores`, donde el corte SI es transitorio y SI se
   reintenta. Aca `TRANSITORIOS` excluye deliberadamente todo lo que huela a cupo.

LO QUE ESTA FUENTE **NO** HACE
-----------------------------------------------------------------------------------
El endpoint documentado en `docs/01-fuentes.md` no toma fechas: entrega el **valor
vigente**, no una serie historica. Asi que Gael **no reemplaza a la CMF para el backfill**
— cubre el caso "hoy la CMF no responde y necesito la UF de hoy". Si se le pide un periodo,
`collect()` falla con un mensaje que lo dice, en vez de devolver un dia y dejar creer que
devolvio treinta.

ADVERTENCIA DE PROCEDENCIA (misma disciplina que el ADR 001)
-----------------------------------------------------------------------------------
La forma de la respuesta NO ha sido verificada contra una respuesta viva: el entorno donde
se escribio este modulo tiene bloqueado el egreso hacia `api.gael.cloud`. Por eso:

- el parser **no asume** nombres de campo: los busca sin distinguir mayusculas entre un
  conjunto declarado de candidatos, y **falla ruidosamente** si encuentra cero o mas de uno;
- el numero **no se interpreta a la fuerza**: si el texto admite dos lecturas y ambas caen
  en el rango plausible, se levanta `ErrorDeFuente` en vez de elegir una. Confundir
  `"39.500"` chileno (treinta y nueve mil quinientos) con `39,5` es un error de mil veces
  sobre el valor que convierte TODO el modelo a pesos, y seria silencioso;
- `selftest()` deja `forma_verificada=False` mientras no vea una respuesta real.

`cli ingest --fuente gael_indicadores` sobre una maquina con salida a internet captura el
primer blob real; de ahi sale la fixture que cierra esta advertencia.
"""

from __future__ import annotations

import re
import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
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
    sha_de,
)
from flujocero.sources.cmf_indicadores import PLAUSIBLE

BASE = "https://api.gael.cloud/general/public/monedas"
PARSER_VERSION = "gael_indicadores/1.0.0"
TIMEOUT = 20.0

# serie interna -> (codigo en Gael, unidad). Solo las que este modelo usa. Pedir codigos
# que no necesitamos gastaria cupo de una fuente que castiga el exceso con una hora de baneo.
SERIES: dict[str, tuple[str, str]] = {
    "uf": ("UF", "CLP"),
    "utm": ("UTM", "CLP"),
}
POR_CODIGO = {codigo.upper(): serie for serie, (codigo, _u) in SERIES.items()}

# Candidatos de nombre de campo, POR NIVEL DE PREFERENCIA. Cada tupla es un nivel: se usa
# el primer nivel que exista en el registro, y dentro de un nivel dos coincidencias son un
# error, porque ahi si son sinonimos y no hay forma de saber cual es el bueno.
#
# La distincion importa y salio de un test: un registro real trae `Codigo` Y `Nombre` a la
# vez. Tratarlos como sinonimos ambiguos rechazaba una respuesta perfectamente legible.
# Pero `Valor` y `Value` juntos si son ambiguos de verdad, y ahi se falla.
CAMPOS_VALOR = (("valor", "value", "monto"),)
CAMPOS_FECHA = (("fecha", "date"), ("fechaactualizacion", "fecha_actualizacion"))
CAMPOS_CODIGO = (("codigo", "code"), ("moneda", "nombre", "name"))

# El cupo real es 9 peticiones / 10 s. Pedimos 6 porque no sabemos si el servidor cuenta la
# ventana como nosotros, y el castigo por equivocarse no es un 429 pasajero: es una hora.
CUPO_PETICIONES = 6
CUPO_VENTANA_S = 10.0

# Se reintenta lo que de verdad es transitorio. NOTA DELIBERADA: ningun error de cupo entra
# aca. Un 429 en esta fuente significa "estas baneado una hora"; reintentarlo lo empeora.
TRANSITORIOS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)
INTENTOS = 3

# Dos valores oficiales de la misma serie y el mismo dia deberian ser identicos. Se tolera
# una brecha de redondeo (la CMF publica 2 decimales, la columna guarda 6) y nada mas.
TOLERANCIA_REL = Decimal("0.0001")

_SOLO_DIGITOS = re.compile(r"^-?\d+$")


class ErrorDeFuente(RuntimeError):
    """La fuente respondio algo que no podemos interpretar. Nunca se traga en silencio (§11)."""


class CupoExcedido(ErrorDeFuente):
    """HTTP 429: la IP quedo baneada. No se reintenta — reintentar prolonga el baneo."""


class Indicador(BaseModel):
    """Una observacion de una serie financiera, con su procedencia completa (§3.1)."""

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
            raise ValueError(f"evidence_level invalido: {v}")
        return v


# --------------------------------------------------------------------------- cupo


class Limitador:
    """Cupo del lado del cliente. Frena ANTES de pedir, no despues de que te banean.

    El reloj y la espera entran por argumento para que los tests midan el comportamiento
    sin dormir de verdad (§11: cero fechas del sistema dentro de la logica).
    """

    def __init__(
        self,
        maximo: int = CUPO_PETICIONES,
        ventana_s: float = CUPO_VENTANA_S,
        reloj: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        if maximo < 1:
            raise ValueError("el cupo tiene que permitir al menos una peticion")
        self.maximo = maximo
        self.ventana_s = ventana_s
        self._reloj = reloj
        self._dormir = dormir
        self._marcas: deque[float] = deque()

    def _purgar(self, ahora: float) -> None:
        while self._marcas and ahora - self._marcas[0] >= self.ventana_s:
            self._marcas.popleft()

    def espera_necesaria(self) -> float:
        """Cuantos segundos habria que esperar para pedir sin pasarse. Puro, para tests."""
        ahora = self._reloj()
        self._purgar(ahora)
        if len(self._marcas) < self.maximo:
            return 0.0
        return max(0.0, self.ventana_s - (ahora - self._marcas[0]))

    def pedir_turno(self) -> float:
        """Bloquea lo que haga falta y anota la peticion. Devuelve los segundos esperados."""
        espera = self.espera_necesaria()
        if espera > 0:
            self._dormir(espera)
        ahora = self._reloj()
        self._purgar(ahora)
        self._marcas.append(ahora)
        return espera


# --------------------------------------------------------------------------- parseo puro


def a_decimal_desambiguada(texto: Any, rango: tuple[Decimal, Decimal] | None = None) -> Decimal:
    """Convierte el valor a Decimal sin adivinar el formato de miles.

    El problema real: `"39.500"` es treinta y nueve mil quinientos en formato chileno y
    treinta y nueve coma cinco en formato ingles. Elegir mal es un error de mil veces sobre
    el numero que convierte todo el modelo a pesos, y no se nota mirando.

    La regla, en orden:

    1. Si ya viene como numero JSON, se usa tal cual. No hay nada que interpretar.
    2. Si trae coma **y** punto, el ultimo separador es el decimal. Sin ambiguedad.
    3. Si trae solo coma, la coma es decimal. Ningun formato usa la coma como decimal
       y como miles a la vez.
    4. Si trae solo punto, hay dos lecturas. Se descarta la que caiga fuera del rango
       plausible de la serie. Si **ambas** caen dentro, se levanta `ErrorDeFuente`:
       preferimos no cargar el dato antes que cargarlo mil veces mal.
    """
    if isinstance(texto, bool):  # bool es subclase de int y no es un valor de serie
        raise ErrorDeFuente(f"valor booleano donde se esperaba un numero: {texto!r}")
    if isinstance(texto, int | float | Decimal):
        return Decimal(str(texto))

    limpio = str(texto).strip().replace(" ", "").replace(" ", "")
    if not limpio:
        raise ErrorDeFuente("valor vacio")

    tiene_coma = "," in limpio
    tiene_punto = "." in limpio

    if tiene_coma and tiene_punto:
        decimal_es_coma = limpio.rfind(",") > limpio.rfind(".")
        candidato = (
            limpio.replace(".", "").replace(",", ".")
            if decimal_es_coma
            else limpio.replace(",", "")
        )
        return _a_decimal(candidato, texto)

    if tiene_coma:
        return _a_decimal(limpio.replace(",", "."), texto)

    if not tiene_punto:
        if not _SOLO_DIGITOS.match(limpio):
            raise ErrorDeFuente(f"no se pudo interpretar el valor {texto!r}")
        return _a_decimal(limpio, texto)

    # Mas de un punto: no hay ambiguedad posible. Ningun formato usa el punto como decimal
    # dos veces, asi que todos son separadores de miles. Sin este caso, un `"1.234.567"`
    # perfectamente legible se rechazaba, porque la lectura "decimal" ni siquiera existe.
    if limpio.count(".") > 1:
        return _a_decimal(limpio.replace(".", ""), texto)

    # Un solo punto: las dos lecturas posibles.
    como_miles = _a_decimal(limpio.replace(".", ""), texto)
    como_decimal = _a_decimal(limpio, texto)
    if como_miles == como_decimal:
        return como_miles
    if rango is None:
        raise ErrorDeFuente(
            f"el valor {texto!r} admite dos lecturas ({como_miles} o {como_decimal}) y no se "
            "entrego rango plausible para desambiguar. Se rechaza en vez de adivinar."
        )
    lo, hi = rango
    cabe_miles = lo <= como_miles <= hi
    cabe_decimal = lo <= como_decimal <= hi
    if cabe_miles and not cabe_decimal:
        return como_miles
    if cabe_decimal and not cabe_miles:
        return como_decimal
    if cabe_miles and cabe_decimal:
        raise ErrorDeFuente(
            f"el valor {texto!r} admite dos lecturas ({como_miles} y {como_decimal}) y las dos "
            f"caen en el rango plausible [{lo}, {hi}]. Se rechaza en vez de adivinar."
        )
    raise ErrorDeFuente(
        f"el valor {texto!r} no cae en el rango plausible [{lo}, {hi}] con ninguna lectura "
        f"({como_miles} ni {como_decimal})"
    )


def _a_decimal(candidato: str, original: Any) -> Decimal:
    try:
        return Decimal(candidato)
    except InvalidOperation as exc:
        raise ErrorDeFuente(f"no se pudo interpretar el valor {original!r}") from exc


def a_fecha(texto: Any) -> date:
    """Interpreta la fecha sin resolver ambiguedades por corazonada.

    Acepta ISO (`2026-08-29`, con o sin hora) siempre. Acepta `DD-MM-AAAA` y `DD/MM/AAAA`
    **solo cuando el primer componente es mayor que 12**, o sea cuando no puede ser un mes.
    `05-08-2026` se rechaza a proposito: en Chile es 5 de agosto y en formato gringo es
    8 de mayo, y una UF con tres meses de error corrompe toda conversion de pesos a UF de
    ese dia. Se prefiere fallar fuerte y pinar el formato con una respuesta real.
    """
    if isinstance(texto, date) and not isinstance(texto, datetime):
        return texto
    if isinstance(texto, datetime):
        return texto.date()

    crudo = str(texto).strip()
    if not crudo:
        raise ErrorDeFuente("fecha vacia")

    iso = crudo.replace("Z", "").split("T")[0].split(" ")[0]
    if re.match(r"^\d{4}-\d{2}-\d{2}$", iso):
        try:
            return date.fromisoformat(iso)
        except ValueError as exc:
            raise ErrorDeFuente(f"fecha ISO invalida: {texto!r}") from exc

    partes = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$", crudo)
    if partes:
        a, b, anio = (int(x) for x in partes.groups())
        if a > 12:
            return date(anio, b, a)
        raise ErrorDeFuente(
            f"la fecha {texto!r} es ambigua: {a}-{b} puede ser dia-mes o mes-dia. Se rechaza "
            "en vez de adivinar; captura una respuesta real y fija el formato en el modulo."
        )
    raise ErrorDeFuente(f"formato de fecha no reconocido: {texto!r}")


def _campo(registro: dict[str, Any], niveles: tuple[tuple[str, ...], ...], que: str) -> Any:
    """Busca el campo recorriendo los niveles de preferencia, sin distinguir mayusculas.

    Gana el primer nivel que aparezca en el registro. Dentro de un nivel, dos coincidencias
    son un error: ahi los nombres si son sinonimos y elegir uno seria adivinar. Entre
    niveles no hay ambiguedad — un campo llamado `Codigo` es el codigo aunque tambien
    venga un `Nombre`.
    """
    for candidatos in niveles:
        encontrados = {
            k: v for k, v in registro.items() if k.strip().lower().replace(" ", "") in candidatos
        }
        if len(encontrados) > 1:
            raise ErrorDeFuente(
                f"mas de un campo de {que} en el mismo registro ({sorted(encontrados)}): no hay "
                "forma de saber cual es el bueno. Se rechaza en vez de elegir."
            )
        if encontrados:
            return next(iter(encontrados.values()))
    todos = [c for nivel in niveles for c in nivel]
    raise ErrorDeFuente(f"ningun campo de {que} {todos} en el registro; claves: {sorted(registro)}")


def _identificar_serie(registro: dict[str, Any]) -> str | None:
    """Deduce la serie desde el propio registro, no desde la URL pedida: si Gael devuelve
    otra cosa de la que se le pidio, queremos notarlo."""
    bruto = str(_campo(registro, CAMPOS_CODIGO, "codigo")).strip().upper()
    if bruto in POR_CODIGO:
        return POR_CODIGO[bruto]
    # Los nombres largos ("Unidad de Fomento") no son codigos: se descartan sin ruido,
    # porque el endpoint general devuelve series que este modelo no usa.
    return None


# --------------------------------------------------------------------------- colector


class GaelIndicadores:
    """Segunda fuente de UF y UTM. Cumple el protocolo `Source` del §7.1."""

    id = "gael_indicadores"
    legal_tier: LegalTier = "api_oficial"
    parser_version = PARSER_VERSION

    def __init__(
        self,
        user_agent: str,
        series: tuple[str, ...] = ("uf", "utm"),
        cliente: httpx.Client | None = None,
        raiz_cruda: Path | None = None,
        limitador: Limitador | None = None,
    ) -> None:
        desconocidas = set(series) - set(SERIES)
        if desconocidas:
            raise ValueError(f"series desconocidas: {sorted(desconocidas)}")
        self.user_agent = user_agent
        self.series = series
        self._cliente = cliente
        self.raiz_cruda = raiz_cruda
        self.limitador = limitador or Limitador()

    # ------------------------------------------------------------------ legalidad

    def robots_ok(self) -> RobotsVerdict:
        """API publica documentada. Igual se consulta robots y se guarda el snapshot,
        porque el §3.1 exige un `robots_snapshot_sha` en cada fila.

        Esta peticion tambien pasa por el limitador. Parece un detalle y no lo es: el
        servidor de Gael cuenta TODOS los GET que le llegan, incluido el del robots.txt.
        Un contador que ignora una de cada tres peticiones no es un contador.
        """
        from flujocero.sources import robots_check

        self.limitador.pedir_turno()
        return robots_check.verificar(
            BASE,
            self.user_agent,
            source_id=self.id,
            cliente=self._cliente,
            raiz_cruda=self.raiz_cruda,
        )

    # ------------------------------------------------------------------ recoleccion

    def url(self, serie: str) -> str:
        return f"{BASE}/{SERIES[serie][0]}"

    def _pedir(self, cliente: httpx.Client, destino: str) -> httpx.Response:
        """GET con cupo respetado y backoff. Un 429 corta de inmediato, sin reintentar."""

        @retry(
            retry=retry_if_exception_type(TRANSITORIOS),
            stop=stop_after_attempt(INTENTOS),
            wait=wait_exponential_jitter(initial=1, max=15),
            reraise=True,
        )
        def _intento() -> httpx.Response:
            self.limitador.pedir_turno()
            resp = cliente.get(destino, headers={"User-Agent": self.user_agent})
            if resp.status_code == 429:
                raise CupoExcedido(
                    f"{destino} respondio 429: se excedio el cupo de Gael (max 9 peticiones "
                    "en 10 s) y la IP queda baneada UNA HORA. No se reintenta a proposito. "
                    "Espera una hora o usa la CMF."
                )
            return resp

        return _intento()

    def collect(self, scope: Scope) -> Iterator[RawDoc]:
        """Descarga el valor VIGENTE y lo persiste antes de parsear (§3.6).

        Si el scope pide un periodo, falla: el endpoint publico de Gael no toma fechas y
        devolver un dia cuando te pidieron treinta es peor que no devolver nada.
        """
        if scope.desde or scope.hasta:
            raise ErrorDeFuente(
                f"Gael no sirve series historicas: el endpoint publico {BASE} entrega el valor "
                f"vigente y no toma fechas. Se pidio {scope.desde}..{scope.hasta}. Para el "
                "backfill la unica fuente sigue siendo la CMF (cmf_indicadores)."
            )

        veredicto = self.robots_ok()
        if not veredicto.allowed or not veredicto.snapshot_sha:
            raise ErrorDeFuente(
                f"no se recolecta: verificacion de robots.txt no superada — {veredicto.motivo}"
            )

        cliente = self._cliente or httpx.Client(timeout=TIMEOUT, follow_redirects=True)
        propio = self._cliente is None
        enviadas = 0
        try:
            for serie in self.series:
                if scope.limite_docs is not None and enviadas >= scope.limite_docs:
                    return
                destino = self.url(serie)
                try:
                    resp = self._pedir(cliente, destino)
                except CupoExcedido:
                    raise
                except httpx.HTTPError as exc:
                    raise ErrorDeFuente(
                        f"no se pudo alcanzar {destino} tras {INTENTOS} intentos: "
                        f"{type(exc).__name__}: {exc}"
                    ) from exc
                if resp.status_code != 200:
                    raise ErrorDeFuente(
                        f"{destino} respondio {resp.status_code}: {resp.text[:200]}"
                    )
                enviadas += 1
                yield escribir_crudo(
                    source_id=self.id,
                    url=destino,
                    contenido=resp.content,
                    momento=scope.ahora,
                    robots_snapshot_sha=veredicto.snapshot_sha,
                    nombre=f"{serie}_vigente",
                    raiz=self.raiz_cruda,
                    parser_version=self.parser_version,
                )
        finally:
            if propio:
                cliente.close()

    # ------------------------------------------------------------------ parseo

    def parse(self, doc: RawDoc) -> list[Indicador]:
        """Acepta tanto el objeto de una serie como la lista del endpoint general.

        Las series que este modelo no usa se descartan sin ruido; lo que NO se descarta en
        silencio es un registro de una serie conocida que no se puede interpretar.
        """
        datos = doc.json()
        if isinstance(datos, dict):
            registros = [datos]
        elif isinstance(datos, list):
            registros = [r for r in datos if isinstance(r, dict)]
        else:
            raise ErrorDeFuente(f"la respuesta de {doc.ruta} no es objeto ni lista JSON")
        if not registros:
            raise ErrorDeFuente(f"la respuesta de {doc.ruta} no trae ningun registro")

        proc = Procedencia(
            source_id=self.id,
            source_url=doc.url,
            fetched_at=doc.fetched_at,
            parser_version=self.parser_version,
            raw_blob_path=str(doc.ruta),
            robots_snapshot_sha=doc.robots_snapshot_sha,
        )
        filas: list[Indicador] = []
        for registro in registros:
            serie = _identificar_serie(registro)
            if serie is None:
                continue
            valor = a_decimal_desambiguada(
                _campo(registro, CAMPOS_VALOR, "valor"), PLAUSIBLE.get(serie)
            )
            filas.append(
                Indicador(
                    fecha=a_fecha(_campo(registro, CAMPOS_FECHA, "fecha")),
                    serie=serie,
                    valor=valor,
                    unidad=SERIES[serie][1],
                    evidence_level="V",
                    **proc.as_dict(),
                )
            )
        if not filas:
            raise ErrorDeFuente(
                f"ningun registro de {doc.ruta} corresponde a una serie conocida "
                f"{sorted(POR_CODIGO)}"
            )
        return filas

    # ------------------------------------------------------------------ selftest

    def selftest(
        self,
        fixture: RawDoc | None = None,
        muestra_viva: list[RawDoc] | None = None,
        n_filas_corrida_anterior: int | None = None,
    ) -> SelfTestReport:
        """Los cuatro checks del §7.1, con la misma honestidad que el modulo de la CMF:
        sin muestra viva, `forma_verificada` queda en falso en vez de fingir."""
        rep = SelfTestReport(source_id=self.id, ok=True)
        rep.n_filas_corrida_anterior = n_filas_corrida_anterior

        docs = ([fixture] if fixture else []) + (muestra_viva or [])
        if not docs:
            rep.fallar("hay_documentos", "sin fixture ni muestra viva que verificar")
            return rep

        filas: list[Indicador] = []
        for doc in docs[:6]:  # el §7.1 pide muestra viva de <=5 documentos
            try:
                filas.extend(self.parse(doc))
            except (ErrorDeFuente, ValueError) as exc:
                rep.fallar("parseo", f"{doc.ruta}: {type(exc).__name__}: {exc}")
                return rep
        rep.pasar("parseo")
        rep.n_filas = len(filas)

        requeridos = ("fecha", "serie", "valor", "unidad", *Procedencia.__dataclass_fields__)
        completos = sum(
            1 for f in filas if all(getattr(f, c, None) not in (None, "") for c in requeridos)
        )
        cobertura = completos / len(filas) if filas else 0.0
        if cobertura < 0.95:
            rep.fallar("campos_requeridos", f"cobertura {cobertura:.1%} < 95%")
        else:
            rep.pasar("campos_requeridos")

        for f in filas:
            lo, hi = PLAUSIBLE[f.serie]
            if not (lo <= f.valor <= hi):
                rep.fallar(
                    "rangos_plausibles", f"{f.serie} {f.fecha} = {f.valor} fuera de [{lo}, {hi}]"
                )
                break
        else:
            rep.pasar("rangos_plausibles")

        caida = rep.caida_pct
        if caida is not None and caida > 0.30:
            rep.fallar(
                "conteo_estable",
                f"el conteo cayo {caida:.0%} vs la corrida anterior "
                f"({rep.n_filas_corrida_anterior} → {rep.n_filas})",
            )
        else:
            rep.pasar("conteo_estable")

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
                "sin muestra viva: la forma de la respuesta proviene de la documentacion y no "
                "ha sido confirmada contra una respuesta real de api.gael.cloud."
            )
        return rep


# --------------------------------------------------------------------------- carga


@dataclass(frozen=True)
class Discrepancia:
    """Dos fuentes oficiales dicen cosas distintas del mismo dia. Eso es un hallazgo."""

    fecha: date
    serie: str
    source_id_existente: str
    valor_existente: Decimal
    valor_nuevo: Decimal

    @property
    def brecha_rel(self) -> Decimal:
        if self.valor_existente == 0:
            return Decimal(0)
        return abs(self.valor_nuevo - self.valor_existente) / abs(self.valor_existente)

    def __str__(self) -> str:
        return (
            f"{self.serie} {self.fecha}: {self.source_id_existente} dice "
            f"{self.valor_existente} y gael_indicadores dice {self.valor_nuevo} "
            f"({self.brecha_rel:.4%})"
        )


@dataclass
class ReporteCarga:
    """Que hizo la carga. El fallback rellena huecos; no pisa a la fuente primaria."""

    insertadas: int = 0
    ya_estaban: int = 0
    discrepancias: list[Discrepancia] = field(default_factory=list)

    def __str__(self) -> str:
        base = f"{self.insertadas} insertadas · {self.ya_estaban} ya estaban"
        if self.discrepancias:
            base += f" · {len(self.discrepancias)} DISCREPANCIAS entre fuentes"
        return base


INSERT_SI_FALTA = """
INSERT INTO dim_tiempo_financiero
  (fecha, serie, valor, unidad, evidence_level,
   source_id, source_url, fetched_at, parser_version, raw_blob_path, robots_snapshot_sha)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (fecha, serie) DO NOTHING
"""


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


def cargar_en_duckdb(
    conexion: Any, filas: list[Indicador], tolerancia: Decimal = TOLERANCIA_REL
) -> ReporteCarga:
    """Rellena huecos. **Nunca pisa una fila que ya existe**, venga de donde venga.

    Esta es la diferencia deliberada con `cmf_indicadores.cargar_en_duckdb`, que hace
    `ON CONFLICT DO UPDATE`. Una fuente de respaldo que sobrescribe a la primaria convierte
    una caida pasajera de la CMF en un cambio permanente de los datos, sin que nadie lo
    pida y sin que quede rastro. Aca el conflicto no se resuelve: se **reporta**.

    Cuando las dos fuentes coinciden dentro de la tolerancia de redondeo, no hay nada que
    decir. Cuando no coinciden, es un hallazgo de calidad de datos y sale en el reporte.
    """
    rep = ReporteCarga()
    for f in filas:
        existente = conexion.execute(
            "SELECT valor, source_id FROM dim_tiempo_financiero WHERE fecha = ? AND serie = ?",
            (f.fecha, f.serie),
        ).fetchone()
        if existente is None:
            conexion.execute(INSERT_SI_FALTA, fila_a_sql(f))
            rep.insertadas += 1
            continue
        rep.ya_estaban += 1
        valor_previo = Decimal(str(existente[0]))
        d = Discrepancia(
            fecha=f.fecha,
            serie=f.serie,
            source_id_existente=str(existente[1]),
            valor_existente=valor_previo,
            valor_nuevo=f.valor,
        )
        if d.brecha_rel > tolerancia:
            rep.discrepancias.append(d)
    return rep


def desde_entorno(entorno: dict[str, str], **kw: Any) -> GaelIndicadores:
    """Construye el colector desde variables de entorno ya cargadas. Gael no pide
    credencial: lo unico que sale del entorno es el user-agent con que nos identificamos."""
    ua = entorno.get("USER_AGENT", "").strip() or "FlujoCero-ResearchBot/1.0"
    return GaelIndicadores(user_agent=ua, **kw)


def ahora_utc() -> datetime:
    """Unico punto donde este modulo mira el reloj, y esta fuera de la logica (§11)."""
    return datetime.now(UTC)


__all__ = [
    "BASE",
    "CUPO_PETICIONES",
    "CUPO_VENTANA_S",
    "PARSER_VERSION",
    "SERIES",
    "CupoExcedido",
    "Discrepancia",
    "ErrorDeFuente",
    "GaelIndicadores",
    "Indicador",
    "Limitador",
    "ReporteCarga",
    "a_decimal_desambiguada",
    "a_fecha",
    "cargar_en_duckdb",
    "desde_entorno",
    "sha_de",
]
