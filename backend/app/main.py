"""Punto de entrada FastAPI: lifespan (create_all + admin + seed), CORS y rutas /api/v1."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.adapters.inbound.api.deps import get_cipher
from app.adapters.inbound.api.errores import registrar_manejadores
from app.adapters.inbound.api.v1 import api_router
from app.adapters.outbound.persistence import models  # noqa: F401  (registra las tablas)
from app.adapters.outbound.persistence.repositories import UserRepoSQL
from app.core.config import get_settings, obtener_clave_privacidad
from app.core.db import Base, SessionLocal, engine
from app.core.security import hashear_password
from app.domain.entities import Usuario
from app.seed.generador_sintetico import base_vacia, sembrar
from app.etl.red_rooster import importar as importar_red_rooster

log = logging.getLogger("micronegocio")


@asynccontextmanager
async def lifespan(_: FastAPI):
    cfg = get_settings()
    Base.metadata.create_all(engine)
    # Migración aditiva para bases existentes; no modifica ni elimina registros.
    if "source_key" not in {c["name"] for c in inspect(engine).get_columns("customers")}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE customers ADD COLUMN source_key VARCHAR(64)"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_customers_source_key ON customers (source_key)"))
    if "codigo_anonimo" not in {c["name"] for c in inspect(engine).get_columns("customers")}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE customers ADD COLUMN codigo_anonimo VARCHAR(10)"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_customers_codigo_anonimo ON customers (codigo_anonimo)"))
    if "canal" not in {c["name"] for c in inspect(engine).get_columns("sales")}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE sales ADD COLUMN canal VARCHAR(20) NOT NULL DEFAULT 'sin_dato'"))
    with SessionLocal() as s:
        repo = UserRepoSQL(s)
        if repo.obtener_por_username(cfg.admin_user) is None:
            repo.crear(Usuario(cfg.admin_user, hashear_password(cfg.admin_password), True))
            s.commit()
            log.info("Usuario admin creado: %s", cfg.admin_user)
        if cfg.data_source_mode.lower() == "red_rooster":
            try:
                log.info("Carga inicial de Red Rooster: %s", importar_red_rooster(
                    s, cfg.red_rooster_json, obtener_clave_privacidad()))
            except Exception:
                log.exception("No se pudo importar el origen real; consulte /api/v1/etl/source-status")
        elif cfg.data_source_mode.lower() == "synthetic" and cfg.seed_on_empty and base_vacia(s):
            log.info("Base vacía: sembrando datos sintéticos...")
            log.info("Sembrado: %s", sembrar(s, get_cipher()))
    yield


app = FastAPI(title="Sistema de Gestión Operativa y Analítica para Micronegocios", version="1.0.0",
              lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_lista, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
registrar_manejadores(app)
app.include_router(api_router)
