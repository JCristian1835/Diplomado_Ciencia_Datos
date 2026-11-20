"""a04_descomposicion_caida: los tres componentes suman la caida total (y 100 %) con cada definicion de anomalia."""
from types import SimpleNamespace

import pandas as pd
import pytest

from analisis import a04_descomposicion_caida as a04
from analisis import comun
from tests.analisis.conftest import leer_json

COMPONENTES = ["domicilios", "dias_casi_sin_pedidos", "demanda_dias_normales"]


def _dias():
    """4 dias base (10 pedidos, 2 domicilios) y 4 dias de caida (8, 8, 2, 2 pedidos; 1, 1, 0, 0 domicilios)."""
    return pd.DataFrame({"periodo": ["base"] * 4 + ["caida"] * 4, "pedidos": [10, 10, 10, 10, 8, 8, 2, 2],
                         "domicilios": [2, 2, 2, 2, 1, 1, 0, 0]})


def test_descomposicion_a_mano():
    c = _dias()
    r = a04.descomponer(c, c["pedidos"] <= 5)
    # base: 10 pedidos/dia, 2 domicilios, otros = 8 en los 4 dias, sin dias anomalos.
    # caida: 5 pedidos/dia, 0,5 domicilios; otros = {7, 7, 2, 2}: normales 7, anomalos 2, perdida = 2/4 x (7 - 2) = 2,5.
    assert r["caida_total"] == pytest.approx(5.0)
    assert r["partes"]["domicilios"] == pytest.approx(1.5)                 # 2 - 0,5
    assert r["partes"]["dias_casi_sin_pedidos"] == pytest.approx(2.5)      # 2,5 - 0
    assert r["partes"]["demanda_dias_normales"] == pytest.approx(1.0)      # 8 - 7
    assert r["porcentajes"] == pytest.approx({"domicilios": 0.3, "dias_casi_sin_pedidos": 0.5,
                                              "demanda_dias_normales": 0.2})
    assert bool(r["cuadre"])
    assert (r["base"]["dias_anomalos"], r["caida"]["dias_anomalos"]) == (0, 2)


def test_sin_dias_anomalos_el_componente_de_dias_vacios_es_cero():
    c = _dias()
    r = a04.descomponer(c, pd.Series(False, index=c.index))
    assert r["partes"]["dias_casi_sin_pedidos"] == 0
    assert sum(r["partes"].values()) == pytest.approx(r["caida_total"])


def _definiciones(c):
    _, _, _, valla_global = comun.valla_tukey(c["pedidos"])
    _, _, _, valla_base = comun.valla_tukey(c[c["periodo"] == "base"]["pedidos"])
    return {"<= 5 pedidos": c["pedidos"] <= comun.UMBRAL_CASI_SIN_PEDIDOS, "Tukey global": c["pedidos"] <= valla_global,
            "Tukey solo base": c["pedidos"] <= valla_base}


def test_los_tres_componentes_suman_el_total_con_las_tres_definiciones(datos):
    c = comun.dias_comparables(datos.diario)
    for nombre, mascara in _definiciones(c).items():
        r = a04.descomponer(c, mascara)
        assert sum(r["partes"].values()) == pytest.approx(r["caida_total"], abs=1e-9), nombre
        assert sum(r["porcentajes"].values()) == pytest.approx(1.0, abs=1e-9), nombre
        assert bool(r["cuadre"]), nombre
        assert r["caida_total"] == pytest.approx(
            c[c["periodo"] == "base"]["pedidos"].mean() - c[c["periodo"] == "caida"]["pedidos"].mean())


def test_la_sensibilidad_guarda_las_tres_definiciones_y_cada_una_suma_100(datos):
    c = comun.dias_comparables(datos.diario)
    rep = SimpleNamespace(datos={})
    a04.sensibilidad(c, rep)
    sensibilidad = rep.datos["sensibilidad"]
    assert len(sensibilidad) == 3
    for nombre, s in sensibilidad.items():
        assert sum(s[k] for k in COMPONENTES) == pytest.approx(1.0, abs=1e-9), nombre
    # La BD sintetica tiene 3 dias de caida con 1 a 3 pedidos: la definicion principal los marca (5 o menos)
    assert next(iter(sensibilidad.values()))["dias_anomalos"] == int((c["pedidos"] <= 5).sum()) >= 3


def test_json_de_la_corrida_cuadra(corrida):
    j = leer_json(corrida["a"], "a04_descomposicion_caida")
    d = j["descomposicion"]
    assert d["cuadre"] is True
    assert sum(d["partes"].values()) == pytest.approx(d["caida_total"], abs=1e-5)
    assert sum(d["porcentajes"].values()) == pytest.approx(1.0, abs=1e-5)
    for s in j["sensibilidad"].values():
        assert sum(s[k] for k in COMPONENTES) == pytest.approx(1.0, abs=1e-5)
