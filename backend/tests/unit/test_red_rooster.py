"""Pruebas del ETL real con fixtures sintéticos anonimizados (nunca datos de clientes reales)."""
import json
from datetime import datetime

import pytest
from sqlalchemy import func, select

from app.adapters.outbound.persistence import models as m
from app.etl.red_rooster import importar


CLAVE_QA = "clave-de-pruebas-no-reutilizable-0123456789"


@pytest.fixture
def json_rooster(tmp_path):
    """Forma representativa del origen, con contactos inventados para verificar minimización."""
    pedidos = [
        {
            "id": 987001,
            "fecha": "2026-03-23T18:49:49-05:00",
            "tipo": "domicilio",
            "estado": "pagado",
            "metodo_pago": "nequi",
            "total": 31000,
            "cliente": "CLIENTE SINTETICO QA",
            "telefono": "3000000000",
            "direccion": "DIRECCION INVENTADA QA",
            "nota": "NOTA PRIVADA QA",
            "productos": [
                {"id": 501, "nombre": "Producto ficticio uno", "qty": 2, "precio": 10000},
                {"id": 502, "nombre": "Producto ficticio dos", "qty": 1, "precio": 11000},
            ],
        },
        {
            "id": 987002,
            "fecha": "2026-03-24T12:00:00-05:00",
            "tipo": "mesa",
            "estado": "cancelado",
            "metodo_pago": "efectivo",
            "total": 10000,
            "productos": [{"id": 501, "nombre": "Producto ficticio uno", "qty": 1, "precio": 10000}],
        },
    ]
    productos = [
        {"id": 501, "nombre": "Producto ficticio uno", "precio": 10000, "costo": 4000,
         "categoria": "Pruebas", "activo": True},
        {"id": 502, "nombre": "Producto ficticio dos", "precio": 11000, "costo": 5000,
         "categoria": "Pruebas", "activo": True},
    ]
    pedidos_path = tmp_path / "pedidos_24meses.json"
    productos_path = tmp_path / "productos.json"

    def escribir():
        pedidos_path.write_text(json.dumps(pedidos, ensure_ascii=False), encoding="utf-8")
        productos_path.write_text(json.dumps(productos, ensure_ascii=False), encoding="utf-8")

    escribir()
    return pedidos_path, pedidos, productos, escribir


def test_carga_inicial_normaliza_fecha_y_omite_pii(db_session, json_rooster):
    ruta, pedidos, _, _ = json_rooster
    resultado = importar(db_session, ruta, CLAVE_QA)

    assert resultado["inserted"] == 2
    assert resultado["updated"] == 0
    venta = db_session.get(m.SaleModel, 987001)
    assert venta is not None and venta.status == "COMPLETED"
    assert venta.created_at == datetime(2026, 3, 23, 18, 49, 49)
    assert venta.customer_id is not None
    assert len(venta.items) == 2

    cliente = db_session.get(m.CustomerModel, venta.customer_id)
    assert cliente.first_name == "Cliente" and cliente.last_name == "Red Rooster"
    assert cliente.source_key and "3000000000" not in cliente.source_key
    # Ninguna cadena personal del fixture debe quedar en las columnas de cliente.
    columnas_cliente = " ".join(str(getattr(cliente, c.name, "")) for c in m.CustomerModel.__table__.columns)
    for dato in ("CLIENTE SINTETICO QA", "3000000000", "DIRECCION INVENTADA QA", "NOTA PRIVADA QA"):
        assert dato not in columnas_cliente

    cancelada = db_session.get(m.SaleModel, 987002)
    assert cancelada.status == "CANCELLED"


