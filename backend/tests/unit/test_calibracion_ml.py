"""Calibracion de Apriori (0.005 / 0.15 / 1.0, lift estricto) y etiquetas unicas del K-Means RFM. Datos sinteticos."""
import numpy as np
import pandas as pd
import pytest

from app.core.config import Settings
from app.etl.pipeline import ConfigAnalitica
from app.ml import basket_apriori, rfm_kmeans
from app.ml.rfm_kmeans import _ETIQUETAS_POR_K, _etiquetar


# ---- Valores por defecto de Apriori
def test_defaults_apriori_config_y_pipeline():
    campos = Settings.model_fields
    assert (campos["apriori_min_support"].default, campos["apriori_min_confidence"].default,
            campos["apriori_min_lift"].default) == (0.005, 0.15, 1.0)
    c = ConfigAnalitica()
    assert (c.apriori_min_support, c.apriori_min_confidence, c.apriori_min_lift) == (0.005, 0.15, 1.0)


# ---- Apriori: lift estrictamente mayor que el minimo
def _matriz(filas):
    """filas = [(A, B, cantidad)] -> DataFrame binario con `cantidad` repeticiones de cada patron."""
    reg = [(a, b) for a, b, n in filas for _ in range(n)]
    return pd.DataFrame(reg, columns=["A", "B"], dtype=bool)


def test_lift_exactamente_uno_no_entra():
    # A y B independientes: P(A)=P(B)=0.5, P(A,B)=0.25 -> lift = 0.25 / (0.5 x 0.5) = 1.0 exacto
    mx = _matriz([(True, True, 25), (True, False, 25), (False, True, 25), (False, False, 25)])
    assert basket_apriori.minar_reglas(mx, 0.005, 0.15, 1.0).empty
    # con un minimo apenas menor la misma regla si aparece (y su lift es 1.0): el corte es estricto, no por redondeo
    r = basket_apriori.minar_reglas(mx, 0.005, 0.15, 0.99)
    assert len(r) == 2 and (r["lift"] == 1.0).all()


def test_lift_mayor_que_uno_entra_con_los_defaults():
    # P(A)=P(B)=0.5, P(A,B)=0.4 -> confianza 0.8, lift = 0.4 / 0.25 = 1.6
    mx = _matriz([(True, True, 40), (True, False, 10), (False, True, 10), (False, False, 40)])
    r = basket_apriori.minar_reglas(mx, 0.005, 0.15, 1.0)
    assert len(r) == 2
    assert r["lift"].tolist() == pytest.approx([1.6, 1.6])
    assert r["support"].tolist() == pytest.approx([0.4, 0.4]) and r["confidence"].tolist() == pytest.approx([0.8, 0.8])


def test_lift_menor_que_uno_no_entra():
    # P(A)=P(B)=0.5, P(A,B)=0.1 -> lift = 0.1 / 0.25 = 0.4
    mx = _matriz([(True, True, 10), (True, False, 40), (False, True, 40), (False, False, 10)])
    assert basket_apriori.minar_reglas(mx, 0.005, 0.15, 1.0).empty


def test_soporte_bajo_0005_aun_se_mina_con_matriz_grande():
    # 1000 ventas; la pareja A+B ocurre en 6 (soporte 0.006 >= 0.005); A en 10 y B en 10 -> lift = 0.006/(0.01*0.01) = 60
    reg = [(True, True)] * 6 + [(True, False)] * 4 + [(False, True)] * 4 + [(False, False)] * 986
    r = basket_apriori.minar_reglas(pd.DataFrame(reg, columns=["A", "B"], dtype=bool), 0.005, 0.15, 1.0)
    assert len(r) == 2 and r["lift"].tolist() == pytest.approx([60.0, 60.0])
    # con soporte 0.007 (> 0.006) la pareja ya no es frecuente
    assert basket_apriori.minar_reglas(pd.DataFrame(reg, columns=["A", "B"], dtype=bool), 0.007, 0.15, 1.0).empty


# ---- K-Means: etiquetas unicas por cluster (_etiquetar directo, clusters con valores exactos)
def _clusters(valores, n=3):
    """valores = [(recencia, frecuencia, monetario)] por cluster; `n` clientes identicos por cluster."""
    filas = [(c, r, f, mo) for c, (r, f, mo) in enumerate(valores) for _ in range(n)]
    return pd.DataFrame(filas, columns=["cluster", "recency", "frequency", "monetary"])


