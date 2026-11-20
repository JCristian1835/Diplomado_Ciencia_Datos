"""Busqueda de clientes por codigo anonimo (?q=C001) y `codigo_anonimo` en /analytics/segments. BD temporal, datos sinteticos."""
import pytest

from app.adapters.outbound.persistence import models as m

P = "/api/v1"


@pytest.fixture
def clientes(session_factory, cipher):
    """Ana (C001), Beto (C002), Carla (C010) y Zoe (manual, sin codigo)."""
    ids = {}
    with session_factory() as s:
        for clave, nombre, apellido, codigo in (("ana", "Ana", "Prueba", "C001"), ("beto", "Beto", "Otro", "C002"),
                                                 ("carla", "Carla", "Dos", "C010"), ("zoe", "Zoe", "Manual", None)):
            fila = m.CustomerModel(first_name=nombre, last_name=apellido, codigo_anonimo=codigo,
                                   encrypted_email=cipher.cifrar(f"{clave}@example.com"))
            s.add(fila)
            s.flush()
            ids[clave] = fila.id
        s.commit()
    return ids


def _buscar(client, auth, q):
    r = client.get(f"{P}/customers", params={"q": q}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


# ---- GET /customers?q=
def test_busqueda_por_codigo_exacto(client, auth, clientes):
    r = _buscar(client, auth, "C001")
    assert [c["id"] for c in r] == [clientes["ana"]] and r[0]["codigo_anonimo"] == "C001"


def test_busqueda_por_codigo_no_distingue_mayusculas(client, auth, clientes):
    assert [c["codigo_anonimo"] for c in _buscar(client, auth, "c002")] == ["C002"]


def test_busqueda_por_prefijo_de_codigo_devuelve_todos_los_que_coinciden(client, auth, clientes):
    # "C00" -> C001 y C002 (no C010 ni el cliente sin codigo)
    assert [c["codigo_anonimo"] for c in _buscar(client, auth, "C00")] == ["C001", "C002"]
    assert [c["codigo_anonimo"] for c in _buscar(client, auth, "C0")] == ["C001", "C002", "C010"]


def test_busqueda_por_codigo_inexistente_devuelve_lista_vacia(client, auth, clientes):
    assert _buscar(client, auth, "C999") == []


def test_busqueda_por_nombre_y_apellido_sigue_funcionando(client, auth, clientes):
    assert [c["first_name"] for c in _buscar(client, auth, "beto")] == ["Beto"]
    assert [c["last_name"] for c in _buscar(client, auth, "manual")] == ["Manual"]
    assert [c["first_name"] for c in _buscar(client, auth, "Prueba")] == ["Ana"]


def test_busqueda_no_confunde_cliente_sin_codigo(client, auth, clientes):
    # Zoe no tiene codigo: ni "None" ni "null" la encuentran
    assert _buscar(client, auth, "None") == [] and _buscar(client, auth, "null") == []


def test_busqueda_por_codigo_no_revela_pii(client, auth, clientes):
    r = client.get(f"{P}/customers", params={"q": "C001"}, headers=auth)
    assert "ana@example.com" not in r.text and r.json()[0]["email"] == "a***@example.com"
    assert r.json()[0]["revelado"] is False


def test_busqueda_por_codigo_con_revelar(client, auth, clientes):
    r = client.get(f"{P}/customers", params={"q": "C002", "revelar": "true"}, headers=auth).json()
    assert len(r) == 1 and r[0]["email"] == "beto@example.com" and r[0]["codigo_anonimo"] == "C002"


def test_busqueda_sin_q_devuelve_todos(client, auth, clientes):
    assert len(client.get(f"{P}/customers", headers=auth).json()) == 4


def test_busqueda_exige_token(client, clientes):
    assert client.get(f"{P}/customers", params={"q": "C001"}).status_code == 401


# ---- GET /analytics/segments
@pytest.fixture
def segmentos(session_factory, clientes):
    with session_factory() as s:
        for clave, cluster, etiqueta, rec, fre, mon in (("ana", 0, "Campeones", 3, 10, 500000.0),
                                                        ("beto", 0, "Campeones", 5, 8, 400000.0),
                                                        ("zoe", 1, "Ocasionales", 90, 1, 20000.0)):
            s.add(m.CustomerSegmentModel(customer_id=clientes[clave], recency=rec, frequency=fre, monetary=mon,
                                         cluster=cluster, segment_label=etiqueta))
        s.commit()
    return clientes


def test_segments_incluye_codigo_anonimo_por_cliente(client, auth, segmentos):
    r = client.get(f"{P}/analytics/segments", headers=auth)
    assert r.status_code == 200, r.text
    por_id = {c["customer_id"]: c for c in r.json()["clientes"]}
    assert set(por_id) == {segmentos["ana"], segmentos["beto"], segmentos["zoe"]}
    assert por_id[segmentos["ana"]]["codigo_anonimo"] == "C001"
    assert por_id[segmentos["beto"]]["codigo_anonimo"] == "C002"
    assert "codigo_anonimo" in por_id[segmentos["zoe"]] and por_id[segmentos["zoe"]]["codigo_anonimo"] is None


def test_segments_conserva_el_resto_de_campos_y_el_resumen(client, auth, segmentos):
    j = client.get(f"{P}/analytics/segments", headers=auth).json()
    ana = next(c for c in j["clientes"] if c["customer_id"] == segmentos["ana"])
    assert (ana["first_name"], ana["last_name"], ana["recency"], ana["frequency"], ana["monetary"],
            ana["cluster"], ana["segment_label"]) == ("Ana", "Prueba", 3, 10, 500000.0, 0, "Campeones")
    por_cluster = {r["cluster"]: r for r in j["resumen"]}
    assert por_cluster[0]["n_clientes"] == 2 and por_cluster[0]["segmento"] == "Campeones"
    assert por_cluster[0]["monetario_total"] == 900000.0 and por_cluster[1]["n_clientes"] == 1


def test_segments_no_expone_email_ni_telefono(client, auth, segmentos):
    r = client.get(f"{P}/analytics/segments", headers=auth)
    assert "@" not in r.text and "encrypted" not in r.text


def test_segments_vacio_sigue_devolviendo_listas(client, auth):
    assert client.get(f"{P}/analytics/segments", headers=auth).json() == {"resumen": [], "clientes": []}


def test_segments_exige_token(client):
    assert client.get(f"{P}/analytics/segments").status_code == 401
