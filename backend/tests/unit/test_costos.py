"""Regla del costo faltante (domain/costos.py) y su uso en imputar() y en KpiRepoSQL. Datos sinteticos, BD temporal."""
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from app.adapters.outbound.persistence import models as m
from app.adapters.outbound.persistence.repositories import KpiRepoSQL
from app.application.kpis import ServicioKpis
from app.domain.costos import costo_unitario, razones_costo
from app.etl import transform as t

# (categoria, precio, costo)
PRODUCTOS = [
    ("a", 100.0, 40.0),     # razon 0.4
    ("a", 200.0, 100.0),    # razon 0.5  -> mediana "a" = 0.45
    ("b", 50.0, 10.0),      # razon 0.2  -> mediana "b" = 0.2
    ("b", 0.0, 5.0),        # precio 0: no cuenta
    ("c", 100.0, 0.0),      # costo 0: no cuenta
    ("c", 100.0, None),     # costo nulo: no cuenta
    (None, 10.0, 5.0),      # sin categoria, razon 0.5
    ("d", None, 5.0),       # precio nulo: no cuenta
]


# ---- razones_costo
def test_razones_por_categoria_y_global_a_mano():
    por_cat, glob = razones_costo(PRODUCTOS)
    assert set(por_cat) == {"a", "b", None}                  # "c" y "d" no tienen ningun producto valido
    assert por_cat["a"] == pytest.approx(0.45)               # mediana de {0.4, 0.5}
    assert por_cat["b"] == pytest.approx(0.2)
    assert por_cat[None] == pytest.approx(0.5)
    assert glob == pytest.approx(0.45)                       # mediana de {0.4, 0.5, 0.2, 0.5} = (0.4 + 0.5) / 2


def test_razones_ningun_costo_positivo_da_cero():
    assert razones_costo([("a", 100.0, 0.0), ("a", 100.0, None), ("b", 0.0, 0.0)]) == ({}, 0.0)
    assert razones_costo([]) == ({}, 0.0)


def test_razones_mediana_impar_y_acepta_iterador():
    por_cat, glob = razones_costo(iter([("x", 100.0, 10.0), ("x", 100.0, 50.0), ("x", 100.0, 90.0)]))
    assert por_cat == {"x": pytest.approx(0.5)} and glob == pytest.approx(0.5)


# ---- costo_unitario
def test_costo_real_positivo_se_respeta():
    r = razones_costo(PRODUCTOS)
    assert costo_unitario("a", 100.0, 7.0, r) == 7.0


@pytest.mark.parametrize("costo", [0, 0.0, None])
def test_costo_faltante_usa_mediana_de_su_categoria(costo):
    r = razones_costo(PRODUCTOS)
    assert costo_unitario("a", 100.0, costo, r) == pytest.approx(45.0)    # 100 x 0.45
    assert costo_unitario("b", 300.0, costo, r) == pytest.approx(60.0)    # 300 x 0.2
    assert costo_unitario(None, 10.0, costo, r) == pytest.approx(5.0)     # categoria None tiene su razon (0.5)


@pytest.mark.parametrize("categoria", ["c", "d", "no_existe"])
def test_categoria_sin_costos_usa_mediana_global(categoria):
    r = razones_costo(PRODUCTOS)
    assert costo_unitario(categoria, 200.0, 0, r) == pytest.approx(90.0)  # 200 x 0.45


def test_sin_ningun_costo_el_estimado_es_cero():
    r = razones_costo([("a", 100.0, 0.0)])
    assert costo_unitario("a", 100.0, 0, r) == 0.0
    assert costo_unitario("z", 100.0, None, r) == 0.0


def test_precio_cero_con_costo_faltante_da_cero():
    r = razones_costo(PRODUCTOS)
    assert costo_unitario("a", 0.0, 0, r) == 0.0


def test_costo_negativo_se_trata_como_faltante():
    r = razones_costo(PRODUCTOS)
    assert costo_unitario("a", 100.0, -5.0, r) == pytest.approx(45.0)


