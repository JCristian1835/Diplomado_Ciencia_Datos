"""a05_demanda: validacion walk-forward sin fuga de datos del futuro y pronostico que no incluye martes."""
import copy

import numpy as np
import pandas as pd
import pytest

from analisis import a05_demanda as a05
from analisis import comun
from tests.analisis.conftest import leer_json

FIN = comun.FIN_CAIDA


@pytest.fixture
def historia(datos):
    return a05.Historia(datos.diario)


def _con_futuro_envenenado(h, origen):
    """Copia de la historia donde todo lo posterior a `origen` (posicion) vale 1.000.000."""
    h2 = copy.deepcopy(h)
    futuro = np.arange(len(h2.fechas)) > origen
    h2.y = h2.y.copy()
    h2.nivel = h2.nivel.copy()
    h2.y[futuro & h2.abierto] = 1e6
    h2.nivel[futuro] = 1e6
    return h2


# ---------------------------------------------------------------- Historia
def test_historia_nivel_es_el_promedio_de_los_ultimos_24_dias_abiertos(datos, historia):
    h = historia
    abiertos = datos.diario[datos.diario["abierto"] & (datos.diario["fecha"] <= FIN)].sort_values("fecha")["pedidos"]
    assert h.nivel[h.pos(FIN)] == pytest.approx(abiertos.tail(24).mean())
    # lo posterior al 12-nov no se conoce: sin pedidos y el nivel se mantiene (ffill)
    despues = h.pos(FIN) + 1
    assert np.isnan(h.y[despues:]).all()
    assert (h.nivel[despues:] == h.nivel[h.pos(FIN)]).all()


def test_historia_martes_no_es_dia_abierto_ni_tiene_pedidos(historia):
    h = historia
    martes = h.dia_semana == 1
    assert not h.abierto[martes].any() and h.abierto[~martes].all()
    assert np.isnan(h.y[martes]).all()
    assert h.coincide_dim_fecha is True


# ---------------------------------------------------------------- sin fuga
def test_pares_de_entrenamiento_solo_usan_objetivos_ya_conocidos(historia):
    h = historia
    origen = h.pos(FIN) - 30
    X, y, o, t = a05.pares(h, np.arange(origen), np.arange(1, 31), hasta=origen)
    assert len(t) > 0
    assert (t <= origen).all() and (o < t).all()                  # el objetivo ya habia ocurrido en el origen
    assert (h.dia_semana[t] != 1).all()                           # y nunca es martes
    # "semana anterior" es el mismo dia de la semana, ya observado en el origen (posicion <= origen del par)
    s = t - 7 * np.ceil((t - o) / 7).astype(int)
    assert (s <= o).all()
    np.testing.assert_allclose(X["semana_anterior"], h.y[s] / h.nivel[o])


@pytest.mark.parametrize("horizonte,ventana", [(7, 1), (7, 8), (30, 1), (30, 2)])
def test_los_pronosticos_de_una_ventana_no_cambian_si_se_alteran_los_datos_posteriores_a_su_origen(
        historia, horizonte, ventana):
    h = historia
    origen = h.pos(FIN) - horizonte * ventana                      # mismo origen que usa validar()
    saltos = np.arange(1, horizonte + 1)

    def pronosticos(hist):
        return a05.pronosticar(hist, origen, saltos, a05.entrenar_xgboost(hist, origen, horizonte))

    normal, envenenada = pronosticos(h), pronosticos(_con_futuro_envenenado(h, origen))
    # control: el veneno si llego a los datos de prueba...
    assert (envenenada["real"] == 1e6).all() and not (normal["real"] == 1e6).any()
    # ...pero ningun modelo lo uso para pronosticar
    pd.testing.assert_frame_equal(normal.drop(columns="real"), envenenada.drop(columns="real"), check_exact=True)


