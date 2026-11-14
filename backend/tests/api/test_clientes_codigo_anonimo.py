"""Contrato HTTP de clientes con `codigo_anonimo` (seudónimo del ETL, no PII). Datos sintéticos y BD temporal."""
import pytest

from app.adapters.outbound.persistence import models as m

P = "/api/v1"


@pytest.fixture
def cliente_con_codigo(session_factory, cipher):
    """Cliente sintético como lo deja el ETL: con código anónimo y PII cifrada."""
    with session_factory() as s:
        fila = m.CustomerModel(first_name="Ana", last_name="Prueba", codigo_anonimo="C001",
                               encrypted_email=cipher.cifrar("ana.prueba@example.com"),
                               encrypted_phone=cipher.cifrar("3001234567"))
        s.add(fila)
        s.commit()
        return fila.id


def _codigo_en_bd(session_factory, cid):
    with session_factory() as s:
        return s.get(m.CustomerModel, cid).codigo_anonimo


# ---- GET
def test_get_detalle_devuelve_codigo_sin_enmascarar_ni_revelar(client, auth, cliente_con_codigo):
    cid = cliente_con_codigo
    # Sin revelar: el código sigue completo; email/teléfono enmascarados.
    g = client.get(f"{P}/customers/{cid}", headers=auth).json()
    assert g["codigo_anonimo"] == "C001"
    assert g["email"] == "a***@example.com" and g["phone"] == "*******567" and g["revelado"] is False
    # Revelando: el código es el mismo; la PII se ve completa.
    r = client.get(f"{P}/customers/{cid}?revelar=true", headers=auth).json()
    assert r["codigo_anonimo"] == "C001"
    assert r["email"] == "ana.prueba@example.com" and r["phone"] == "3001234567" and r["revelado"] is True


def test_get_lista_devuelve_codigo_en_ambos_modos(client, auth, cliente_con_codigo):
    sin = client.get(f"{P}/customers", headers=auth).json()
    assert len(sin) == 1
    assert sin[0]["codigo_anonimo"] == "C001"
    assert sin[0]["email"] == "a***@example.com" and sin[0]["revelado"] is False
    assert "ana.prueba" not in client.get(f"{P}/customers", headers=auth).text

    con = client.get(f"{P}/customers?revelar=true", headers=auth).json()
    assert con[0]["codigo_anonimo"] == "C001"
    assert con[0]["email"] == "ana.prueba@example.com" and con[0]["revelado"] is True


def test_cliente_manual_sin_codigo_lo_devuelve_null(client, auth, session_factory):
    with session_factory() as s:
        s.add(m.CustomerModel(first_name="Beto", last_name="Manual"))
        s.commit()
    lista = client.get(f"{P}/customers", headers=auth).json()
    assert len(lista) == 1 and "codigo_anonimo" in lista[0] and lista[0]["codigo_anonimo"] is None


def test_lista_mezcla_clientes_con_y_sin_codigo(client, auth, cliente_con_codigo):
    sin_codigo = client.post(f"{P}/customers", headers=auth, json={"first_name": "Caro", "last_name": "Nueva"}).json()
    por_id = {c["id"]: c["codigo_anonimo"] for c in client.get(f"{P}/customers", headers=auth).json()}
    assert por_id == {cliente_con_codigo: "C001", sin_codigo["id"]: None}


# ---- POST
def test_post_crea_cliente_con_codigo_null(client, auth):
    r = client.post(f"{P}/customers", headers=auth, json={"first_name": "Ana", "last_name": "Perez"})
    assert r.status_code == 201
    assert "codigo_anonimo" in r.json() and r.json()["codigo_anonimo"] is None


def test_post_ignora_codigo_anonimo_del_cuerpo(client, auth, session_factory):
    r = client.post(f"{P}/customers", headers=auth, json={
        "first_name": "Ana", "last_name": "Perez", "codigo_anonimo": "C999"})
    assert r.status_code == 201, r.text
    assert r.json()["codigo_anonimo"] is None
    cid = r.json()["id"]
    assert client.get(f"{P}/customers/{cid}", headers=auth).json()["codigo_anonimo"] is None
    assert _codigo_en_bd(session_factory, cid) is None


# ---- PUT
def test_put_conserva_el_codigo(client, auth, cliente_con_codigo, session_factory):
    cid = cliente_con_codigo
    r = client.put(f"{P}/customers/{cid}", headers=auth, json={"first_name": "Zoe", "email": "zoe@example.com"})
    assert r.status_code == 200, r.text
    assert r.json()["codigo_anonimo"] == "C001" and r.json()["first_name"] == "Zoe"
    assert r.json()["email"] == "z***@example.com" and r.json()["revelado"] is False
    assert client.get(f"{P}/customers/{cid}", headers=auth).json()["codigo_anonimo"] == "C001"
    assert _codigo_en_bd(session_factory, cid) == "C001"


def test_put_no_permite_cambiar_el_codigo_desde_el_cuerpo(client, auth, cliente_con_codigo, session_factory):
    cid = cliente_con_codigo
    r = client.put(f"{P}/customers/{cid}", headers=auth, json={"phone": "3109998877", "codigo_anonimo": "C999"})
    assert r.status_code == 200, r.text
    assert r.json()["codigo_anonimo"] == "C001"
    assert _codigo_en_bd(session_factory, cid) == "C001"
    # El resto del cambio sí se aplicó (PUT válido, solo el campo extra se ignora).
    assert client.get(f"{P}/customers/{cid}?revelar=true", headers=auth).json()["phone"] == "3109998877"


def test_put_sobre_cliente_sin_codigo_no_se_lo_asigna(client, auth, session_factory):
    cid = client.post(f"{P}/customers", headers=auth, json={"first_name": "A", "last_name": "B"}).json()["id"]
    r = client.put(f"{P}/customers/{cid}", headers=auth, json={"first_name": "Z", "codigo_anonimo": "C007"})
    assert r.status_code == 200
    assert r.json()["codigo_anonimo"] is None
    assert _codigo_en_bd(session_factory, cid) is None