# ---- regla nueva: costo real solo si 0 < costo < precio
# (categoria, precio, costo): "a" tiene 2 reales (0.4 y 0.5) y 2 mal cargados; "b" solo mal cargados; "c" 1 real (0.2)
PRODUCTOS_MAL_CARGADOS = [
    ("a", 100.0, 40.0), ("a", 200.0, 100.0),   # razones 0.4 y 0.5 -> mediana "a" = 0.45
    ("a", 100.0, 100.0),                       # costo == precio: no es real
    ("a", 100.0, 250.0),                       # costo > precio: no es real (si contara, la mediana de "a" seria 0.5)
    ("b", 100.0, 100.0), ("b", 50.0, 80.0),    # "b" sin ningun costo real
    ("c", 100.0, 20.0),                        # razon 0.2
]


def test_razones_excluyen_costo_mayor_o_igual_al_precio():
    por_cat, glob = razones_costo(PRODUCTOS_MAL_CARGADOS)
    assert set(por_cat) == {"a", "c"}                         # "b" no tiene ningun costo real
    assert por_cat["a"] == pytest.approx(0.45)                # {0.4, 0.5}; con 1.0 y 2.5 seria 0.75
    assert por_cat["c"] == pytest.approx(0.2)
    assert glob == pytest.approx(0.4)                         # mediana de {0.4, 0.5, 0.2}


def test_razones_con_solo_costos_mayores_o_iguales_al_precio_da_vacio():
    assert razones_costo([("a", 100.0, 100.0), ("a", 100.0, 120.0), ("b", 10.0, 10.5)]) == ({}, 0.0)


@pytest.mark.parametrize("costo", [100.0, 100.01, 250.0, 1e9])
def test_costo_mayor_o_igual_al_precio_se_estima_con_su_categoria(costo):
    r = razones_costo(PRODUCTOS_MAL_CARGADOS)
    assert costo_unitario("a", 100.0, costo, r) == pytest.approx(45.0)     # 100 x 0.45, no el costo cargado
    assert costo_unitario("c", 50.0, costo, r) == pytest.approx(10.0)             # 50 x 0.2


@pytest.mark.parametrize("categoria,precio,esperado", [("b", 200.0, 80.0), ("no_existe", 50.0, 20.0)])
def test_costo_mayor_al_precio_sin_costos_reales_en_la_categoria_usa_la_mediana_global(categoria, precio, esperado):
    r = razones_costo(PRODUCTOS_MAL_CARGADOS)
    assert costo_unitario(categoria, precio, precio * 3, r) == pytest.approx(esperado)   # precio x 0.4


def test_costo_justo_por_debajo_del_precio_es_real():
    r = razones_costo(PRODUCTOS_MAL_CARGADOS)
    assert costo_unitario("a", 100.0, 99.99, r) == pytest.approx(99.99)
    assert costo_unitario("a", 100.0, 0.01, r) == pytest.approx(0.01)


@pytest.mark.parametrize("precio", [None, float("nan"), np.nan, 0, 0.0, -1.0, -100.0])
@pytest.mark.parametrize("costo", [None, 0.0, 5.0, 500.0, float("nan")])
def test_precio_invalido_da_cero_sin_excepcion(precio, costo):
    r = razones_costo(PRODUCTOS_MAL_CARGADOS)
    resultado = costo_unitario("a", precio, costo, r)
    assert resultado == 0.0 and isinstance(resultado, float)


def test_costo_nan_con_precio_valido_se_estima():
    r = razones_costo(PRODUCTOS_MAL_CARGADOS)
    assert costo_unitario("a", 100.0, float("nan"), r) == pytest.approx(45.0)


def test_precio_invalido_no_entra_en_las_medianas():
    por_cat, glob = razones_costo([("a", float("nan"), 5.0), ("a", None, 5.0), ("a", -10.0, 5.0), ("a", 100.0, 30.0)])
    assert por_cat == {"a": pytest.approx(0.3)} and glob == pytest.approx(0.3)


# ---- transform.imputar
def _productos_df(filas):
    return pd.DataFrame([{"id": i, "sku": f"S{i}", "name": f"P{i}", "category": c, "unit_price": p, "unit_cost": k,
                          "stock": 1, "is_active": True} for i, (c, p, k) in enumerate(filas, 1)])


def _items_df():
    return pd.DataFrame({"sale_id": [1], "created_at": pd.to_datetime(["2025-01-01 10:00"]), "customer_id": [1],
                         "product_id": [1], "quantity": [1.0], "unit_price": [100.0], "subtotal": [100.0]})


