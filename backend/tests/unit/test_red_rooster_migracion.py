"""Migración aditiva del lifespan: una BD vieja gana las columnas nuevas sin perder registros."""
import asyncio
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import sessionmaker

from app import main
from app.adapters.outbound.persistence import models as m
from app.core.db import crear_motor


def _correr_lifespan():
    async def _go():
        async with main.lifespan(main.app):
            pass
    asyncio.run(_go())


def test_lifespan_agrega_columnas_nuevas_sin_perder_datos(tmp_path, monkeypatch):
    motor = crear_motor(f"sqlite:///{(tmp_path / 'vieja.db').as_posix()}")
    # Esquema anterior al cambio: customers sin source_key/codigo_anonimo y sales sin canal.
    with motor.begin() as con:
        con.execute(text("CREATE TABLE customers (id INTEGER PRIMARY KEY AUTOINCREMENT, first_name VARCHAR(100) NOT NULL,"
                         " last_name VARCHAR(100) NOT NULL, encrypted_email TEXT, encrypted_phone TEXT, created_at DATETIME)"))
        con.execute(text("CREATE TABLE sales (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER,"
                         " total_amount NUMERIC NOT NULL, payment_method VARCHAR(50) NOT NULL,"
                         " status VARCHAR(20), created_at DATETIME)"))
        con.execute(text("INSERT INTO customers (id, first_name, last_name, created_at) VALUES (7, 'Ana', 'Vieja', '2026-01-01 00:00:00')"))
        con.execute(text("INSERT INTO sales (id, customer_id, total_amount, payment_method, status, created_at)"
                         " VALUES (70, 7, 12345, 'EFECTIVO', 'COMPLETED', '2026-01-02 10:00:00')"))
    columnas = lambda t: {c["name"] for c in inspect(motor).get_columns(t)}  # noqa: E731
    assert "codigo_anonimo" not in columnas("customers") and "canal" not in columnas("sales")

    monkeypatch.setattr(main, "engine", motor)
    monkeypatch.setattr(main, "SessionLocal", sessionmaker(bind=motor, expire_on_commit=False))
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(
        admin_user="admin_mig", admin_password="clave-mig-qa-123", data_source_mode="ninguno", seed_on_empty=False))
    try:
        _correr_lifespan()
        assert {"source_key", "codigo_anonimo"} <= columnas("customers")
        assert "canal" in columnas("sales")
        indices = {i["name"]: i["unique"] for i in inspect(motor).get_indexes("customers")}
        assert indices.get("ix_customers_codigo_anonimo") == 1 and indices.get("ix_customers_source_key") == 1

        with sessionmaker(bind=motor)() as s:
            venta = s.get(m.SaleModel, 70)
            assert venta.canal == "sin_dato"                         # DEFAULT para filas ya existentes
            assert float(venta.total_amount) == 12345 and venta.customer_id == 7
            cliente = s.get(m.CustomerModel, 7)
            assert cliente.first_name == "Ana" and cliente.codigo_anonimo is None and cliente.source_key is None
            # las tablas nuevas existen y se puede escribir en las columnas nuevas
            cliente.codigo_anonimo = "C001"
            s.add(m.SaleModel(id=71, total_amount=1, payment_method="EFECTIVO", canal="domicilio",
                              created_at=datetime(2026, 1, 3)))
            s.commit()
            assert s.scalar(select(m.SaleModel.canal).where(m.SaleModel.id == 71)) == "domicilio"
        assert {"dim_fecha", "ventas_diarias", "calidad_datos"} <= set(inspect(motor).get_table_names())

        _correr_lifespan()                                           # segunda vez: idempotente, no falla ni pierde datos
        with sessionmaker(bind=motor)() as s:
            assert s.get(m.CustomerModel, 7).codigo_anonimo == "C001"
            assert s.get(m.SaleModel, 70).canal == "sin_dato"
    finally:
        motor.dispose()