def test_reimportar_es_idempotente_y_actualiza_estado_y_lineas(db_session, json_rooster):
    ruta, pedidos, _, escribir = json_rooster
    inicial = importar(db_session, ruta, CLAVE_QA)
    assert inicial["inserted"] == 2

    repetida = importar(db_session, ruta, CLAVE_QA, force=True)
    assert repetida["inserted"] == 0
    assert repetida["updated"] == 0
    assert repetida["unchanged"] == 2
    n_lineas = db_session.scalar(select(func.count()).select_from(m.SaleItemModel)
                                 .where(m.SaleItemModel.sale_id == 987001))
    assert n_lineas == 2

    pedidos[1]["estado"] = "pagado"
    pedidos[1]["productos"] = [{"id": 502, "nombre": "Producto ficticio dos", "qty": 3, "precio": 11000}]
    escribir()
    actualizada = importar(db_session, ruta, CLAVE_QA, force=True)
    assert actualizada["updated"] == 1
    sale = db_session.get(m.SaleModel, 987002)
    assert sale.status == "COMPLETED"
    assert len(sale.items) == 1
    assert sale.items[0].product_id == 502 and sale.items[0].quantity == 3


def test_mismo_cliente_tiene_hash_estable_y_otra_clave_lo_separa(db_session, json_rooster):
    ruta, _, _, _ = json_rooster
    importar(db_session, ruta, CLAVE_QA)
    original = db_session.get(m.SaleModel, 987001).customer_id
    importar(db_session, ruta, "otra-clave-privacidad-qa-0123456789", force=True)
    nuevo = db_session.get(m.SaleModel, 987001).customer_id
    assert nuevo != original


