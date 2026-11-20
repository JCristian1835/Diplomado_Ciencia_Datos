"""a03_inferencia: Mann-Whitney, chi-cuadrado, Kruskal-Wallis y bootstrap contra scipy y calculos a mano."""
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from analisis import a03_inferencia as a03
from analisis import comun
from tests.analisis.conftest import leer_json


# ---------------------------------------------------------------- Mann-Whitney
def test_mann_whitney_muestras_separadas_a_mano():
    r = a03.mann_whitney(np.array([1, 2, 3, 4, 5]), np.array([6, 7, 8, 9, 10]))
    assert r["U"] == 0                                         # ningun valor de a supera a uno de b
    assert r["delta_cliff"] == -1 and r["magnitud"] == "grande"
    assert r["p"] == pytest.approx(2 / 252)                    # exacto: 2 / C(10, 5)
    inversa = a03.mann_whitney(np.array([6, 7, 8, 9, 10]), np.array([1, 2, 3, 4, 5]))
    assert inversa["U"] == 25 and inversa["delta_cliff"] == 1 and inversa["p"] == pytest.approx(2 / 252)


def test_mann_whitney_entrelazadas_a_mano():
    r = a03.mann_whitney(np.array([1, 3, 5, 7, 9]), np.array([2, 4, 6, 8, 10]))
    assert r["U"] == 10                                        # pares a > b: 0 + 1 + 2 + 3 + 4
    assert r["delta_cliff"] == pytest.approx(-0.2)             # 2 x 10 / 25 - 1
    assert r["magnitud"] == "pequeño"


def test_mann_whitney_coincide_con_scipy_y_con_el_conteo_de_pares():
    rng = np.random.default_rng(3)
    a, b = rng.normal(10, 2, 35), rng.normal(11, 3, 45)
    r = a03.mann_whitney(a, b)
    ref = stats.mannwhitneyu(a, b, alternative="two-sided")
    assert (r["U"], r["p"]) == (ref.statistic, ref.pvalue)
    mayores = sum(x > y for x in a for y in b)
    menores = sum(x < y for x in a for y in b)
    assert r["delta_cliff"] == pytest.approx((mayores - menores) / (len(a) * len(b)))   # delta de Cliff por definicion


@pytest.mark.parametrize("delta,esperado", [
    (0.0, "insignificante"), (0.146, "insignificante"), (-0.146, "insignificante"),
    (0.147, "pequeño"), (-0.329, "pequeño"), (0.33, "mediano"), (-0.473, "mediano"),
    (0.474, "grande"), (-1.0, "grande"),
])
def test_magnitud_del_delta_de_cliff(delta, esperado):
    assert a03.magnitud(delta) == esperado


def test_concluir_usa_alfa_0_05():
    assert a03.concluir(0.049, "dif", "igual") == "dif (p < 0,05)."
    assert a03.concluir(0.05, "dif", "igual") == "igual (p >= 0,05)."


# ---------------------------------------------------------------- bootstrap
def test_bootstrap_de_grupos_constantes_es_exacto():
    ic = a03.bootstrap_diferencia_medias(np.full(8, 10.0), np.full(9, 4.0), np.random.default_rng(1))
    assert ic.tolist() == [6.0, 6.0]


def test_bootstrap_con_semilla_fija_es_determinista():
    rng = np.random.default_rng(5)
    a, b = rng.normal(10, 2, 40), rng.normal(8, 2, 40)
    ic1 = a03.bootstrap_diferencia_medias(a, b, np.random.default_rng(comun.SEMILLA))
    ic2 = a03.bootstrap_diferencia_medias(a, b, np.random.default_rng(comun.SEMILLA))
    ic3 = a03.bootstrap_diferencia_medias(a, b, np.random.default_rng(comun.SEMILLA + 1))
    assert ic1.tolist() == ic2.tolist()
    assert ic1.tolist() != ic3.tolist()


def test_bootstrap_es_coherente_con_el_error_estandar_teorico():
    rng = np.random.default_rng(11)
    a, b = rng.normal(10, 2, 50), rng.normal(7, 2, 60)
    ic = a03.bootstrap_diferencia_medias(a, b, np.random.default_rng(comun.SEMILLA))
    diferencia = a.mean() - b.mean()
    ee = math.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    assert ic[0] < diferencia < ic[1]
    assert (ic[1] - ic[0]) / 2 == pytest.approx(1.96 * ee, rel=0.1)       # IC 95 % ~ +/- 1,96 EE


# ---------------------------------------------------------------- chi-cuadrado
def _ventas(celdas):
    """celdas: {(canal, periodo): n}. Agrega filas que deben ignorarse (otro periodo y otro canal)."""
    filas = [(c, p) for (c, p), k in celdas.items() for _ in range(k)] + [("mesa", "arranque")] * 7 \
        + [("sin_dato", "base")] * 3
    return pd.DataFrame(filas, columns=["canal", "periodo"])


def test_chi_cuadrado_2x2_a_mano_con_correccion_de_yates():
    ventas = _ventas({("mesa", "base"): 30, ("llevar", "base"): 10, ("mesa", "caida"): 20, ("llevar", "caida"): 20})
    rep = SimpleNamespace(datos={})
    a03.chi_cuadrado(ventas, ["mesa", "llevar"], "t", "k", rep)
    r = rep.datos["k"]
    # esperadas: mesa 25/25, llevar 15/15 ; Yates: (|O - E| - 0,5)^2 / E = 20,25 / E -> 1,62 + 2,7
    assert r["chi2"] == pytest.approx(4.32) and r["gl"] == 1
    assert r["p"] == pytest.approx(stats.chi2.sf(4.32, 1)) and r["p"] == pytest.approx(0.0376, abs=5e-4)
    assert r["v_cramer"] == pytest.approx(math.sqrt(4.32 / 80))
    assert r["esperada_minima"] == pytest.approx(15)
    assert r["tabla"] == {"base": {"mesa": 30, "llevar": 10}, "caida": {"mesa": 20, "llevar": 20}}


