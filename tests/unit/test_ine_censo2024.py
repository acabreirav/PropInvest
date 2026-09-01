"""T-014 · promocion de los archivos del Censo a la zona cruda: verbatim, con meta, sin pisar."""

import json
from datetime import UTC, datetime

from flujocero.sources import ine_censo2024 as censo


def _armar(tmp_path):
    origen = tmp_path / "incoming"
    origen.mkdir()
    (origen / "Base_manzana_entidad_CPV24.csv").write_bytes(b"ID_MANZENT;P01\n123;4\n")
    (origen / "shp-apc2023-r13.zip").write_bytes(b"PK\x03\x04zipfalso")
    return origen, tmp_path / "raw"


def test_copia_verbatim_con_meta_y_fecha_de_descarga(tmp_path):
    origen, raiz = _armar(tmp_path)
    momento = datetime(2026, 8, 31, 22, 30, tzinfo=UTC)
    res = censo.promover(origen, raiz, ahora=momento)
    assert [r.accion for r in res] == ["copiado", "copiado"]

    destino = raiz / "ine_censo2024" / "2026" / "08" / "31" / "Base_manzana_entidad_CPV24.csv"
    assert destino.read_bytes() == b"ID_MANZENT;P01\n123;4\n", "verbatim, sin gzip encima"
    meta = json.loads((destino.parent / "Base_manzana_entidad_CPV24.meta.json").read_text())
    # Las columnas del §3.1 que un blob puede portar, mas el sha para la idempotencia.
    assert meta["source_id"] == "ine_censo2024"
    assert meta["source_url"] == censo.URL_RESULTADOS
    assert meta["fetched_at"].startswith("2026-08-31")
    assert meta["robots_snapshot_sha"] == censo.ROBOTS_SHA_MANUAL
    assert meta["sha_contenido"] == res[0].sha

    # La cartografia apunta a SU pagina, no a la de resultados.
    meta2 = json.loads((destino.parent / "shp-apc2023-r13.meta.json").read_text())
    assert meta2["source_url"] == censo.URL_GEODATOS


def test_es_idempotente_y_no_pisa_un_contenido_distinto(tmp_path):
    origen, raiz = _armar(tmp_path)
    momento = datetime(2026, 8, 31, tzinfo=UTC)
    censo.promover(origen, raiz, ahora=momento)
    res2 = censo.promover(origen, raiz, ahora=momento)
    assert [r.accion for r in res2] == ["ya_estaba", "ya_estaba"]

    # El usuario re-descarga un CSV distinto con el mismo nombre: la zona cruda es
    # inmutable, se reporta conflicto y no se toca el blob existente.
    (origen / "Base_manzana_entidad_CPV24.csv").write_bytes(b"OTRA_COSA\n")
    res3 = censo.promover(origen, raiz, ahora=momento)
    assert res3[0].accion == "conflicto"
    destino = raiz / "ine_censo2024" / "2026" / "08" / "31" / "Base_manzana_entidad_CPV24.csv"
    assert destino.read_bytes() == b"ID_MANZENT;P01\n123;4\n"


def test_sin_carpeta_no_hay_drama(tmp_path):
    assert censo.promover(tmp_path / "no-existe", tmp_path / "raw") == []


# ------------------------------------------------------------------- carga a DuckDB


CABECERA = (
    "CONTENEDOR_COMUNAL;COD_REGION;REGION;PROVINCIA;CUT;COMUNA;AREA_C;MANZENT;TIPO_MZ;"
    "n_per;n_hog;prom_per_hog;prom_edad;prom_escolaridad18;n_vp;n_vp_ocupada;"
    "n_vp_desocupada;n_tipo_viv_depto;n_tipo_viv_casa;n_tenencia_arrendada_contrato;"
    "n_tenencia_arrendada_sin_contrato;n_tenencia_propia_pagada;"
    "n_tenencia_propia_pagandose;n_hog_unipersonales"
)


def _csv_como_el_del_ine(tmp_path):
    """Con las DOS trampas verificadas en el archivo real: '*' enmascarado y coma decimal."""
    origen = tmp_path / "incoming"
    origen.mkdir(exist_ok=True)
    filas = [
        CABECERA,
        "0;13;METROPOLITANA;SANTIAGO;13119;SANTIAGO;1;13119011001001;URBANO;"
        "120;40;2,9;38,5;12,4;55;50;5;48;2;20;4;10;8;12",
        # n_per enmascarado con '*': la manzana es chica y el INE protege privacidad.
        "0;13;METROPOLITANA;SANTIAGO;13119;SANTIAGO;1;13119011001002;URBANO;"
        "*;*;*;41,0;11,1;8;7;1;0;8;2;1;3;1;2",
    ]
    (origen / "Base_manzana_entidad_CPV24.csv").write_text("\n".join(filas), encoding="utf-8")
    return origen


