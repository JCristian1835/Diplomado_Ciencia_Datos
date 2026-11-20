"""a06_venta_cruzada: margen de combo = 0,9 x suma de precios reales - costos; hallazgos de catalogo; canastas."""
from types import SimpleNamespace

import pandas as pd
import pytest

from analisis import a06_venta_cruzada as a06
from tests.analisis.conftest import leer_json


# ---------------------------------------------------------------- combos
def test_armar_combo_a_mano():
    margen = pd.DataFrame({"precio_real": [20000.0, 5000.0], "costo": [8000.0, 1500.0]}, index=["Plato", "Bebida"])
    categorias = {"Plato": "platos", "Bebida": "bebidas"}
    for a, b in (("Plato", "Bebida"), ("Bebida", "Plato")):         # el orden de la regla no cambia el resultado
        c = a06.armar_combo(a, b, 0.05, 2.5, margen, categorias)
        assert (c["plato"], c["bebida"]) == ("Plato", "Bebida")
        assert c["suma_precios"] == 25000
        assert c["precio_combo"] == pytest.approx(22500)             # 0,9 x 25.000
        assert c["costo"] == 9500
        assert c["margen"] == pytest.approx(13000)                   # 22.500 - 9.500
        assert c["margen_pct"] == pytest.approx(13000 / 22500)
        assert c["margen_sin_descuento"] == pytest.approx(15500)     # 25.000 - 9.500
    assert a06.DESCUENTO_COMBO == 0.10 and a06.LIFT_COMBO == 2.0


def test_combos_de_la_bd_sintetica_usan_precio_real_y_costo_efectivo(corrida):
    j = leer_json(corrida["a"], "a06_venta_cruzada")
    margenes = {m["producto"]: m for m in j["margenes"]}
    combos = j["combos"]["sugeridos"]
    assert j["combos"]["pares_candidatos"] >= 2 and len(combos) >= 2
    for c in combos:
        assert margenes[c["bebida"]]["categoria"] == "bebidas" and margenes[c["plato"]]["categoria"] != "bebidas"
        assert c["lift"] >= 2.0
        suma = margenes[c["plato"]]["precio_real"] + margenes[c["bebida"]]["precio_real"]
        costo = margenes[c["plato"]]["costo"] + margenes[c["bebida"]]["costo"]
        assert c["suma_precios"] == pytest.approx(suma)
        assert c["precio_combo"] == pytest.approx(0.9 * suma)
        assert c["costo"] == pytest.approx(costo)
        assert c["margen"] == pytest.approx(0.9 * suma - costo)
        assert c["margen_sin_descuento"] == pytest.approx(suma - costo)
    por_par = {(c["plato"], c["bebida"]): c for c in combos}
    # A mano: Hamburguesa 15.000 (costo 6.000) + Gaseosa 4.000 (1.500) -> 0,9 x 19.000 = 17.100 ; 17.100 - 7.500
    assert por_par[("Hamburguesa", "Gaseosa")]["margen"] == pytest.approx(9600)
    # Pizza se cobra a 30.000 (no a la lista 20.000): 0,9 x 35.000 = 31.500 ; costo 8.000 + 1.937,5 (Jugo estimado)
    assert por_par[("Pizza", "Jugo")]["margen"] == pytest.approx(31500 - 9937.5)
    soportes = [c["soporte"] for c in combos]
    assert soportes == sorted(soportes, reverse=True)               # los mas frecuentes primero


def test_margenes_por_producto_de_la_bd_sintetica(corrida):
    m = {x["producto"]: x for x in leer_json(corrida["a"], "a06_venta_cruzada")["margenes"]}
    assert m["Pizza"]["precio_real"] == 30000 and m["Pizza"]["margen"] == pytest.approx(22000)
    assert not m["Pizza"]["costo_estimado"]
    assert m["Jugo"]["costo"] == pytest.approx(1937.5) and m["Jugo"]["costo_estimado"]      # costo 0 -> estimado
    assert m["Jugo"]["margen_pct"] == pytest.approx(3062.5 / 5000)
    assert m["Postre"]["costo"] == pytest.approx(2000) and m["Postre"]["costo_estimado"]     # costo 6.000 >= precio 5.000
    assert m["Postre"]["margen"] == pytest.approx(3000) and m["Postre"]["margen"] > 0
    assert m["Prod_SinVentas"]["precio_real"] == 7000 and m["Prod_SinVentas"]["unidades_vendidas"] == 0
    assert m["Prod_Mediana"]["unidades_vendidas"] == 3              # la venta cancelada no cuenta