def test_chi_cuadrado_2x3_a_mano():
    ventas = _ventas({("mesa", "base"): 30, ("llevar", "base"): 10, ("domicilio", "base"): 10,
                      ("mesa", "caida"): 20, ("llevar", "caida"): 20, ("domicilio", "caida"): 10})
    rep = SimpleNamespace(datos={})
    a03.chi_cuadrado(ventas, ["mesa", "llevar", "domicilio"], "t", "k", rep)
    r = rep.datos["k"]
    # esperadas: 25/25, 15/15, 10/10 -> 25/25 x 2 + 25/15 x 2 + 0 = 16/3 ; g.l. = 2 ; p = exp(-chi2 / 2)
    assert r["chi2"] == pytest.approx(16 / 3) and r["gl"] == 2
    assert r["p"] == pytest.approx(math.exp(-8 / 3))
    assert r["v_cramer"] == pytest.approx(math.sqrt((16 / 3) / 100))
    assert r["esperada_minima"] == pytest.approx(10)


def test_chi_cuadrado_independientes_no_rechaza():
    ventas = _ventas({("mesa", "base"): 40, ("llevar", "base"): 20, ("mesa", "caida"): 40, ("llevar", "caida"): 20})
    rep = SimpleNamespace(datos={})
    a03.chi_cuadrado(ventas, ["mesa", "llevar"], "t", "k", rep)
    assert rep.datos["k"]["chi2"] == pytest.approx(0) and rep.datos["k"]["p"] == pytest.approx(1)
    assert "(p >= 0,05)" in rep.datos["k"]["conclusion"]


# ---------------------------------------------------------------- sobre la BD sintetica
def test_json_mann_whitney_coincide_con_scipy_sobre_los_datos(corrida, datos):
    c = comun.dias_comparables(datos.diario)
    base = c[c["periodo"] == "base"]["pedidos"].to_numpy()
    caida = c[c["periodo"] == "caida"]["pedidos"].to_numpy()
    ref = stats.mannwhitneyu(base, caida, alternative="two-sided")
    j = leer_json(corrida["a"], "a03_inferencia")["pedidos_por_dia_abierto"]
    assert (j["base_n"], j["caida_n"]) == (106, 62)
    assert j["mann_whitney"]["U"] == pytest.approx(ref.statistic)
    assert j["mann_whitney"]["p"] == pytest.approx(ref.pvalue, abs=1e-6)
    assert j["diferencia_medias"] == pytest.approx(base.mean() - caida.mean(), abs=1e-5)
    assert j["ic95_bootstrap"][0] <= j["diferencia_medias"] <= j["ic95_bootstrap"][1]
    assert (j["semilla"], j["replicas"]) == (42, 10000)
    sin = j["sin_dias_casi_vacios"]
    assert sin["base_n"] == (base > 5).sum() and sin["caida_n"] == (caida > 5).sum()   # excluye los dias de 5 pedidos o menos


def test_json_chi_cuadrado_y_kruskal_coinciden_con_scipy(corrida, datos):
    j = leer_json(corrida["a"], "a03_inferencia")
    v = datos.ventas[datos.ventas["periodo"].isin(["base", "caida"]) & datos.ventas["canal"].isin(["mesa", "llevar", "domicilio"])]
    cruce = pd.crosstab(v["canal"], v["periodo"]).loc[["mesa", "llevar", "domicilio"], ["base", "caida"]]
    ref = stats.chi2_contingency(cruce)
    assert j["chi2_canal_periodo"]["chi2"] == pytest.approx(ref.statistic, abs=1e-5)
    assert j["chi2_canal_periodo"]["p"] == pytest.approx(ref.pvalue, abs=1e-6)
    assert j["chi2_canal_periodo"]["gl"] == 2
    c = comun.dias_comparables(datos.diario)
    h = stats.kruskal(*[g["pedidos"].to_numpy() for _, g in c.groupby("dia_semana")])
    k = j["kruskal_dia_semana"]["Base + caída"]
    assert k["H"] == pytest.approx(h.statistic, abs=1e-5) and k["gl"] == 5
    assert k["epsilon2"] == pytest.approx(h.statistic / (len(c) - 1), abs=1e-5)


def test_json_ticket_compara_caida_contra_base(corrida, datos):
    v = datos.ventas
    base = v[v["periodo"] == "base"]["total_amount"].to_numpy(dtype=float)
    caida = v[v["periodo"] == "caida"]["total_amount"].to_numpy(dtype=float)
    j = leer_json(corrida["a"], "a03_inferencia")["ticket"]
    ref = stats.mannwhitneyu(caida, base, alternative="two-sided")
    assert j["mann_whitney_caida_vs_base"]["U"] == pytest.approx(ref.statistic)
    assert j["diferencia_medias"] == pytest.approx(caida.mean() - base.mean(), abs=1e-3)
    assert j["mediana_base"] == pytest.approx(np.median(base)) and j["pedidos_caida"] == len(caida)