def test_carga_el_csv_con_asterisco_como_null_y_coma_decimal(tmp_path):
    import duckdb

    from flujocero import db

    origen = _csv_como_el_del_ine(tmp_path)
    censo.promover(origen, tmp_path / "raw")

    con = duckdb.connect()
    db.aplicar_esquema(con)
    n = censo.cargar_csv(con, tmp_path / "raw")
    assert n == 2

    normal = con.execute(
        "SELECT n_personas, prom_edad, n_viv_desocupadas, comuna FROM dim_manzana "
        "WHERE manzent = '13119011001001'"
    ).fetchone()
    assert normal == (120, 38.5, 5, "SANTIAGO"), "coma decimal parseada, conteos enteros"

    velada = con.execute(
        "SELECT n_personas, n_hogares, prom_edad FROM dim_manzana WHERE manzent = '13119011001002'"
    ).fetchone()
    assert velada[0] is None and velada[1] is None, (
        "'*' es un valor ENMASCARADO por privacidad: NULL, jamas 0 (§3.2)"
    )
    assert velada[2] == 41.0

    seis = con.execute(
        "SELECT source_id, source_url, fetched_at, parser_version, raw_blob_path, "
        "robots_snapshot_sha FROM dim_manzana LIMIT 1"
    ).fetchone()
    assert all(seis), "las seis columnas del §3.1 pobladas en cada fila"


def test_carga_geometria_desde_el_zip_regional(tmp_path):
    import zipfile

    import duckdb
    import geopandas as gpd
    from shapely.geometry import Polygon

    from flujocero import db

    origen = _csv_como_el_del_ine(tmp_path)

    # Un shapefile real en miniatura, con la estructura del ZIP del INE.
    gdf = gpd.GeoDataFrame(
        {"MANZENT": [13119011001001], "geometry": [Polygon([(0, 0), (0, 1), (1, 1)])]},
        crs="EPSG:3857",
    )
    carpeta_shp = tmp_path / "SHP_APC2023_R13"
    carpeta_shp.mkdir()
    gdf.to_file(carpeta_shp / "Manzana_Urbana.shp")
    with zipfile.ZipFile(origen / "shp-apc2023-r13.zip", "w") as zf:
        for f in carpeta_shp.iterdir():
            zf.write(f, f"SHP_APC2023_R13/{f.name}")

    censo.promover(origen, tmp_path / "raw")
    con = duckdb.connect()
    db.aplicar_esquema(con)
    censo.cargar_csv(con, tmp_path / "raw")
    resultados = censo.cargar_geometria(con, tmp_path / "raw")
    assert resultados == {"shp-apc2023-r13.zip": "1 poligonos · 1 calzan con el censo"}

    lat, lon, wkb = con.execute(
        "SELECT lat, lon, geom_wkb FROM dim_manzana WHERE manzent = '13119011001001'"
    ).fetchone()
    assert wkb is not None and lat is not None
    assert abs(lat) < 1 and abs(lon) < 1, "reproyectado de EPSG:3857 a 4326"
    # La manzana sin poligono queda con NULL, no con un centroide inventado.
    assert (
        con.execute("SELECT geom_wkb FROM dim_manzana WHERE manzent = '13119011001002'").fetchone()[
            0
        ]
        is None
    )


def test_llave_numerica_del_dbf_no_rompe_el_cruce(tmp_path):
    """El DBF entrega la llave como float: str() directo da '13119011001001.0' y calza CERO.

    Paso EXACTO en la maquina real: 109.543 poligonos leidos, 2.853 calzaron (1%). Este
    test fija la normalizacion float -> Int64 -> texto, y que el diagnostico de cruce roto
    aparezca cuando calza menos de la mitad.
    """
    import zipfile

    import duckdb
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import Polygon

    from flujocero import db

    origen = _csv_como_el_del_ine(tmp_path)
    gdf = gpd.GeoDataFrame(
        {
            "MANZENT": np.array([13119011001001.0, 99999999999999.0]),  # float, como el DBF
            "geometry": [
                Polygon([(0, 0), (0, 1), (1, 1)]),
                Polygon([(2, 2), (2, 3), (3, 3)]),
            ],
        },
        crs="EPSG:4326",
    )
    carpeta = tmp_path / "SHP_APC2023_R13"
    carpeta.mkdir()
    gdf.to_file(carpeta / "Manzana_Urbana.shp")
    with zipfile.ZipFile(origen / "shp-apc2023-r13.zip", "w") as zf:
        for f in carpeta.iterdir():
            zf.write(f, f"SHP_APC2023_R13/{f.name}")

    censo.promover(origen, tmp_path / "raw")
    con = duckdb.connect()
    db.aplicar_esquema(con)
    censo.cargar_csv(con, tmp_path / "raw")
    res = censo.cargar_geometria(con, tmp_path / "raw")["shp-apc2023-r13.zip"]
    assert res.startswith("2 poligonos · 1 calzan"), res

    assert (
        con.execute(
            "SELECT geom_wkb IS NOT NULL FROM dim_manzana WHERE manzent = '13119011001001'"
        ).fetchone()[0]
        is True
    ), "la llave float normalizada calza"
