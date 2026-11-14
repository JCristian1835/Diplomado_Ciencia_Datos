from fastapi import APIRouter, Depends, Query
from pathlib import Path
from datetime import datetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.inbound.api.deps import servicio_analitica, usuario_actual
from app.adapters.inbound.schemas.analitica import EtlRunOut
from app.application.analitica import ServicioAnalitica
from app.adapters.outbound.persistence import models as m
from app.core.config import get_settings, obtener_clave_privacidad
from app.core.db import get_session
from app.etl.red_rooster import importar as importar_red_rooster

router = APIRouter(prefix="/etl", tags=["etl"], dependencies=[Depends(usuario_actual)])


@router.post("/run", response_model=EtlRunOut)
def ejecutar(force: bool = Query(False, description="Reentrenar aunque no haya ventas nuevas"),
             svc: ServicioAnalitica = Depends(servicio_analitica)):
    return svc.ejecutar_etl(force)


@router.get("/runs", response_model=list[EtlRunOut])
def runs(limit: int = Query(20, ge=1, le=200), svc: ServicioAnalitica = Depends(servicio_analitica)):
    return svc.listar_runs(limit)


@router.get("/source-status")
def source_status(s: Session = Depends(get_session)):
    cfg = get_settings()
    path = Path(cfg.red_rooster_json).expanduser()
    run = s.scalar(select(m.SourceImportRunModel).order_by(m.SourceImportRunModel.id.desc()).limit(1))
    source_orders = None
    if path.is_file():
        try:
            import json
            with path.open("r", encoding="utf-8-sig") as f:
                data = json.load(f)
            source_orders = len(data) if isinstance(data, list) else None
        except (OSError, ValueError):
            source_orders = None
    report = run.report if run and run.report else {}
    return {"mode": cfg.data_source_mode, "source_path": str(path.resolve()), "exists": path.is_file(),
            "last_modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat() if path.is_file() else None,
            "source_orders": source_orders,
            "loaded_orders": int(s.scalar(select(func.count(m.SaleModel.id))) or 0),
            "last_import_at": run.finished_at if run else None,
            "last_status": run.status if run else None,
            "watcher_interval_seconds": cfg.red_rooster_poll_seconds,
            "last_report": {k: v for k, v in report.items() if k != "fingerprint"},
            "last_error": run.error if run else None}


@router.post("/import")
def importar(force: bool = Query(False, description="Reprocesa aunque el origen no haya cambiado"),
             s: Session = Depends(get_session)):
    cfg = get_settings()
    started = datetime.now()
    try:
        reporte = importar_red_rooster(s, cfg.red_rooster_json, obtener_clave_privacidad(), force)
        return {**reporte, "started_at": started, "finished_at": datetime.now(),
                "errors": reporte.get("skipped", 0)}
    except Exception as exc:
        s.rollback()
        fallida = m.SourceImportRunModel(started_at=started, finished_at=datetime.now(), status="FAILED",
                                         source_path=str(Path(cfg.red_rooster_json).expanduser()),
                                         source_mtime=None, report={"inserted": 0, "updated": 0,
                                         "unchanged": 0, "skipped": 0, "lines": 0, "products": 0},
                                         error=str(exc)[:2000])
        s.add(fallida)
        s.commit()
        return {"status": "FAILED", "started_at": started, "finished_at": datetime.now(),
                "inserted": 0, "updated": 0, "unchanged": 0, "skipped": 0, "lines": 0,
                "products": 0, "errors": 1, "source_mtime": None, "message": str(exc)}


@router.get("/quality")
def calidad(s: Session = Depends(get_session)):
    tablas = {"pedidos": m.SaleModel, "detalle": m.SaleItemModel, "productos": m.ProductModel,
              "clientes": m.CustomerModel, "dim_fecha": m.DimFechaModel, "ventas_diarias": m.VentaDiariaModel}
    reglas = s.scalars(select(m.CalidadDatosModel).order_by(m.CalidadDatosModel.id)).all()
    return {"reglas": [{"regla": r.regla, "descripcion": r.descripcion,
                        "registros_afectados": r.registros_afectados, "tratamiento": r.tratamiento} for r in reglas],
            "conteos": {nombre: int(s.scalar(select(func.count()).select_from(modelo)) or 0)
                        for nombre, modelo in tablas.items()}}
