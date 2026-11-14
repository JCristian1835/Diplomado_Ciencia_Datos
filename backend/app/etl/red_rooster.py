"""Carga repetible del origen real Red Rooster a SQLite, sin persistir PII."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.outbound.persistence import models as m

BOGOTA = ZoneInfo("America/Bogota")
ESTADOS_PAGADOS = {"pagado", "entregado"}
PAGOS = {"efectivo": "EFECTIVO", "tarjeta": "TARJETA", "nequi": "NEQUI",
         "breb": "TRANSFERENCIA", "transferencia": "TRANSFERENCIA"}
CANALES = {"mesa", "llevar", "domicilio"}


def _fecha(texto: str) -> datetime:
    valor = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=BOGOTA)
    return valor.astimezone(BOGOTA).replace(tzinfo=None)


def canal_de(pedido: dict[str, Any]) -> str:
    tipo = str(pedido.get("tipo") or "").lower()
    return tipo if tipo in CANALES else "sin_dato"


def _huella_cliente(pedido: dict[str, Any], clave: str) -> str | None:
    """HMAC del teléfono (solo dígitos, sin el 57 del país) o, si no hay, de la dirección de un domicilio."""
    identificador = re.sub(r"\D", "", str(pedido.get("telefono") or ""))
    if len(identificador) == 12 and identificador.startswith("57"):
        identificador = identificador[2:]
    if not identificador and canal_de(pedido) == "domicilio":
        identificador = " ".join(str(pedido.get("direccion") or "").lower().split())
    if not identificador:
        return None
    return hmac.new(clave.encode(), identificador.encode(), hashlib.sha256).hexdigest()


def _asignar_codigos(session: Session) -> None:
    """Da C001, C002... por orden de primera compra; un código ya asignado no cambia nunca."""
    nuevos = session.scalars(select(m.CustomerModel).where(m.CustomerModel.codigo_anonimo.is_(None))
                             .order_by(m.CustomerModel.created_at, m.CustomerModel.id)).all()
    usados = session.scalars(select(m.CustomerModel.codigo_anonimo)
                             .where(m.CustomerModel.codigo_anonimo.is_not(None))).all()
    siguiente = max((int(c[1:]) for c in usados), default=0) + 1
    for cliente in nuevos:
        cliente.codigo_anonimo = f"C{siguiente:03d}"
        siguiente += 1


def _leer_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def _fingerprint(*paths: Path) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(p.name.encode())
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    return h.hexdigest()


def importar(session: Session, ruta: str | Path, clave: str, force: bool = False) -> dict[str, Any]:
    """Upsert de catálogo y pedidos dentro de una transacción (se puede repetir)."""
    ruta = Path(ruta).expanduser().resolve()
    catalogo_path = ruta.with_name("productos.json")
    if not ruta.is_file() or not catalogo_path.is_file():
        raise FileNotFoundError(f"No existen el archivo de pedidos o su catálogo: {ruta}")
    if len(clave) < 16:
        raise ValueError("DATA_PRIVACY_KEY debe tener al menos 16 caracteres")
    mtime = max(ruta.stat().st_mtime, catalogo_path.stat().st_mtime)
    firma = _fingerprint(ruta, catalogo_path)
    ultimo = session.scalar(select(m.SourceImportRunModel).where(
        m.SourceImportRunModel.status == "SUCCESS").order_by(m.SourceImportRunModel.id.desc()).limit(1))
    if ultimo and ultimo.report and ultimo.report.get("fingerprint") == firma and not force:
        return {"status": "SIN_CAMBIOS", "inserted": 0, "updated": 0, "unchanged": 0,
                "skipped": 0, "lines": 0, "products": 0, "errors": 0,
                "source_mtime": mtime, "message": "Los archivos de origen no han cambiado"}
    # No mezclar una semilla sintética preexistente con pedidos reales ni sobrescribirla.
    if ultimo is None and session.scalar(select(func.count(m.SaleModel.id))) > 0:
        raise ValueError("La base ya contiene ventas sin linaje Red Rooster. Configure DATABASE_URL a un SQLite vacío para no mezclar fuentes.")
    pedidos, productos = _leer_json(ruta), _leer_json(catalogo_path)
    if not isinstance(pedidos, list) or not isinstance(productos, list):
        raise ValueError("El archivo de pedidos y productos.json deben contener listas JSON")

    nuevos = actualizados = sin_cambio = omitidos = lineas = 0
    por_pid: dict[int, m.ProductModel] = {}
    for item in productos:
        pid = int(item["id"])
        producto = session.get(m.ProductModel, pid)
        valores = {"sku": f"RR-{pid:03d}", "name": str(item["nombre"])[:150],
                   "category": str(item.get("categoria") or "Sin categoría")[:100],
                   "unit_price": float(item.get("precio") or 0), "unit_cost": float(item.get("costo") or 0),
                   "is_active": bool(item.get("activo", True))}
        if producto is None:
            producto = m.ProductModel(id=pid, stock=0, **valores)
        else:
            for k, v in valores.items():
                setattr(producto, k, v)
        session.add(producto)
        por_pid[pid] = producto
    session.flush()

    for pedido in pedidos:
        try:
            sid = int(pedido["id"])
            estado = str(pedido.get("estado") or "").lower()
            fecha = _fecha(str(pedido["fecha"]))
            huella = _huella_cliente(pedido, clave)
            cliente_id = None
            if huella:
                cliente = session.scalar(select(m.CustomerModel).where(m.CustomerModel.source_key == huella))
                if cliente is None:
                    cliente = m.CustomerModel(first_name="Cliente", last_name="Red Rooster", source_key=huella,
                                              created_at=fecha)
                    session.add(cliente)
                    session.flush()
                elif fecha < cliente.created_at:
                    cliente.created_at = fecha
                cliente_id = cliente.id
            venta = session.get(m.SaleModel, sid)
            existente = venta is not None
            if existente:
                # Compare el contenido relevante para devolver un conteo real de actualizaciones.
                actual = (venta.created_at, venta.customer_id, float(venta.total_amount), venta.status,
                          venta.payment_method, venta.canal,
                          [(i.product_id, i.quantity, float(i.unit_price)) for i in venta.items])
            else:
                venta = m.SaleModel(id=sid)
                session.add(venta)
                actual = None
            lineas_nuevas = []
            for l in pedido.get("productos") or []:
                pid, qty = int(l["id"]), int(l.get("qty") or 0)
                if pid not in por_pid or qty <= 0:
                    omitidos += 1
                    continue
                precio = float(l.get("precio") or 0)
                lineas_nuevas.append((pid, qty, precio))
            status = "COMPLETED" if estado in ESTADOS_PAGADOS else "CANCELLED"
            total = float(pedido.get("total") or 0)
            pago = PAGOS.get(str(pedido.get("metodo_pago") or "").lower(), "EFECTIVO")
            canal = canal_de(pedido)
            objetivo = (fecha, cliente_id, total, status, pago, canal, lineas_nuevas)
            if actual == objetivo:
                sin_cambio += 1
                continue
            venta.created_at, venta.customer_id = fecha, cliente_id
            venta.total_amount, venta.status, venta.payment_method, venta.canal = total, status, pago, canal
            venta.items.clear()
            for pid, qty, precio in lineas_nuevas:
                venta.items.append(m.SaleItemModel(product_id=pid, quantity=qty, unit_price=precio,
                                                   subtotal=round(qty * precio, 2)))
            lineas += len(lineas_nuevas)
            if existente:
                actualizados += 1
            else:
                nuevos += 1
        except (KeyError, TypeError, ValueError, OverflowError):
            omitidos += 1
    _asignar_codigos(session)
    from app.etl.red_rooster_analitica import reconstruir  # import tardío: el módulo usa constantes de este
    reconstruir(session, pedidos, productos)
    reporte = {"fingerprint": firma, "inserted": nuevos, "updated": actualizados,
               "unchanged": sin_cambio, "skipped": omitidos, "lines": lineas, "products": len(productos),
               "orders_in_source": len(pedidos)}
    ahora = datetime.now()
    corrida = m.SourceImportRunModel(started_at=ahora, finished_at=ahora, status="SUCCESS",
                                     source_path=str(ruta), source_mtime=mtime, report=reporte)
    session.add(corrida)
    session.commit()
    return {"status": "SUCCESS", **reporte, "errors": omitidos, "source_mtime": mtime,
            "message": "Importación completada"}