# ---------------------------------------------------------------- hallazgos de catalogo
def test_hallazgos_detectan_costo_mayor_al_precio_y_precio_de_lista_distinto_al_cobrado(datos):
    rep = SimpleNamespace(datos={})
    a06.hallazgos_catalogo(datos.items, datos.productos, rep)
    h = {f["producto"]: f for f in rep.datos["hallazgos_catalogo"]}
    assert h["Postre"]["hallazgo"] == "costo registrado >= precio de lista"
    assert h["Postre"]["costo_registrado"] == 6000 and h["Postre"]["costo_usado"] == pytest.approx(2000)
    assert h["Pizza"]["hallazgo"] == "precio de lista distinto al cobrado"
    assert (h["Pizza"]["precio_lista"], h["Pizza"]["precio_real"]) == (20000, 30000)
    # Prod_Mediana: lista = real (9.000) pero 1 de 3 ventas (20.000) se aparta mas del 20 % -> 33 % > 30 %
    assert h["Prod_Mediana"]["hallazgo"] == "33 % de las ventas con otro precio"


def test_hallazgos_no_marcan_productos_sanos(datos):
    rep = SimpleNamespace(datos={})
    a06.hallazgos_catalogo(datos.items, datos.productos, rep)
    marcados = {f["producto"] for f in rep.datos["hallazgos_catalogo"]}
    assert marcados == {"Postre", "Pizza", "Prod_Mediana"}
    # sanos: Hamburguesa, Gaseosa, Cerveza; Jugo (costo 0, no es >= precio); Prod_Cerca (11.000 vs lista 10.000: +10 %,
    # dentro del 20 %); Prod_SinVentas (sin ventas, precio real = lista)


def test_costo_igual_al_precio_tambien_es_hallazgo():
    productos = pd.DataFrame({"id": [1], "name": ["X"], "category": ["platos"], "unit_price": [100.0],
                              "unit_cost": [100.0], "precio_real": [100.0], "costo": [40.0]})
    items = pd.DataFrame({"product_id": [1, 1], "unit_price": [100.0, 100.0]})
    rep = SimpleNamespace(datos={})
    a06.hallazgos_catalogo(items, productos, rep)
    assert [f["hallazgo"] for f in rep.datos["hallazgos_catalogo"]] == ["costo registrado >= precio de lista"]


# ---------------------------------------------------------------- canastas y bebidas
def test_canastas_a_mano():
    items = pd.DataFrame({"sale_id": [1, 1, 2, 3, 3], "product_id": [10, 11, 10, 12, 12]})
    rep = SimpleNamespace(datos={})
    a06.canastas(items, rep)
    c = rep.datos["canastas"]
    # pedido 1: 2 productos distintos; pedido 2: 1; pedido 3: el mismo producto dos veces = 1 distinto
    assert (c["pedidos"], c["con_2_o_mas_productos"], c["maximo_productos"]) == (3, 1, 2)
    assert c["pct_con_2_o_mas"] == pytest.approx(1 / 3) and c["productos_promedio"] == pytest.approx(4 / 3)


def test_pedidos_sin_bebida_a_mano():
    items = pd.DataFrame({
        "sale_id": [1, 1, 2, 3, 4, 4, 5, 5],
        "category": ["platos", "bebidas", "platos", "postres", "postres", "bebidas", "platos", "postres"],
        "name": ["Plato", "Gaseosa", "Plato", "Postre", "Postre", "Jugo", "Plato", "Postre"]})
    rep = SimpleNamespace(datos={})
    filas, total = a06.sin_bebida(items, rep)
    por_cat = {f["categoria"]: f for f in filas}
    # platos en los pedidos {1, 2, 5}: sin bebida {2, 5} ; postres en {3, 4, 5}: sin bebida {3, 5}
    assert (por_cat["platos"]["pedidos"], por_cat["platos"]["sin_bebida"]) == (3, 2)
    assert por_cat["postres"]["pct_sin_bebida"] == pytest.approx(2 / 3)
    # pedidos con algun plato o postre: {1, 2, 3, 4, 5}; sin bebida: {2, 3, 5}
    assert total == {"pedidos_con_plato": 5, "sin_bebida": 3, "pct_sin_bebida": pytest.approx(0.6)}
    assert "bebidas" not in por_cat


def test_reglas_apriori_de_la_bd_sintetica_encuentran_las_parejas_plantadas(corrida):
    j = leer_json(corrida["a"], "a06_venta_cruzada")
    reglas = {(r["antecedent"], r["consequent"]) for r in j["apriori_producto"]["top"]}
    assert ("Gaseosa", "Hamburguesa") in reglas or ("Hamburguesa", "Gaseosa") in reglas
    assert j["apriori_producto"]["n_reglas"] >= 4 and j["apriori_producto"]["lift_maximo"] > 2
    assert all(r["lift"] > 1.0 and r["confidence"] >= 0.15 for r in j["apriori_producto"]["top"])
