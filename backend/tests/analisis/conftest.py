"""Fixtures del paquete analisis/: BD sintetica, y la corrida completa de los 7 pasos (una vez por sesion).

Nunca se toca backend/data/*.db ni backend/analisis/salidas/: la ruta de la BD y la de salidas se redirigen
a carpetas temporales (comun.DB_RUTA y comun.SALIDAS).
"""
import hashlib
import json

import pytest

from analisis import comun
from tests.analisis.bd_sintetica import construir_bd


def huella(ruta):
    """(tamano, mtime_ns, sha256) de un archivo."""
    est = ruta.stat()
    return est.st_size, est.st_mtime_ns, hashlib.sha256(ruta.read_bytes()).hexdigest()


@pytest.fixture(scope="session")
def bd_sintetica(tmp_path_factory):
    ruta = tmp_path_factory.mktemp("analisis_bd") / "sintetica.db"
    meta = construir_bd(ruta)
    return ruta, meta


@pytest.fixture
def bd(bd_sintetica, monkeypatch):
    """Apunta el analisis a la BD sintetica (ANALISIS_DB se resuelve en comun.DB_RUTA al importar)."""
    ruta, meta = bd_sintetica
    monkeypatch.setattr(comun, "DB_RUTA", ruta)
    return ruta, meta


@pytest.fixture
def datos(bd):
    return comun.cargar()


def _correr_todo(ruta, salidas):
    from analisis import correr_todo
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(comun, "DB_RUTA", ruta)
        mp.setattr(comun, "SALIDAS", salidas)
        correr_todo.main()
    finally:
        mp.undo()


@pytest.fixture(scope="session")
def corrida(bd_sintetica, tmp_path_factory):
    """Ejecuta correr_todo dos veces sobre la BD sintetica (salidas en carpetas temporales distintas)."""
    ruta, meta = bd_sintetica
    antes = huella(ruta)
    a, b = tmp_path_factory.mktemp("salidas_a"), tmp_path_factory.mktemp("salidas_b")
    _correr_todo(ruta, a)
    despues_primera = huella(ruta)
    _correr_todo(ruta, b)
    return {"a": a, "b": b, "antes": antes, "despues_primera": despues_primera, "despues": huella(ruta),
            "meta": meta, "ruta": ruta}


def leer_json(carpeta, nombre):
    return json.loads((carpeta / f"{nombre}.json").read_text(encoding="utf-8"))
