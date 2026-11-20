"""Corrida completa de los 7 pasos sobre la BD sintetica: salidas, determinismo, sin PII y BD intacta."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.analisis.conftest import leer_json

BACKEND = Path(__file__).resolve().parents[2]
PASOS = ["a01_perfil_ventas", "a02_estacionalidad_anomalias", "a03_inferencia", "a04_descomposicion_caida",
         "a05_demanda", "a06_venta_cruzada", "a07_segmentacion"]
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
TELEFONO = re.compile(r"(?<!\d)(?:\+?57)?3\d{9}(?!\d)")


def _textos(carpeta):
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(carpeta.iterdir()) if p.suffix in (".json", ".txt")}


def test_cada_paso_genera_json_txt_y_graficas(corrida):
    carpeta = corrida["a"]
    for paso in PASOS:
        assert (carpeta / f"{paso}.json").stat().st_size > 2, paso
        assert (carpeta / f"{paso}.txt").stat().st_size > 50, paso
    for paso in ("a01_perfil_ventas", "a02_estacionalidad_anomalias", "a04_descomposicion_caida", "a05_demanda",
                 "a06_venta_cruzada", "a07_segmentacion"):
        for grafica in leer_json(carpeta, paso)["graficas"]:
            assert (carpeta / grafica).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_dos_corridas_dan_json_y_txt_identicos(corrida):
    a, b = _textos(corrida["a"]), _textos(corrida["b"])
    assert set(a) == set(b) and len(a) == 14
    for nombre in a:
        assert a[nombre] == b[nombre], f"{nombre} difiere entre corridas"


def test_las_salidas_no_contienen_pii(corrida):
    textos = _textos(corrida["a"])
    for nombre, texto in textos.items():
        assert "PII_" not in texto, f"{nombre} contiene una marca de PII"
        assert not EMAIL.search(texto), f"{nombre} contiene un correo"
        assert not TELEFONO.search(texto), f"{nombre} contiene un telefono"
        for marca in corrida["meta"]["marcas_pii"]:
            assert marca not in texto, f"{nombre} contiene {marca}"


def test_los_clientes_aparecen_solo_como_codigo_anonimo(corrida):
    top = leer_json(corrida["a"], "a07_segmentacion")["segmentos"]["top_clientes"]
    assert len(top) == 5
    for cliente in top:
        assert re.fullmatch(r"C\d{3}", cliente["codigo"])
        assert cliente["codigo"] in corrida["meta"]["codigos"]
    assert "C0" in (corrida["a"] / "a07_segmentacion.txt").read_text(encoding="utf-8")


def test_la_bd_no_se_modifica(corrida):
    # (tamano, mtime_ns, sha256) igual tras una y tras dos corridas
    assert corrida["despues_primera"] == corrida["antes"]
    assert corrida["despues"] == corrida["antes"]
    ruta = corrida["ruta"]
    assert sorted(p.name for p in ruta.parent.iterdir()) == [ruta.name]     # sin -journal / -wal / -shm


def test_conexion_de_solo_lectura_rechaza_escrituras(bd):
    import sqlite3

    from analisis import comun
    con = comun.conectar()
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            con.execute("DELETE FROM products")
    finally:
        con.close()


def test_la_corrida_no_escribio_en_las_salidas_reales(corrida):
    from analisis import comun
    assert comun.SALIDAS == Path(comun.__file__).resolve().parent / "salidas"      # se restauro tras la corrida
    assert corrida["a"] != comun.SALIDAS


def test_ruta_de_la_bd_sale_de_la_variable_ANALISIS_DB(tmp_path):
    ruta = tmp_path / "otra.db"
    env = {**os.environ, "ANALISIS_DB": str(ruta)}
    r = subprocess.run([sys.executable, "-c", "from analisis import comun; print(comun.DB_RUTA)"], cwd=BACKEND,
                       env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert Path(r.stdout.strip()) == ruta
    assert not ruta.exists()                    # solo se leyo la ruta: importar no crea ni escribe la BD
