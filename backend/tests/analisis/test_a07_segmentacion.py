"""a07_segmentacion: puntajes RFM 1-5, segmentos para todos los clientes y K-Means (silueta por k = 2 a 6)."""
import numpy as np
import pandas as pd
import pytest

from analisis import a07_segmentacion as a07
from tests.analisis.conftest import leer_json

NOMBRES = [s[0] for s in a07.SEGMENTOS]


def test_puntaje_por_quintiles_a_mano():
    # cortes de 1..10 (20, 40, 60, 80 %): 2,8 ; 4,6 ; 6,4 ; 8,2 -> puntaje = 1 + cortes superados
    p = a07.puntaje(pd.Series(range(1, 11)))
    assert p.tolist() == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    assert a07.puntaje(pd.Series(range(1, 11)), invertir=True).tolist() == [5, 5, 4, 4, 3, 3, 2, 2, 1, 1]


def test_puntaje_con_empates_queda_entre_1_y_5():
    p = a07.puntaje(pd.Series([1] * 8 + [2, 9]))
    assert p.min() >= 1 and p.max() <= 5
    assert a07.puntaje(pd.Series([3, 3, 3, 3])).tolist() == [1, 1, 1, 1]         # todos iguales: nadie supera ningun corte


def test_calcular_rfm_a_mano():
    ventas = pd.DataFrame({"id": [1, 2, 3], "customer_id": [1.0, 1.0, 2.0],
                           "fecha": pd.to_datetime(["2026-11-01", "2026-11-10", "2026-11-12"]),
                           "total_amount": [100.0, 200.0, 50.0]})
    rfm = a07.calcular_rfm(ventas, pd.Timestamp("2026-11-13"))
    assert rfm.loc[1].tolist() == [3, 2, 300.0]                  # recencia (13-nov - 10-nov), pedidos, dinero
    assert rfm.loc[2].tolist() == [1, 1, 50.0]


def test_segmentos_a_mano_y_todos_asignados():
    rfm = pd.DataFrame({"recencia": range(1, 11), "frecuencia": [5, 1, 3, 2, 2, 1, 2, 1, 4, 1],
                        "monetario": [500, 100, 300, 200, 200, 100, 200, 100, 400, 100]})
    r = a07.asignar_segmentos(rfm)
    assert r["R"].tolist() == [5, 5, 4, 4, 3, 3, 2, 2, 1, 1]
    assert r["segmento"].tolist() == ["Campeones", "Nuevos", "Leales", "Prometedores", "Necesitan atención",
                                      "Una sola vez", "En riesgo", "Una sola vez", "En riesgo", "Una sola vez"]
    assert r["segmento"].isin(NOMBRES).all() and r["segmento"].notna().all()
    assert r[["R", "F", "M"]].stack().between(1, 5).all()
    assert "R" not in rfm.columns                                   # no modifica la entrada


@pytest.mark.parametrize("f", [1, 2, 3, 4, 7])
@pytest.mark.parametrize("r", [1, 2, 3, 4, 5])
def test_las_reglas_de_segmento_cubren_todas_las_combinaciones(r, f):
    asignados = [nombre for nombre, regla, _ in a07.SEGMENTOS if regla(r, f)]
    assert asignados, f"R={r}, F={f} sin segmento"


def test_segmentos_de_la_bd_sintetica_cubren_a_todos_los_clientes_de_domicilio(corrida):
    j = leer_json(corrida["a"], "a07_segmentacion")
    dom = j["poblaciones"]["clientes_de_domicilio"]
    tabla = j["segmentos"]["tabla"]
    assert [s["segmento"] for s in tabla] == NOMBRES
    assert sum(s["clientes"] for s in tabla) == dom > 7
    assert sum(s["pct_clientes"] for s in tabla) == pytest.approx(1.0, abs=1e-5)
    assert sum(s["pct_dinero"] for s in tabla) == pytest.approx(1.0, abs=1e-5)
    assert sum(s["dinero"] for s in tabla) == pytest.approx(j["segmentos"]["dinero_total"], abs=1e-3)
    assert j["rfm_resumen"]["frecuencia"]["count"] == dom
    for s in tabla:
        if s["clientes"]:
            assert all(1 <= s[k] <= 5 for k in ("puntaje_r", "puntaje_f", "puntaje_m"))


def test_poblaciones_usa_el_dia_siguiente_al_ultimo_domicilio(corrida):
    p = leer_json(corrida["a"], "a07_segmentacion")["poblaciones"]
    ultimo, ref = pd.Timestamp(p["ultimo_domicilio"]), pd.Timestamp(p["fecha_referencia"])
    assert ref - ultimo == pd.Timedelta(days=1)
    assert p["clientes_registrados"] == 40 and p["clientes_de_domicilio"] <= 40


def test_kmeans_silueta_para_k_de_2_a_6(corrida):
    k = leer_json(corrida["a"], "a07_segmentacion")["kmeans"]
    siluetas = k["silueta_por_k"]
    assert list(siluetas) == ["2", "3", "4", "5", "6"]
    assert all(-1 <= s <= 1 for s in siluetas.values())
    assert k["mejor_k"] == int(max(siluetas, key=siluetas.get))
    assert k["silueta_mejor"] == siluetas[str(k["mejor_k"])]
    assert len(k["grupos"]) == k["mejor_k"] and k["semilla"] == 42
    assert sum(g["pct_clientes"] for g in k["grupos"]) == pytest.approx(1.0, abs=1e-5)
    assert -1 <= k["rand_ajustado_vs_reglas"] <= 1


def test_kmeans_separa_grupos_bien_definidos():
    """Tres nubes muy separadas: k = 3 debe tener la mejor silueta (y alta)."""
    rng = np.random.default_rng(0)
    centros = [(3, 1, 3), (60, 2, 3), (200, 6, 5)]    # recencia (dias), pedidos, gasto en miles
    filas = [[max(1, c[0] * rng.uniform(0.9, 1.1)), c[1], c[2] * 1000 * rng.uniform(0.9, 1.1)]
             for c in centros for _ in range(15)]
    rfm = a07.asignar_segmentos(pd.DataFrame(filas, columns=["recencia", "frecuencia", "monetario"]))
    rep = type("R", (), {"datos": {}})()
    a07.kmeans(rfm, rep)
    k = rep.datos["kmeans"]
    assert k["mejor_k"] == 3 and k["silueta_mejor"] > 0.7
    assert sorted(g["clientes"] for g in k["grupos"]) == [15, 15, 15]
