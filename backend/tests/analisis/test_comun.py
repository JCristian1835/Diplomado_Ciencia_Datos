"""analisis/comun.py: definiciones de dia abierto y periodos, precio real, costos, formato es-CO y salidas."""
import json
import sqlite3

import numpy as np
import pandas as pd
import pytest

from analisis import comun


# ---------------------------------------------------------------- periodos
def test_constantes_de_los_periodos():
    assert (comun.INICIO_BASE, comun.FIN_BASE) == (pd.Timestamp("2026-05-01"), pd.Timestamp("2026-08-31"))
    assert (comun.INICIO_CAIDA, comun.FIN_CAIDA) == (pd.Timestamp("2026-09-01"), pd.Timestamp("2026-11-12"))
    assert comun.SEMILLA == 42 and comun.UMBRAL_CASI_SIN_PEDIDOS == 5


@pytest.mark.parametrize("fecha,esperado", [
    ("2026-03-23", "arranque"), ("2026-04-30", "arranque"),
    ("2026-05-01", "base"), ("2026-08-31", "base"),
    ("2026-09-01", "caida"), ("2026-11-12", "caida"),
    ("2026-11-13", "incompleto"), ("2026-11-14", "incompleto"),
])
def test_periodo_en_los_bordes(fecha, esperado):
    assert comun._periodo(pd.Series([pd.Timestamp(fecha)])).tolist() == [esperado]


def test_dias_comparables_excluyen_martes_13_nov_y_arranque(datos):
    c = comun.dias_comparables(datos.diario)
    assert (c["fecha"].dt.day_of_week != 1).all()                       # sin martes
    assert pd.Timestamp("2026-11-13") not in set(c["fecha"])            # ultimo dia incompleto
    assert c["fecha"].min() == pd.Timestamp("2026-05-01") and c["fecha"].max() == pd.Timestamp("2026-11-12")
    assert set(c["periodo"]) == {"base", "caida"}                       # sin arranque (mar-abr) ni incompleto
    # A mano: 1-may a 31-ago son 123 dias con 17 martes (5-may ... 25-ago) = 106;
    # 1-sep a 12-nov son 73 dias con 11 martes (1-sep ... 10-nov) = 62.
    assert c.groupby("periodo").size().to_dict() == {"base": 106, "caida": 62}


def test_martes_con_ventas_no_cuentan_como_dia_abierto(datos):
    martes = datos.ventas[datos.ventas["dia_semana"] == 1]
    assert len(martes) > 0 and not martes["abierto"].any()
    assert datos.ventas.loc[datos.ventas["dia_semana"] != 1, "abierto"].all()
    c = comun.dias_comparables(datos.diario)
    assert not set(martes["fecha"]) & set(c["fecha"])
    assert not datos.diario[datos.diario["fecha"].dt.day_of_week == 1]["abierto"].any()


def test_pedidos_por_dia_abierto_es_pedidos_pagados_sobre_dias_abiertos(datos):
    c = comun.dias_comparables(datos.diario)
    v = datos.ventas[datos.ventas["abierto"]]
    for periodo, dias in (("base", 106), ("caida", 62)):
        pagados = (v["periodo"] == periodo).sum()
        assert c[c["periodo"] == periodo]["pedidos"].mean() == pytest.approx(pagados / dias)


def test_el_13_nov_queda_como_incompleto_y_los_cancelados_no_cuentan(bd_sintetica, datos):
    assert (datos.ventas.loc[datos.ventas["fecha"] == "2026-11-13", "periodo"] == "incompleto").all()
    assert (datos.ventas["status"] == "COMPLETED").all()
    con = sqlite3.connect(bd_sintetica[0])
    try:
        cancelados, total = con.execute("SELECT SUM(status != 'COMPLETED'), COUNT(*) FROM sales").fetchone()
    finally:
        con.close()
    assert datos.cancelados == cancelados > 0
    assert len(datos.ventas) == total - cancelados
    assert set(datos.items["sale_id"]) <= set(datos.ventas["id"])      # lineas de pedidos cancelados fuera


def test_dia_abierto_es_el_mismo_en_ventas_y_en_dim_fecha(datos):
    por_fecha = datos.ventas.groupby("fecha")["abierto"].first()
    diario = datos.diario.set_index("fecha")["abierto"]
    assert (por_fecha == diario.reindex(por_fecha.index)).all()


# ---------------------------------------------------------------- precio real y costos
def test_precio_real_es_la_mediana_de_lo_cobrado_en_pedidos_pagados(datos):
    p = datos.productos.set_index("name")
    assert p.loc["Prod_Mediana", "precio_real"] == 9000        # mediana de {8000, 9000, 20000}; el cancelado (1.000.000) no cuenta
    assert p.loc["Pizza", "precio_real"] == 30000              # lista 20000, cobrado 30000
    assert p.loc["Prod_Cerca", "precio_real"] == 11000
    assert p.loc["Hamburguesa", "precio_real"] == 15000