def test_imputar_costo_cero_y_nulo_se_estiman_con_su_categoria():
    # A: razones {0.4}; costo 0 de 200 -> 80 ; costo nulo de 50 -> 20. B sin costos -> mediana global.
    prods = _productos_df([("A", 100.0, 40.0), ("A", 200.0, 0.0), ("A", 50.0, None),
                           ("B", 100.0, 30.0), ("C", 100.0, 0.0)])
    _, out, _ = t.imputar(_items_df(), prods)
    # global = mediana de {A: 0.4, B: 0.3} = 0.35 -> producto C (sin costos en su categoria): 100 x 0.35
    assert out["unit_cost"].tolist() == pytest.approx([40.0, 80.0, 20.0, 30.0, 35.0])


def test_imputar_no_toca_costos_reales_ni_modifica_la_entrada():
    prods = _productos_df([("A", 100.0, 40.0), ("A", 100.0, 0.0)])
    antes = prods.copy()
    _, out, _ = t.imputar(_items_df(), prods)
    assert out["unit_cost"].tolist() == pytest.approx([40.0, 40.0])
    pd.testing.assert_frame_equal(prods, antes)


def test_imputar_sin_ningun_costo_deja_cero():
    _, out, _ = t.imputar(_items_df(), _productos_df([("A", 100.0, 0.0), ("B", 80.0, None)]))
    assert out["unit_cost"].tolist() == [0.0, 0.0]


def test_imputar_costo_mayor_o_igual_al_precio_se_estima_y_no_entra_en_la_mediana():
    # A: reales {0.4}; costo 100 de precio 100 (==) -> 40 ; costo 300 de precio 200 (>) -> 80.
    # B: solo un costo mayor al precio -> mediana global = {A: 0.4} = 0.4 -> 50 x 0.4 = 20.
    prods = _productos_df([("A", 100.0, 40.0), ("A", 100.0, 100.0), ("A", 200.0, 300.0), ("B", 50.0, 60.0)])
    _, out, _ = t.imputar(_items_df(), prods)
    assert out["unit_cost"].tolist() == pytest.approx([40.0, 40.0, 80.0, 20.0])


def test_imputar_precio_nulo_o_cero_da_costo_cero():
    prods = _productos_df([("A", 100.0, 40.0), ("A", 0.0, 5.0), ("A", np.nan, 5.0)])
    _, out, _ = t.imputar(_items_df(), prods)
    assert out["unit_cost"].tolist() == [40.0, 0.0, 0.0]


def test_imputar_categoria_nula_se_agrupa_como_sin_categoria():
    prods = _productos_df([(None, 100.0, 20.0), (None, 100.0, 0.0)])
    _, out, _ = t.imputar(_items_df(), prods)
    assert out["category"].tolist() == ["Sin categoría"] * 2
    assert out["unit_cost"].tolist() == pytest.approx([20.0, 20.0])


# ---- KpiRepoSQL (BD temporal)
@pytest.fixture
def kpis_bd(db_session):
    s = db_session
    prods = [  # (sku, categoria, precio, costo, stock, activo)
        ("P1", "Bebidas", 1000, 400, 10, True),   # razon 0.4
        ("P2", "Bebidas", 2000, 0, 5, True),      # estimado 2000 x 0.4 = 800
        ("P3", "Snacks", 500, 0, 4, True),        # Snacks sin costos -> global
        ("P4", "Aseo", 100, 20, 100, True),       # razon 0.2 ; global = mediana{0.4, 0.2} = 0.3 -> P3 = 150
        ("P5", "Bebidas", 1000, 0, 50, False),    # inactivo: fuera del inventario (estimado 400)
    ]
    ids = {}
    for sku, cat, precio, costo, stock, activo in prods:
        fila = m.ProductModel(sku=sku, name=sku, category=cat, unit_price=precio, unit_cost=costo, stock=stock,
                              is_active=activo)
        s.add(fila)
        s.flush()
        ids[sku] = fila.id

    def venta(estado, lineas):
        total = sum(q * p for _, q, p in lineas)
        s.add(m.SaleModel(total_amount=total, payment_method="cash", status=estado,
                          created_at=datetime(2026, 11, 10, 12, 0),
                          items=[m.SaleItemModel(product_id=ids[k], quantity=q, unit_price=p, subtotal=q * p)
                                 for k, q, p in lineas]))
    venta("COMPLETED", [("P2", 3, 2000), ("P3", 2, 500), ("P1", 1, 1000)])   # total 8000
    venta("CANCELLED", [("P1", 5, 1000)])                                    # no cuenta
    s.commit()
    return s, ids