@pytest.mark.parametrize("k", [2, 3, 4, 5, 6])
def test_etiquetas_unicas_y_en_orden_para_cada_k(k):
    # cluster 0 = mejor (reciente, frecuente, gasta mas) ... cluster k-1 = peor; recencia siempre peor que la mediana
    # en los clusters "En riesgo"/"Perdidos", asi que ninguno se convierte en "Nuevos".
    valores = [(10 + 40 * i, 20 - 3 * i, 1000 - 150 * i) for i in range(k)]
    etiquetas = _etiquetar(_clusters(valores))
    assert etiquetas == dict(enumerate(_ETIQUETAS_POR_K[k]))
    assert len(set(etiquetas.values())) == k


def test_tabla_de_etiquetas_cubre_k_2_a_6_sin_repetir():
    assert set(_ETIQUETAS_POR_K) == {2, 3, 4, 5, 6}
    for k, nombres in _ETIQUETAS_POR_K.items():
        assert len(nombres) == k == len(set(nombres))
        assert nombres[0] == "Campeones"


def test_en_riesgo_con_recencia_reciente_pasa_a_nuevos():
    # A (mejor), B, C: C tiene el peor puntaje por frecuencia/monto pero compro hace 5 dias (<= mediana 20) -> "Nuevos"
    etiquetas = _etiquetar(_clusters([(20, 20, 1000), (100, 10, 500), (5, 1, 10)]))
    assert etiquetas == {0: "Campeones", 1: "Ocasionales", 2: "Nuevos"}


def test_nuevos_se_usa_una_sola_vez_y_el_otro_riesgo_conserva_su_nombre():
    # k=5: "En riesgo" (c3) y "Perdidos" (c4) ambos con recencia <= mediana (30): solo el primero pasa a "Nuevos"
    # (recencias 25, 26 <= mediana 30; frecuencia y monto de c3/c4 muy por debajo, asi que son los dos peores)
    valores = [(30, 200, 100000), (40, 150, 80000), (50, 100, 60000), (25, 2, 100), (26, 1, 50)]
    etiquetas = _etiquetar(_clusters(valores))
    assert etiquetas == {0: "Campeones", 1: "Leales", 2: "Prometedores", 3: "Nuevos", 4: "Perdidos"}


def test_k2_nunca_genera_riesgo_ni_nuevos():
    etiquetas = _etiquetar(_clusters([(10, 20, 1000), (200, 1, 10)]))
    assert etiquetas == {0: "Campeones", 1: "Ocasionales"}


def test_columna_constante_no_rompe_el_etiquetado():
    # frecuencia identica en todos los clientes (desviacion 0): sigue habiendo una etiqueta distinta por cluster
    etiquetas = _etiquetar(_clusters([(10, 5, 1000), (60, 5, 500), (120, 5, 100)]))
    assert etiquetas == {0: "Campeones", 1: "Ocasionales", 2: "En riesgo"}


def test_etiquetas_usan_los_numeros_de_cluster_de_entrada():
    # los ids de cluster no tienen por que ser 0..k-1 en orden de calidad
    df = _clusters([(10, 20, 1000), (60, 10, 500)])
    df["cluster"] = df["cluster"].map({0: 7, 1: 3})
    assert _etiquetar(df) == {7: "Campeones", 3: "Ocasionales"}


# ---- K-Means de punta a punta: k elegido por silueta, etiquetas unicas
def _blobs(k, por_grupo=12, semilla=0):
    """k grupos muy separados en escala logaritmica (recencia sube, frecuencia y monto bajan)."""
    rng = np.random.default_rng(semilla)
    partes = []
    for i in range(k):
        rec, fre, mon = 4 * 3.0 ** i, 60 / 2.0 ** i, 2_000_000 / 3.5 ** i
        partes.append(pd.DataFrame({
            "recency": np.maximum(1, rng.normal(rec, rec * 0.03, por_grupo)).round().astype(int),
            "frequency": np.maximum(1, rng.normal(fre, fre * 0.03, por_grupo)).round().astype(int),
            "monetary": np.abs(rng.normal(mon, mon * 0.03, por_grupo))}))
    df = pd.concat(partes, ignore_index=True)
    df.insert(0, "customer_id", range(1, len(df) + 1))
    return df


@pytest.mark.parametrize("k", [2, 3, 4, 5, 6])
def test_segmentar_cada_cluster_recibe_una_etiqueta_distinta(k):
    out, met = rfm_kmeans.segmentar(_blobs(k))
    assert met["k"] == k
    etiquetas_por_cluster = out.groupby("cluster")["segment_label"].nunique()
    assert (etiquetas_por_cluster == 1).all()                      # un cluster, una etiqueta
    assert out["segment_label"].nunique() == k                     # clusters distintos, etiquetas distintas
    assert set(out["segment_label"]) <= set(_ETIQUETAS_POR_K[k]) | {"Nuevos"}