def test_precio_real_sin_ventas_usa_el_precio_de_lista(datos):
    p = datos.productos.set_index("name")
    assert p.loc["Prod_SinVentas", "precio_real"] == 7000
    assert not datos.items["product_id"].eq(9).any()


def test_costos_de_la_bd_sintetica_siguen_la_regla_nueva(datos):
    p = datos.productos.set_index("name")
    # razones reales: platos 0,4 ; bebidas {0,375 ; 0,4} -> 0,3875 ; global = mediana de {0,375 ; 0,4 x 6} = 0,4
    assert p.loc["Jugo", "costo"] == pytest.approx(5000 * 0.3875) and p.loc["Jugo", "costo_estimado"]
    assert p.loc["Postre", "costo"] == pytest.approx(5000 * 0.4)      # costo 6000 >= precio 5000: estimado con la global
    assert bool(p.loc["Postre", "costo_estimado"])
    assert p.loc["Hamburguesa", "costo"] == 6000 and not p.loc["Hamburguesa", "costo_estimado"]


def test_estimar_costos_a_mano():
    prods = pd.DataFrame({"category": ["a", "a", "a", "b", "c"], "unit_price": [100.0, 200.0, 100.0, 100.0, 50.0],
                          "unit_cost": [40.0, 100.0, 100.0, 0.0, 80.0]})
    r = comun.estimar_costos(prods)
    # a: razones {0,4 ; 0,5} -> 0,45 ; el costo 100 de precio 100 (>=) no cuenta ; global = 0,45
    assert r["costo"].tolist() == pytest.approx([40.0, 100.0, 45.0, 45.0, 22.5])
    assert r["costo_estimado"].tolist() == [False, False, True, True, True]
    assert r["razon_costo"].tolist() == pytest.approx([0.4, 0.5, 0.45, 0.45, 0.45])
    assert "costo" not in prods.columns                                # no modifica la entrada


# ---------------------------------------------------------------- Tukey
def test_valla_tukey_a_mano():
    q1, q3, iqr, valla = comun.valla_tukey(pd.Series(range(1, 10)))
    assert (q1, q3, iqr, valla) == (3, 7, 4, -3)                       # 3 - 1,5 x 4


# ---------------------------------------------------------------- formato es-CO
@pytest.mark.parametrize("valor,dec,esperado", [
    (1234567.891, 2, "1.234.567,89"), (1000, 0, "1.000"), (0, 0, "0"), (999, 0, "999"),
    (-1234.5, 1, "-1.234,5"), (0.5, 3, "0,500"), (12.0, 2, "12,00"),
])
def test_n_formato_es_co(valor, dec, esperado):
    assert comun.n(valor, dec) == esperado


def test_n_sin_dato():
    assert comun.n(None) == "-" and comun.n(float("nan")) == "-"


def test_pesos_pct_y_valor_p():
    assert comun.pesos(1500) == "$ 1.500"
    assert comun.pesos(1234.5, 1) == "$ 1.234,5"
    assert comun.pct(0.256) == "25,6 %"
    assert comun.pct(0.25, 0) == "25 %"
    assert comun.fmt_p(0.00001) == "< 0,0001" and comun.fmt_p(0.03456) == "0,0346"
    assert comun.texto_p(0.00001) == "p < 0,0001" and comun.texto_p(0.5) == "p = 0,5000"
    assert comun.fecha_corta("2026-11-05") == "05-11-2026"


# ---------------------------------------------------------------- salidas
def test_reporte_escribe_txt_y_json_y_limpia_tipos(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(comun, "SALIDAS", tmp_path / "salidas")
    with comun.Reporte("prueba") as rep:
        print("hola consola")
        rep.datos["x"] = {"a": np.int64(3), "b": float("nan"), "c": np.float64(1.23456789),
                          "d": pd.Timestamp("2026-11-05"), "e": np.bool_(True), "f": (1, 2), "g": float("inf")}
    assert "hola consola" in capsys.readouterr().out                    # sigue saliendo por consola
    assert (tmp_path / "salidas" / "prueba.txt").read_text(encoding="utf-8").strip() == "hola consola"
    datos = json.loads((tmp_path / "salidas" / "prueba.json").read_text(encoding="utf-8"))
    assert datos["x"] == {"a": 3, "b": None, "c": 1.234568, "d": "2026-11-05", "e": True, "f": [1, 2], "g": None}
    assert datos["graficas"] == []


def test_reporte_no_escribe_si_el_paso_falla(tmp_path, monkeypatch):
    monkeypatch.setattr(comun, "SALIDAS", tmp_path / "salidas")
    with pytest.raises(RuntimeError):
        with comun.Reporte("falla"):
            raise RuntimeError("boom")
    assert not (tmp_path / "salidas" / "falla.json").exists()