def test_json_invalido_no_crea_catalogo_ni_ventas(db_session, json_rooster):
    ruta, _, _, _ = json_rooster
    ruta.write_text("{json truncado", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        importar(db_session, ruta, CLAVE_QA)
    assert db_session.query(m.ProductModel).count() == 0
    assert db_session.query(m.SaleModel).count() == 0


def test_clave_de_privacidad_obligatoria(db_session, json_rooster):
    ruta, _, _, _ = json_rooster
    with pytest.raises(ValueError, match="DATA_PRIVACY_KEY"):
        importar(db_session, ruta, "short")


# ---------------------------------------------------------------------------------------------
# Huella de cliente, privacidad, códigos anónimos, canal e incremental (caso: cambio de analítica)
# ---------------------------------------------------------------------------------------------
from sqlalchemy import inspect as sa_inspect, text  # noqa: E402

from app.etl.red_rooster import _huella_cliente, canal_de  # noqa: E402
from tests.unit.rr_helpers import escribir_origen, pedido  # noqa: E402

F = "2026-03-10T12:00:00-05:00"


def _h(**campos):
    return _huella_cliente(campos, CLAVE_QA)


def test_huella_telefono_con_y_sin_prefijo_pais_es_el_mismo_cliente():
    base = _h(telefono="3005550142")
    assert base is not None and len(base) == 64
    assert _h(telefono="+57 300 555 0142") == base
    assert _h(telefono="573005550142") == base
    assert _h(telefono="+57 (300) 555-0142") == base


def test_huella_solo_quita_57_si_son_12_digitos():
    # 10 dígitos que empiezan por 57 y 12 dígitos que no empiezan por 57 se dejan intactos.
    assert _h(telefono="5712345678") != _h(telefono="12345678")
    assert _h(telefono="123456789012") != _h(telefono="3456789012")
    assert _h(telefono="3005550142") != _h(telefono="3005550143")


def test_huella_telefono_tiene_prioridad_sobre_la_direccion():
    con_tel = _h(tipo="domicilio", telefono="3001112233", direccion="Calle 1 # 2-3")
    mismo_tel_otra_dir = _h(tipo="domicilio", telefono="3001112233", direccion="Carrera 9 # 8-7")
    solo_direccion = _h(tipo="domicilio", direccion="Calle 1 # 2-3")
    assert con_tel == mismo_tel_otra_dir
    assert con_tel != solo_direccion


def test_huella_domicilio_sin_telefono_usa_direccion_normalizada():
    a = _h(tipo="domicilio", direccion="CALLE 10  #5-20 ")
    b = _h(tipo="domicilio", direccion="calle 10 #5-20")
    assert a is not None and a == b
    assert a != _h(tipo="domicilio", direccion="calle 11 #5-20")
    # un teléfono sin dígitos no cuenta como teléfono: cae a la dirección
    assert _h(tipo="domicilio", telefono="sin numero", direccion="calle 10 #5-20") == b


def test_huella_sin_datos_identificables_no_crea_cliente():
    assert _h() is None
    assert _h(tipo="mesa", direccion="Calle 1 # 2-3") is None
    assert _h(tipo="llevar", direccion="Calle 1 # 2-3", telefono="") is None
    assert _h(tipo="domicilio") is None
    assert _h(tipo="domicilio", direccion="   ") is None
    assert _h(tipo=None, direccion="Calle 1 # 2-3") is None


def test_huella_con_otra_clave_es_distinta():
    assert _huella_cliente({"telefono": "3005550142"}, CLAVE_QA) != \
        _huella_cliente({"telefono": "3005550142"}, "otra-clave-privacidad-qa-0123456789")


def test_canal_de_los_cuatro_valores():
    assert canal_de({"tipo": "mesa"}) == "mesa"
    assert canal_de({"tipo": "llevar"}) == "llevar"
    assert canal_de({"tipo": "domicilio"}) == "domicilio"
    assert canal_de({"tipo": "MESA"}) == "mesa"
    for valor in (None, "", "otro", "barra"):
        assert canal_de({"tipo": valor}) == "sin_dato"
    assert canal_de({}) == "sin_dato"


def test_importar_clientes_segun_huella_y_canal(db_session, tmp_path):
    pedidos = [
        pedido(1, F, tipo="llevar", telefono="+57 300 555 0142"),
        pedido(2, F, tipo="llevar", telefono="3005550142"),
        pedido(3, F, tipo="domicilio", direccion="CALLE 10  #5-20 "),
        pedido(4, F, tipo="domicilio", direccion="calle 10 #5-20"),
        pedido(5, F, tipo="domicilio", direccion="otra calle 99"),
        pedido(6, F, tipo="mesa", direccion="Calle 10 #5-20"),
        pedido(7, F, tipo="llevar"),
        pedido(8, F, tipo=None, telefono="3009998877"),
        pedido(9, F, tipo=None),
    ]
    importar(db_session, escribir_origen(tmp_path, pedidos), CLAVE_QA)
    cid = {i: db_session.get(m.SaleModel, i).customer_id for i in range(1, 10)}
    canal = {i: db_session.get(m.SaleModel, i).canal for i in range(1, 10)}

    assert cid[1] is not None and cid[1] == cid[2]
    assert cid[3] is not None and cid[3] == cid[4]
    assert cid[5] is not None and cid[5] not in (cid[1], cid[3])
    assert cid[6] is None and cid[7] is None and cid[9] is None
    assert cid[8] is not None and cid[8] not in (cid[1], cid[3], cid[5])
    assert db_session.scalar(select(func.count(m.CustomerModel.id))) == 4
    assert canal == {1: "llevar", 2: "llevar", 3: "domicilio", 4: "domicilio", 5: "domicilio",
                     6: "mesa", 7: "llevar", 8: "sin_dato", 9: "sin_dato"}


def test_huella_domicilio_con_tipo_en_mayusculas_o_mixto_usa_la_direccion():
    base = _h(tipo="domicilio", direccion="calle 10 #5-20")
    assert base is not None
    assert _h(tipo="DOMICILIO", direccion="calle 10 #5-20") == base
    assert _h(tipo="Domicilio", direccion="calle 10 #5-20") == base
    # el tipo en mayúsculas sigue sin identificar a quien no es domicilio
    assert _h(tipo="MESA", direccion="calle 10 #5-20") is None


def test_importar_domicilio_con_tipo_en_mayusculas_sin_telefono_recibe_cliente_y_canal(db_session, tmp_path):
    pedidos = [
        pedido(1, F, tipo="DOMICILIO", direccion="Carrera 7 #45-12"),
        pedido(2, F, tipo="Domicilio", direccion="CARRERA 7  #45-12 "),
        pedido(3, F, tipo="DOMICILIO", direccion="carrera 7 #45-12"),
        pedido(4, F, tipo="Domicilio", direccion="Avenida 30 #1-1"),
        pedido(5, F, tipo="MESA", direccion="Carrera 7 #45-12"),
    ]
    importar(db_session, escribir_origen(tmp_path, pedidos), CLAVE_QA)
    ventas = {i: db_session.get(m.SaleModel, i) for i in range(1, 6)}

    # mismo domicilio en distinta capitalización/espaciado -> mismo cliente
    assert ventas[1].customer_id is not None
    assert ventas[1].customer_id == ventas[2].customer_id == ventas[3].customer_id
    # otra dirección -> otro cliente
    assert ventas[4].customer_id is not None and ventas[4].customer_id != ventas[1].customer_id
    # una mesa con dirección no recibe cliente
    assert ventas[5].customer_id is None
    assert db_session.scalar(select(func.count(m.CustomerModel.id))) == 2
    assert [ventas[i].canal for i in range(1, 6)] == ["domicilio", "domicilio", "domicilio", "domicilio", "mesa"]


def test_privacidad_ningun_dato_personal_en_ninguna_tabla(db_session, db_engine, tmp_path):
    sensibles = ["NOMBRE SINTETICO ZETA", "3115550123", "CALLE FALSA 123 QA", "NOTA SECRETA QA",
                 "10.99.88.77", "MESERO QA UNO", "calle falsa 123 qa"]
    pedidos = [
        pedido(1, F, tipo="domicilio", cliente="NOMBRE SINTETICO ZETA", telefono="+57 311 555 0123",
               direccion="CALLE FALSA 123 QA", nota="NOTA SECRETA QA", ip="10.99.88.77", mesero="MESERO QA UNO"),
        pedido(2, F, tipo="domicilio", cliente="NOMBRE SINTETICO ZETA", direccion="calle falsa 123 qa",
               nota="NOTA SECRETA QA", ip="10.99.88.77"),
    ]
    importar(db_session, escribir_origen(tmp_path, pedidos), CLAVE_QA)
    assert db_session.scalar(select(func.count(m.CustomerModel.id))) == 2  # hay clientes: la prueba no es vacía

    con = db_session.connection()
    tablas = sa_inspect(db_engine).get_table_names()
    assert {"customers", "sales", "dim_fecha", "ventas_diarias", "calidad_datos", "source_import_runs"} <= set(tablas)
    for tabla in tablas:
        for fila in con.execute(text(f'SELECT * FROM "{tabla}"')).fetchall():
            texto = " | ".join(str(v) for v in fila).lower()
            for dato in sensibles:
                assert dato.lower() not in texto, f"{dato!r} aparece en la tabla {tabla}"


def _mapa_codigos(db_session):
    return {c.source_key: c.codigo_anonimo for c in db_session.scalars(select(m.CustomerModel))}


def test_codigos_por_orden_de_primera_compra_aunque_el_json_venga_desordenado(db_session, tmp_path):
    # Primera compra real: T3 el 03-02, T2 el 03-05, T1 el 03-10  =>  C001=T3, C002=T2, C003=T1
    pedidos = [
        pedido(1, "2026-03-20T10:00:00-05:00", tipo="llevar", telefono="3000000003"),
        pedido(2, "2026-03-10T10:00:00-05:00", tipo="llevar", telefono="3000000001"),
        pedido(3, "2026-03-05T10:00:00-05:00", tipo="llevar", telefono="3000000002"),
        pedido(4, "2026-03-02T10:00:00-05:00", tipo="llevar", telefono="3000000003"),
    ]
    importar(db_session, escribir_origen(tmp_path, pedidos), CLAVE_QA)
    por_codigo = {c.codigo_anonimo: c for c in db_session.scalars(select(m.CustomerModel))}
    assert sorted(por_codigo) == ["C001", "C002", "C003"]
    assert por_codigo["C001"].created_at == datetime(2026, 3, 2, 10)
    assert por_codigo["C002"].created_at == datetime(2026, 3, 5, 10)
    assert por_codigo["C003"].created_at == datetime(2026, 3, 10, 10)
    # el cliente C001 es quien compró los pedidos 1 y 4
    assert db_session.get(m.SaleModel, 1).customer_id == db_session.get(m.SaleModel, 4).customer_id == por_codigo["C001"].id


def test_codigos_estables_entre_corridas_y_nuevos_continuan_la_numeracion(db_session, tmp_path):
    pedidos = [pedido(1, "2026-03-05T10:00:00-05:00", tipo="llevar", telefono="3000000001"),
               pedido(2, "2026-03-06T10:00:00-05:00", tipo="llevar", telefono="3000000002")]
    ruta = escribir_origen(tmp_path, pedidos)
    importar(db_session, ruta, CLAVE_QA)
    antes = _mapa_codigos(db_session)
    assert sorted(antes.values()) == ["C001", "C002"]

    importar(db_session, ruta, CLAVE_QA, force=True)
    assert _mapa_codigos(db_session) == antes

    # Dos clientes nuevos, uno con compra ANTERIOR a todos los existentes: no reordena, continúa en C003.
    pedidos += [pedido(3, "2026-04-02T10:00:00-05:00", tipo="llevar", telefono="3000000010"),
                pedido(4, "2026-04-01T10:00:00-05:00", tipo="llevar", telefono="3000000011"),
                pedido(5, "2026-01-01T10:00:00-05:00", tipo="llevar", telefono="3000000012")]
    escribir_origen(tmp_path, pedidos)
    importar(db_session, ruta, CLAVE_QA, force=True)
    despues = _mapa_codigos(db_session)
    assert all(despues[k] == v for k, v in antes.items())           # los existentes no cambian
    nuevos = {k: v for k, v in despues.items() if k not in antes}
    # orden de primera compra entre los nuevos: 01-01 -> C003, 04-01 -> C004, 04-02 -> C005
    por_fecha = sorted(db_session.scalars(select(m.CustomerModel).where(m.CustomerModel.source_key.in_(nuevos))),
                       key=lambda c: c.created_at)
    assert [c.codigo_anonimo for c in por_fecha] == ["C003", "C004", "C005"]
    assert len(set(despues.values())) == 5


def test_cambio_de_tipo_en_origen_cuenta_como_actualizacion_y_cambia_el_canal(db_session, tmp_path):
    pedidos = [pedido(1, F, tipo="mesa"), pedido(2, F, tipo="llevar")]
    ruta = escribir_origen(tmp_path, pedidos)
    importar(db_session, ruta, CLAVE_QA)
    assert db_session.get(m.SaleModel, 1).canal == "mesa"

    pedidos[0]["tipo"] = "domicilio"
    escribir_origen(tmp_path, pedidos)
    r = importar(db_session, ruta, CLAVE_QA, force=True)
    assert (r["inserted"], r["updated"], r["unchanged"]) == (0, 1, 1)
    assert db_session.get(m.SaleModel, 1).canal == "domicilio"
    assert db_session.get(m.SaleModel, 2).canal == "llevar"


def test_segunda_corrida_sin_cambios_e_incremental_inserta_uno_y_actualiza_uno(db_session, tmp_path):
    pedidos = [pedido(1, "2026-03-10T10:00:00-05:00"), pedido(2, "2026-03-11T10:00:00-05:00"),
               pedido(3, "2026-03-12T10:00:00-05:00")]
    ruta = escribir_origen(tmp_path, pedidos)
    assert importar(db_session, ruta, CLAVE_QA)["inserted"] == 3
    repetida = importar(db_session, ruta, CLAVE_QA)
    assert repetida["status"] == "SIN_CAMBIOS"
    assert (repetida["inserted"], repetida["updated"]) == (0, 0)

    pedidos[1]["estado"] = "cancelado"
    pedidos.append(pedido(4, "2026-03-13T10:00:00-05:00"))
    escribir_origen(tmp_path, pedidos)
    r = importar(db_session, ruta, CLAVE_QA)
    assert r["status"] == "SUCCESS"
    assert (r["inserted"], r["updated"], r["unchanged"]) == (1, 1, 2)
    assert db_session.get(m.SaleModel, 2).status == "CANCELLED"
    assert db_session.scalar(select(func.count(m.SaleModel.id))) == 4
