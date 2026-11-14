"""Contrato HTTP de importación real con datos sintéticos y BD temporal."""
import json
from types import SimpleNamespace

import pytest

from app.adapters.inbound.api.v1 import etl as etl_api


@pytest.fixture
def origen_sintetico(tmp_path):
    pedidos = [{"id": 876501, "fecha": "2026-04-01T12:00:00-05:00", "tipo": "llevar",
                "estado": "pagado", "metodo_pago": "efectivo", "total": 5000,
                "productos": [{"id": 601, "nombre": "Producto demo", "qty": 1, "precio": 5000}]}]
    productos = [{"id": 601, "nombre": "Producto demo", "precio": 5000, "costo": 2000,
                  "categoria": "QA", "activo": True}]
    pedidos_path = tmp_path / "pedidos_24meses.json"
    pedidos_path.write_text(json.dumps(pedidos), encoding="utf-8")
    (tmp_path / "productos.json").write_text(json.dumps(productos), encoding="utf-8")
    return pedidos_path


def test_importador_exige_auth(client):
    assert client.get("/api/v1/etl/source-status").status_code == 401
    assert client.post("/api/v1/etl/import").status_code == 401


def test_status_y_import_idempotente(client, auth, monkeypatch, origen_sintetico):
    monkeypatch.setattr(etl_api, "get_settings", lambda: SimpleNamespace(
        red_rooster_json=str(origen_sintetico), data_source_mode="red_rooster", red_rooster_poll_seconds=60))
    monkeypatch.setattr(etl_api, "obtener_clave_privacidad", lambda: "clave-sintetica-qa-0123456789")

    estado = client.get("/api/v1/etl/source-status", headers=auth)
    assert estado.status_code == 200
    assert estado.json()["exists"] is True
    assert estado.json()["source_orders"] == 1
    assert estado.json()["mode"] == "red_rooster"

    primera = client.post("/api/v1/etl/import", headers=auth)
    assert primera.status_code == 200, primera.text
    assert primera.json()["status"] == "SUCCESS"
    assert primera.json()["inserted"] == 1

    segunda = client.post("/api/v1/etl/import", headers=auth)
    assert segunda.status_code == 200
    assert segunda.json()["status"] == "SIN_CAMBIOS"

    estado_final = client.get("/api/v1/etl/source-status", headers=auth)
    assert estado_final.json()["loaded_orders"] == 1
    assert estado_final.json()["last_status"] == "SUCCESS"


def test_import_fallido_se_registra_en_estado(client, auth, monkeypatch, origen_sintetico):
    monkeypatch.setattr(etl_api, "get_settings", lambda: SimpleNamespace(
        red_rooster_json=str(origen_sintetico), data_source_mode="red_rooster", red_rooster_poll_seconds=60))
    monkeypatch.setattr(etl_api, "obtener_clave_privacidad", lambda: "clave-sintetica-qa-0123456789")
    origen_sintetico.write_text("{json incompleto", encoding="utf-8")

    respuesta = client.post("/api/v1/etl/import", headers=auth)
    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "FAILED"
    estado = client.get("/api/v1/etl/source-status", headers=auth)
    assert estado.json()["last_status"] == "FAILED"
    assert estado.json()["last_error"]


# --- GET /etl/quality -------------------------------------------------------------------------
REGLAS_CALIDAD = ["fechas_con_zona_utc", "fechas_con_zona_bogota", "pedidos_sin_canal", "mesero_texto_libre",
                  "productos_costo_cero", "total_no_cuadra", "pedidos_cancelados", "pago_sin_dato",
                  "lineas_omitidas"]
CONTEOS = ["pedidos", "detalle", "productos", "clientes", "dim_fecha", "ventas_diarias"]


def test_quality_exige_token(client):
    assert client.get("/api/v1/etl/quality").status_code == 401
    assert client.get("/api/v1/etl/quality", headers={"Authorization": "Bearer invalido"}).status_code == 401


def test_quality_sin_importar_devuelve_reglas_vacias_y_conteos_en_cero(client, auth):
    r = client.get("/api/v1/etl/quality", headers=auth)
    assert r.status_code == 200
    assert r.json() == {"reglas": [], "conteos": {k: 0 for k in CONTEOS}}


def test_quality_con_token_devuelve_reglas_y_seis_conteos(client, auth, monkeypatch, origen_sintetico):
    monkeypatch.setattr(etl_api, "get_settings", lambda: SimpleNamespace(
        red_rooster_json=str(origen_sintetico), data_source_mode="red_rooster", red_rooster_poll_seconds=60))
    monkeypatch.setattr(etl_api, "obtener_clave_privacidad", lambda: "clave-sintetica-qa-0123456789")
    assert client.post("/api/v1/etl/import", headers=auth).json()["status"] == "SUCCESS"

    r = client.get("/api/v1/etl/quality", headers=auth)
    assert r.status_code == 200
    cuerpo = r.json()
    assert set(cuerpo) == {"reglas", "conteos"}
    assert [x["regla"] for x in cuerpo["reglas"]] == REGLAS_CALIDAD
    assert all(set(x) == {"regla", "descripcion", "registros_afectados", "tratamiento"} for x in cuerpo["reglas"])
    # origen: 1 pedido llevar, pagado, efectivo, hora -05:00, total 5000 = 1 x 5000, 1 producto sin mesero
    por_regla = {x["regla"]: x["registros_afectados"] for x in cuerpo["reglas"]}
    assert por_regla == {"fechas_con_zona_utc": 0, "fechas_con_zona_bogota": 1, "pedidos_sin_canal": 0,
                         "mesero_texto_libre": 0, "productos_costo_cero": 0, "total_no_cuadra": 0,
                         "pedidos_cancelados": 0, "pago_sin_dato": 0, "lineas_omitidas": 0}
    # sin teléfono ni dirección: 0 clientes; 1 pedido, 1 línea, 1 producto, 1 día
    assert cuerpo["conteos"] == {"pedidos": 1, "detalle": 1, "productos": 1, "clientes": 0,
                                 "dim_fecha": 1, "ventas_diarias": 1}
