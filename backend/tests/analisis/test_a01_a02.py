"""a01_perfil_ventas y a02_estacionalidad_anomalias sobre la BD sintetica: conteos de dias abiertos y reglas de anomalia."""
import pandas as pd
import pytest

from analisis import comun
from tests.analisis.conftest import leer_json


def test_a01_resumen_coincide_con_los_datos(corrida, datos):
    s = leer_json(corrida["a"], "a01_perfil_ventas")["resumen"]
    v = datos.ventas
    assert s["pedidos_pagados"] == len(v) and s["pedidos_no_pagados"] == datos.cancelados
    assert s["ingresos"] == pytest.approx(v["total_amount"].sum())
    assert s["pedidos_13_nov_excluidos"] == (v["fecha"] == "2026-11-13").sum() > 0
    assert s["pedidos_en_martes"] == (v["dia_semana"] == 1).sum() > 0
    assert s["dias_abiertos_comparables"] == 168
    assert (s["primer_dia"], s["ultimo_dia"]) == ("2026-03-23", "2026-11-13")


def test_a01_dias_abiertos_por_mes_a_mano(corrida, datos):
    meses = {m["mes"]: m for m in leer_json(corrida["a"], "a01_perfil_ventas")["por_mes"]}
    # dias del mes menos martes: mayo 31 - 4 ; jun 30 - 5 ; jul 31 - 4 ; ago 31 - 4 ; sep 30 - 5 ; oct 31 - 4 ; nov 1 al 12 menos 2
    esperado = {"mayo": 27, "junio": 25, "julio": 27, "agosto": 27, "septiembre": 25, "octubre": 27, "noviembre": 10}
    assert {k: meses[k]["dias_abiertos"] for k in esperado} == esperado
    assert sum(esperado[k] for k in ("mayo", "junio", "julio", "agosto")) == 106
    assert [meses[k]["periodo"] for k in ("marzo", "mayo", "septiembre")] == ["Arranque", "Base", "Caída"]
    v = datos.ventas[datos.ventas["periodo"] != "incompleto"]                        # sin el 13-nov
    assert meses["noviembre"]["pedidos"] == (v["fecha"].dt.month == 11).sum()
    for numero, nombre in comun.MESES.items():
        if nombre in meses:
            g = v[v["fecha"].dt.month == numero]
            assert meses[nombre]["pedidos"] == len(g)
            # solo los pedidos de dias abiertos (los martes con ventas no cuentan en el cociente)
            assert meses[nombre]["pedidos_por_dia_abierto"] == pytest.approx(
                g["abierto"].sum() / meses[nombre]["dias_abiertos"])


def test_a01_descriptivos_por_periodo(corrida, datos):
    c = comun.dias_comparables(datos.diario)
    d = leer_json(corrida["a"], "a01_perfil_ventas")["descriptivos_pedidos_por_dia_abierto"]
    for periodo, dias in (("base", 106), ("caida", 62)):
        serie = c[c["periodo"] == periodo]["pedidos"]
        assert d[periodo]["dias"] == dias
        assert d[periodo]["media"] == pytest.approx(serie.mean(), abs=1e-5)
        assert d[periodo]["desviacion"] == pytest.approx(serie.std(ddof=1), abs=1e-5)
    assert d["caida"]["minimo"] <= 3 < d["base"]["minimo"]                            # los dias casi vacios son de la caida


def test_a02_valla_de_tukey_y_dias_casi_sin_pedidos(corrida, datos):
    c = comun.dias_comparables(datos.diario)
    j = leer_json(corrida["a"], "a02_estacionalidad_anomalias")
    q1, q3, iqr, valla = comun.valla_tukey(c["pedidos"])
    t = j["tukey"]
    assert (t["q1"], t["q3"]) == (pytest.approx(q1), pytest.approx(q3))
    assert t["valla_inferior"] == pytest.approx(q1 - 1.5 * (q3 - q1))
    assert t["dias_anomalos"] == [f.strftime("%Y-%m-%d") for f in c[c["pedidos"] <= valla]["fecha"]]
    bajos = j["casi_sin_pedidos"]
    assert bajos["umbral"] == 5 and bajos["dias"] == (c["pedidos"] <= 5).sum() >= 3
    assert all(d["pedidos"] <= 5 and d["dia"] != "martes" for d in bajos["detalle"])
    assert {d["fecha"] for d in bajos["detalle"]} >= {"2026-09-14", "2026-10-05", "2026-10-19"}   # los 3 lunes sembrados
    assert bajos["minimo_periodo_base"] == c[c["periodo"] == "base"]["pedidos"].min()


def test_a02_efecto_dia_de_la_semana_no_incluye_martes(corrida):
    dias = leer_json(corrida["a"], "a02_estacionalidad_anomalias")["efecto_dia_semana"]["dias"]
    assert [d["dia"] for d in dias] == ["lunes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    assert sum(d["dias"] for d in dias) == 168


def test_a02_domicilios_reporta_la_interrupcion_mas_larga(corrida, datos):
    j = leer_json(corrida["a"], "a02_estacionalidad_anomalias")["domicilios"]
    fechas = pd.Series(sorted(datos.ventas.loc[datos.ventas["canal"] == "domicilio", "fecha"].unique()))
    saltos = fechas.diff().dt.days
    assert j["interrupcion_mas_larga"]["dias_sin_domicilio"] == int(saltos.max()) - 1
    assert j["ultimo_domicilio"] == fechas.iloc[-1].strftime("%Y-%m-%d")