def test_ventanas_walk_forward_de_la_corrida(corrida):
    detalle = pd.DataFrame(leer_json(corrida["a"], "a05_demanda")["detalle_pruebas"])
    detalle["fecha"], detalle["origen"] = pd.to_datetime(detalle["fecha"]), pd.to_datetime(detalle["origen"])
    assert detalle.groupby("horizonte")["ventana"].nunique().to_dict() == {7: 8, 30: 2}
    assert (detalle["fecha"] > detalle["origen"]).all()                                   # se pronostica hacia adelante
    assert ((detalle["fecha"] - detalle["origen"]).dt.days <= detalle["horizonte"]).all()
    assert (detalle["fecha"] <= FIN).all()                                                # nada del 13-nov incompleto
    esperado = FIN - pd.to_timedelta(detalle["horizonte"] * detalle["ventana"], unit="D")
    assert (detalle["origen"] == esperado).all()
    assert (detalle["fecha"].dt.day_of_week != 1).all()
    assert (detalle["evaluable"] == (detalle["real"] > 5)).all()


# ---------------------------------------------------------------- pronostico
def test_el_pronostico_no_incluye_martes(corrida):
    j = leer_json(corrida["a"], "a05_demanda")
    p = pd.DataFrame(j["pronostico"])
    fechas = pd.to_datetime(p["fecha"])
    assert (fechas.dt.day_of_week != 1).all() and "martes" not in set(p["dia"])
    # 14-nov a 13-dic son 30 dias con 4 martes (17 y 24-nov, 1 y 8-dic) -> 26 dias abiertos
    assert len(p) == 26 and fechas.min() == pd.Timestamp("2026-11-14") and fechas.max() <= pd.Timestamp("2026-12-13")
    assert (p["minimo"] >= 0).all() and ((p["minimo"] <= p["pronostico"]) & (p["pronostico"] <= p["maximo"])).all()
    assert j["pronostico_total_pedidos"] == pytest.approx(p["pronostico"].sum(), abs=1e-3)
    assert j["calendario_coincide_dim_fecha"] is True and j["semilla"] == 42


def test_pares_de_pronostico_nunca_caen_en_martes(historia):
    h = historia
    _, _, _, t = a05.pares(h, np.arange(100, 140), np.arange(1, 31), hasta=len(h.fechas))
    assert len(t) > 0 and (h.dia_semana[t] != 1).all()


# ---------------------------------------------------------------- metricas y eleccion
def test_metricas_a_mano_excluyen_los_dias_no_evaluables():
    pruebas = pd.DataFrame({
        "horizonte": [7, 7, 7, 7], "real": [10.0, 20.0, 30.0, 3.0], "evaluable": [True, True, True, False],
        "M1": [12.0, 18.0, 33.0, 40.0], "M2": [10.0, 20.0, 30.0, 40.0], "M3": [10.0, 20.0, 36.0, 40.0]})
    met = a05.metricas(pruebas)[7]
    assert met["M1"]["mae"] == pytest.approx(7 / 3)                  # errores 2, 2, 3
    assert met["M2"]["mae"] == 0 and met["M3"]["mae"] == pytest.approx(2.0)
    assert met["M1"]["r2"] == pytest.approx(1 - 17 / 200)            # SSE 17 ; SST 200 (media 20)
    assert met["M2"]["r2"] == pytest.approx(1.0)
    assert met["M1"]["dias_evaluados"] == 3 and met["ganador"] == "M2"


def test_eleccion_del_modelo():
    def met(g7, g30):
        return {7: {"ganador": g7}, 30: {"ganador": g30}}
    assert a05.elegir_modelo(met("M3", "M1"))[0] == "M3"             # XGBoost gana a 7 dias
    assert a05.elegir_modelo(met("M1", "M2"))[0] == "M2"             # si no, el ganador a 30 dias
    assert a05.elegir_modelo(met("M2", "M3"))[0] == "M3"


def test_la_banda_usa_el_mae_a_30_dias_del_modelo_elegido(corrida):
    j = leer_json(corrida["a"], "a05_demanda")
    assert j["mae_banda"] == pytest.approx(j["metricas"]["30"][j["modelo_elegido"]]["mae"], abs=1e-5)
    assert set(j["metricas"]) == {"7", "30"}
    p = j["pronostico"][0]
    assert p["maximo"] - p["pronostico"] == pytest.approx(j["mae_banda"], abs=1e-5)