AHORA = datetime(2026, 11, 15)


def test_kpi_costo_vendido_y_margen_con_costo_cero_estimado(kpis_bd):
    s, _ = kpis_bd
    r = ServicioKpis(KpiRepoSQL(s)).resumen(30, 5, ahora=AHORA)
    assert r["total_ventas"] == 8000 and r["n_ventas"] == 1 and r["unidades_vendidas"] == 6
    # 3 x 800 (P2 estimado) + 2 x 150 (P3 estimado con la mediana global) + 1 x 400 (P1 real)
    assert r["costo_vendido"] == pytest.approx(3100.0)
    assert r["margen"] == pytest.approx(4900.0)            # NO 8000: el costo 0 no se toma como real
    assert r["margen_pct"] == pytest.approx(61.25)         # 4900 / 8000


def test_kpi_valor_inventario_solo_activos_con_costo_estimado(kpis_bd):
    s, _ = kpis_bd
    # 10 x 400 + 5 x 800 + 4 x 150 + 100 x 20 = 4000 + 4000 + 600 + 2000 ; P5 inactivo no suma (50 x 400 = 20000)
    assert KpiRepoSQL(s).valor_inventario() == pytest.approx(10600.0)


def test_kpi_rotacion_usa_costo_estimado(kpis_bd):
    s, _ = kpis_bd
    r = ServicioKpis(KpiRepoSQL(s)).resumen(30, 5, ahora=AHORA)
    assert r["valor_inventario"] == pytest.approx(10600.0)
    assert r["rotacion"] == pytest.approx(3100 / 10600, abs=1e-3)


def test_kpi_no_modifica_products_unit_cost(kpis_bd):
    s, ids = kpis_bd
    ServicioKpis(KpiRepoSQL(s)).resumen(30, 5, ahora=AHORA)
    s.expire_all()
    assert s.get(m.ProductModel, ids["P2"]).unit_cost == 0
    assert s.get(m.ProductModel, ids["P3"]).unit_cost == 0
    assert s.get(m.ProductModel, ids["P1"]).unit_cost == 400


def test_kpi_costo_mayor_al_precio_se_estima_en_margen_e_inventario(db_session):
    s = db_session
    ids = {}
    for sku, precio, costo, stock in (("X", 1000, 400, 10), ("Y", 1000, 1500, 5)):   # Y: costo > precio
        fila = m.ProductModel(sku=sku, name=sku, category="Bebidas", unit_price=precio, unit_cost=costo, stock=stock,
                              is_active=True)
        s.add(fila)
        s.flush()
        ids[sku] = fila.id
    s.add(m.SaleModel(total_amount=2000, payment_method="cash", created_at=datetime(2026, 11, 10, 12, 0),
                      items=[m.SaleItemModel(product_id=ids["Y"], quantity=2, unit_price=1000, subtotal=2000)]))
    s.commit()
    r = ServicioKpis(KpiRepoSQL(s)).resumen(30, 5, ahora=AHORA)
    # Y se estima con la razon de X (0.4): costo 400 por unidad, no 1500
    assert r["costo_vendido"] == pytest.approx(800.0)             # 2 x 400 (con el costo cargado serian 3000)
    assert r["margen"] == pytest.approx(1200.0)
    assert r["valor_inventario"] == pytest.approx(6000.0)         # 10 x 400 + 5 x 400
    s.expire_all()
    assert s.get(m.ProductModel, ids["Y"]).unit_cost == 1500      # el dato original no se toca


def test_kpi_sin_ningun_costo_positivo_margen_igual_a_ventas(db_session):
    s = db_session
    p = m.ProductModel(sku="Z", name="Z", category="X", unit_price=100, unit_cost=0, stock=3, is_active=True)
    s.add(p)
    s.flush()
    s.add(m.SaleModel(total_amount=200, payment_method="cash", created_at=datetime(2026, 11, 10),
                      items=[m.SaleItemModel(product_id=p.id, quantity=2, unit_price=100, subtotal=200)]))
    s.commit()
    r = ServicioKpis(KpiRepoSQL(s)).resumen(30, 5, ahora=AHORA)
    assert r["costo_vendido"] == 0 and r["margen"] == 200 and r["valor_inventario"] == 0
