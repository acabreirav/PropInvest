"""Colector CMF — tasas hipotecarias por banco. Tarea T-012, capa 6.

Fuente: planilla XLS que la CMF publica en su portal de estadísticas.
`legal_tier: json_publico` — archivo estático publicado, sin auth.

## Estructura real, verificada contra el archivo

Una hoja por monto de crédito (`Tasa Fija UF 1000`, `UF 1500`, `UF 3000`) más una hoja
`Conceptos` que es glosario y se ignora. Dentro de cada hoja:

    fila N   'Fecha de la consulta: 22 al 26 de mayo de 2006'
    fila N+k 'MONTO DEL CRÉDITO:'      ...  '1.000 UF'
             'VALOR DE LA PROPIEDAD:'  ...  '1.350 UF'
             'PLAZO DEL CRÉDITO:'      ...  '20 AÑOS'
    fila M   'Nombre de la institución' | 'Letras de Crédito (1)' | 'Mutuo Hipotecario
              Endosable' | 'Mutuo Hipotecario No Endosable'
    filas    'Banco BICE' | 0.056 | 0.0515 | 0.0515
             'Banco BBVA' | 'n/o'  | 0.0644 | 0.0614      <- 'n/o' = no ofrece el producto

**Las filas NO están en índices fijos**: entre la primera hoja y las siguientes todo se
corre una fila. Por eso este parser localiza cada bloque por su etiqueta y nunca por
número de fila. Si la CMF mueve algo, el parser falla ruidosamente en vez de leer basura.

## Advertencia de obsolescencia

El archivo publicado hoy en `articles-46417_recurso_1.xls` es de **mayo de 2006**: lo dice
su propia celda `Fecha de la consulta`, lo firma la SBIF (que dejó de existir en 2019) y
lista bancos disueltos. `antiguedad_meses` y el `selftest` lo detectan y lo rechazan: una
tasa de 2006 usada para una decisión de 2026 es peor que no tener el dato.

Dos metadatos más que impiden comparar estas tasas con nuestro escenario base sin ajustar:
el plazo de la planilla es **20 años** (el modelo usa 30) y el crédito es el **75% del
valor de la propiedad** (el modelo usa 90% con FOGAES).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from flujocero.sources.base import (
    LegalTier,
    Procedencia,
    RawDoc,
    RobotsVerdict,
    Scope,
    SelfTestReport,
    escribir_crudo,
)

URL = "https://www.cmfchile.cl/portal/estadisticas/617/articles-46417_recurso_1.xls"
PARSER_VERSION = "cmf_tasas_hipotecarias/1.0.0"
TIMEOUT = 60.0

# Una tasa hipotecaria de más de un año no sirve para decidir una compra hoy.
ANTIGUEDAD_MAX_MESES = 12

# Productos que publica la planilla, en el orden de sus columnas de encabezado.
PRODUCTOS = {
    "letras de crédito": "letras_credito",
    "mutuo hipotecario  endosable": "mutuo_endosable",
    "mutuo hipotecario endosable": "mutuo_endosable",
    "mutuos hipotecario endosable": "mutuo_endosable",
    "mutuo hipotecario no endosable": "mutuo_no_endosable",
    "mutuos hipotecario no endosable": "mutuo_no_endosable",
}

MESES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

TASA_MIN, TASA_MAX = Decimal("0.005"), Decimal("0.30")


class ErrorDeFuente(RuntimeError):
    """La planilla no tiene la forma esperada. Nunca se traga en silencio (§11)."""


class PlanillaObsoleta(ErrorDeFuente):
    """La planilla es demasiado vieja para usarse. Se distingue de un error de forma."""


class TasaBanco(BaseModel):
    """Una tasa publicada por un banco para un producto y monto, con su procedencia."""

    fecha: date
    banco: str
    producto: str
    monto_credito_uf: Decimal
    plazo_anios: int
    ltv: Decimal
    tasa_anual: Decimal
    con_subsidio: bool = False
    evidence_level: str = "V"

    source_id: str
    source_url: str
    fetched_at: datetime
    parser_version: str
    raw_blob_path: str
    robots_snapshot_sha: str


# --------------------------------------------------------------------------- utilidades


def parsear_fecha_consulta(texto: str) -> date:
    """'Fecha de la consulta: 22 al 26 de mayo de 2006' -> date(2006, 5, 26).

    Se toma el ÚLTIMO día del rango: es la fecha hasta la cual el dato es válido.
    """
    t = texto.lower()
    m = re.search(r"(\d{1,2})\s*(?:al\s*(\d{1,2}))?\s*de\s*([a-záé]+)\s*de\s*(\d{4})", t)
    if not m:
        raise ErrorDeFuente(f"no se pudo leer la fecha de consulta en {texto!r}")
    dia = int(m.group(2) or m.group(1))
    mes = MESES.get(m.group(3))
    if mes is None:
        raise ErrorDeFuente(f"mes desconocido en {texto!r}")
    return date(int(m.group(4)), mes, dia)


def antiguedad_meses(fecha_dato: date, ahora: date) -> int:
    return (ahora.year - fecha_dato.year) * 12 + (ahora.month - fecha_dato.month)


def _uf_de(texto: str) -> Decimal:
    """'1.000 UF' -> 1000. Punto de miles, igual que el resto de las fuentes chilenas."""
    m = re.search(r"([\d.]+)", texto.replace(" ", ""))
    if not m:
        raise ErrorDeFuente(f"no se pudo leer un monto en UF desde {texto!r}")
    return Decimal(m.group(1).replace(".", ""))


def _entero_de(texto: str) -> int:
    m = re.search(r"(\d+)", texto)
    if not m:
        raise ErrorDeFuente(f"no se pudo leer un entero desde {texto!r}")
    return int(m.group(1))


# --------------------------------------------------------------------------- colector


class CmfTasasHipotecarias:
    """Cumple el protocolo `Source` del §7.1."""

    id = "cmf_tasas_hipotecarias"
    legal_tier: LegalTier = "json_publico"
    parser_version = PARSER_VERSION

    def __init__(
        self,
        user_agent: str,
        cliente: httpx.Client | None = None,
        raiz_cruda: Path | None = None,
        antiguedad_max_meses: int = ANTIGUEDAD_MAX_MESES,
    ) -> None:
        self.user_agent = user_agent
        self._cliente = cliente
        self.raiz_cruda = raiz_cruda
        self.antiguedad_max_meses = antiguedad_max_meses

    def robots_ok(self) -> RobotsVerdict:
        from flujocero.sources import robots_check

        return robots_check.verificar(
            URL,
            self.user_agent,
            source_id=self.id,
            cliente=self._cliente,
            raiz_cruda=self.raiz_cruda,
        )

    def collect(self, scope: Scope) -> Iterator[RawDoc]:
        veredicto = self.robots_ok()
        if not veredicto.allowed or not veredicto.snapshot_sha:
            raise ErrorDeFuente(f"no se recolecta: robots.txt no superado — {veredicto.motivo}")
        cliente = self._cliente or httpx.Client(timeout=TIMEOUT, follow_redirects=True)
        propio = self._cliente is None
        try:
            try:
                resp = cliente.get(URL, headers={"User-Agent": self.user_agent})
            except httpx.HTTPError as exc:
                raise ErrorDeFuente(f"no se pudo alcanzar {URL}: {exc}") from exc
            if resp.status_code != 200:
                raise ErrorDeFuente(f"{URL} respondió {resp.status_code}")
            yield escribir_crudo(
                self.id,
                URL,
                resp.content,
                scope.ahora,
                veredicto.snapshot_sha,
                "tasas_hipotecarias.xls",
                self.raiz_cruda,
            )
        finally:
            if propio:
                cliente.close()

    # ------------------------------------------------------------------ parseo

    def parse(self, doc: RawDoc, ahora: date | None = None) -> list[TasaBanco]:
        import xlrd

        libro = xlrd.open_workbook(file_contents=doc.contenido)
        proc = Procedencia(
            source_id=self.id,
            source_url=doc.url,
            fetched_at=doc.fetched_at,
            parser_version=self.parser_version,
            raw_blob_path=str(doc.ruta),
            robots_snapshot_sha=doc.robots_snapshot_sha,
        )
        filas: list[TasaBanco] = []
        hojas = [n for n in libro.sheet_names() if n.lower().startswith("tasa")]
        if not hojas:
            raise ErrorDeFuente(
                f"ninguna hoja de tasas en {doc.ruta}; encontradas: {libro.sheet_names()}"
            )
        for nombre in hojas:
            filas.extend(self._parsear_hoja(libro.sheet_by_name(nombre), proc))

        fechas = {f.fecha for f in filas}
        if len(fechas) != 1:
            raise ErrorDeFuente(f"las hojas no coinciden en la fecha de consulta: {fechas}")
        fecha = fechas.pop()
        edad = antiguedad_meses(fecha, ahora or datetime.now(UTC).date())
        if edad > self.antiguedad_max_meses:
            raise PlanillaObsoleta(
                f"la planilla es de {fecha:%Y-%m-%d}, {edad} meses de antigüedad "
                f"(máximo {self.antiguedad_max_meses}). Una tasa vieja usada para decidir "
                "hoy es peor que no tener el dato."
            )
        return filas

    def _parsear_hoja(self, hoja: Any, proc: Procedencia) -> list[TasaBanco]:
        """Localiza cada bloque por su etiqueta. Nunca por número de fila: entre hojas
        de este mismo archivo los índices se corren."""
        texto: dict[tuple[int, int], str] = {}
        for r in range(hoja.nrows):
            for c in range(hoja.ncols):
                v = hoja.cell_value(r, c)
                if isinstance(v, str) and v.strip():
                    texto[(r, c)] = v.strip()

        def buscar(fragmento: str) -> tuple[int, int, str]:
            for (r, c), v in texto.items():
                if fragmento.lower() in v.lower():
                    return r, c, v
            raise ErrorDeFuente(f"no se encontró '{fragmento}' en la hoja {hoja.name!r}")

        _, _, txt_fecha = buscar("Fecha de la consulta")
        fecha = parsear_fecha_consulta(txt_fecha)

        def valor_a_la_derecha(fragmento: str) -> str:
            r, c, _ = buscar(fragmento)
            for cc in range(c + 1, hoja.ncols):
                v = hoja.cell_value(r, cc)
                if str(v).strip():
                    return str(v)
            raise ErrorDeFuente(f"'{fragmento}' sin valor a la derecha en {hoja.name!r}")

        monto = _uf_de(valor_a_la_derecha("MONTO DEL CRÉDITO"))
        propiedad = _uf_de(valor_a_la_derecha("VALOR DE LA PROPIEDAD"))
        plazo = _entero_de(valor_a_la_derecha("PLAZO DEL CRÉDITO"))
        ltv = monto / propiedad

        fila_enc, col_banco, _ = buscar("Nombre de la institución")
        columnas: dict[int, str] = {}
        for c in range(hoja.ncols):
            etiqueta = str(hoja.cell_value(fila_enc, c)).strip().lower()
            etiqueta = re.sub(r"\s*\(\d\)\s*", "", etiqueta)
            etiqueta = re.sub(r"\s+", " ", etiqueta)
            if etiqueta in PRODUCTOS:
                columnas[c] = PRODUCTOS[etiqueta]
        if not columnas:
            raise ErrorDeFuente(
                f"ninguna columna de producto reconocida en {hoja.name!r}; "
                f"encabezados: {[hoja.cell_value(fila_enc, c) for c in range(hoja.ncols)]}"
            )

        filas: list[TasaBanco] = []
        for r in range(fila_enc + 1, hoja.nrows):
            banco = str(hoja.cell_value(r, col_banco)).strip()
            # Las notas al pie empiezan con '(1)', 'Notas:', 'n/o:', 'Fuente:', '*'
            if not banco or re.match(r"^[(*]|^(notas|n/o|fuente|actualizado)\b", banco.lower()):
                continue
            banco = re.sub(r"\s*\(\d\)\s*$", "", banco).strip()
            for c, producto in columnas.items():
                bruto = hoja.cell_value(r, c)
                if not isinstance(bruto, float):
                    continue  # 'n/o' = no ofrece el producto. Es ND, no cero (§3.2).
                tasa = Decimal(str(bruto))
                if not (TASA_MIN <= tasa <= TASA_MAX):
                    raise ErrorDeFuente(
                        f"tasa implausible en {hoja.name!r} fila {r}: {tasa} para {banco}"
                    )
                filas.append(
                    TasaBanco(
                        fecha=fecha,
                        banco=banco,
                        producto=producto,
                        monto_credito_uf=monto,
                        plazo_anios=plazo,
                        ltv=ltv,
                        tasa_anual=tasa,
                        con_subsidio=False,
                        **proc.as_dict(),
                    )
                )
        return filas

    # ------------------------------------------------------------------ selftest

    def selftest(
        self,
        fixture: RawDoc | None = None,
        muestra_viva: list[RawDoc] | None = None,
        ahora: date | None = None,
        n_filas_corrida_anterior: int | None = None,
    ) -> SelfTestReport:
        rep = SelfTestReport(source_id=self.id, ok=True)
        rep.n_filas_corrida_anterior = n_filas_corrida_anterior
        docs = ([fixture] if fixture else []) + (muestra_viva or [])
        if not docs:
            rep.fallar("hay_documentos", "sin fixture ni muestra viva")
            return rep

        filas: list[TasaBanco] = []
        for doc in docs[:5]:
            try:
                filas.extend(self.parse(doc, ahora=ahora))
            except PlanillaObsoleta as exc:
                rep.fallar("frescura", str(exc))
                return rep
            except ErrorDeFuente as exc:
                rep.fallar("parseo", f"{doc.ruta}: {exc}")
                return rep
        rep.pasar("parseo")
        rep.pasar("frescura")
        rep.n_filas = len(filas)

        requeridos = ("fecha", "banco", "producto", "tasa_anual", *Procedencia.__dataclass_fields__)
        completos = sum(
            1 for f in filas if all(getattr(f, c, None) not in (None, "") for c in requeridos)
        )
        if not filas or completos / len(filas) < 0.95:
            rep.fallar("campos_requeridos", "menos del 95% de las filas completas")
        else:
            rep.pasar("campos_requeridos")

        caida = rep.caida_pct
        if caida is not None and caida > 0.30:
            rep.fallar("conteo_estable", f"el conteo cayó {caida:.0%}")
        else:
            rep.pasar("conteo_estable")

        rep.checks["forma_verificada"] = fixture is not None or bool(muestra_viva)
        return rep


UPSERT = """
INSERT INTO dim_tasa_banco
  (fecha, banco, con_subsidio, tasa_anual, plazo_max_anios, ltv_max, evidence_level,
   source_id, source_url, fetched_at, parser_version, raw_blob_path, robots_snapshot_sha)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (fecha, banco, con_subsidio) DO UPDATE SET
  tasa_anual = excluded.tasa_anual, plazo_max_anios = excluded.plazo_max_anios,
  ltv_max = excluded.ltv_max, evidence_level = excluded.evidence_level,
  source_id = excluded.source_id, source_url = excluded.source_url,
  fetched_at = excluded.fetched_at, parser_version = excluded.parser_version,
  raw_blob_path = excluded.raw_blob_path, robots_snapshot_sha = excluded.robots_snapshot_sha
"""


def cargar_en_duckdb(conexion: Any, filas: list[TasaBanco]) -> int:
    """Carga la mejor tasa por (fecha, banco): la planilla trae varios productos y montos.

    Quedarse con la mínima es una decisión explícita, no un promedio silencioso: es la
    tasa que el banco efectivamente ofrece en su producto más barato.
    """
    mejor: dict[tuple[date, str], TasaBanco] = {}
    for f in filas:
        clave = (f.fecha, f.banco)
        if clave not in mejor or f.tasa_anual < mejor[clave].tasa_anual:
            mejor[clave] = f
    for f in mejor.values():
        conexion.execute(
            UPSERT,
            (
                f.fecha,
                f.banco,
                f.con_subsidio,
                float(f.tasa_anual),
                f.plazo_anios,
                float(f.ltv),
                f.evidence_level,
                f.source_id,
                f.source_url,
                f.fetched_at,
                f.parser_version,
                f.raw_blob_path,
                f.robots_snapshot_sha,
            ),
        )
    return len(mejor)
