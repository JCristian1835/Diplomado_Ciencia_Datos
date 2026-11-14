"""Tablas analíticas del caso Red Rooster: dim_fecha, ventas_diarias y calidad_datos.

Se reconstruyen completas dentro de la transacción de la importación (misma sesión, sin commit propio).
Definiciones del calendario:
- es_quincena: día de pago, es decir el 15 y el último día de cada mes.
- es_descanso: martes (día de descanso del negocio).
- es_festivo: festivos de Colombia según el paquete `holidays`.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import holidays
import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.adapters.outbound.persistence import models as m
from app.etl.red_rooster import ESTADOS_PAGADOS, PAGOS, canal_de

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MARTES = 1
TOLERANCIA_TOTAL = 1


def _dim_fecha(primera: pd.Timestamp, ultima: pd.Timestamp) -> list[m.DimFechaModel]:
    festivos = holidays.Colombia(years=range(primera.year, ultima.year + 1))
    filas = []
    for dia in pd.date_range(primera, ultima, freq="D"):
        manana = dia + timedelta(days=1)
        filas.append(m.DimFechaModel(
            fecha=dia.date(), anio=dia.year, mes=dia.month, dia=dia.day, dia_semana=dia.weekday(),
            nombre_dia_semana=DIAS[dia.weekday()], es_festivo=dia.date() in festivos,
            es_quincena=dia.day == 15 or manana.month != dia.month, es_descanso=dia.weekday() == MARTES))
    return filas


def _ventas_diarias(ventas: pd.DataFrame, primera: pd.Timestamp, ultima: pd.Timestamp) -> list[m.VentaDiariaModel]:
    pagadas = ventas[ventas["status"] == "COMPLETED"]
    por_dia = pagadas.groupby(pagadas["created_at"].dt.normalize()).agg(
        pedidos_pagados=("total_amount", "size"), ingresos=("total_amount", "sum"))
    df = por_dia.reindex(pd.date_range(primera, ultima, freq="D"), fill_value=0)
    df["ticket_promedio"] = df["ingresos"] / df["pedidos_pagados"].where(df["pedidos_pagados"] > 0)
    df["lag_1"] = df["pedidos_pagados"].shift(1)
    df["lag_7"] = df["pedidos_pagados"].shift(7)
    # shift(1) antes de la media: el día no entra en su propia media móvil (sin fuga del objetivo).
    df["media_movil_7"] = df["pedidos_pagados"].shift(1).rolling(7).mean()

    def nulo(valor, tipo):
        return None if pd.isna(valor) else tipo(valor)

    return [m.VentaDiariaModel(
        fecha=dia.date(), pedidos_pagados=int(f.pedidos_pagados), ingresos=float(f.ingresos),
        ticket_promedio=nulo(f.ticket_promedio, lambda v: round(float(v), 2)), lag_1=nulo(f.lag_1, int),
        lag_7=nulo(f.lag_7, int), media_movil_7=nulo(f.media_movil_7, float)) for dia, f in df.iterrows()]


def _zona(pedido: dict[str, Any]) -> timedelta | None:
    try:
        return datetime.fromisoformat(str(pedido["fecha"]).replace("Z", "+00:00")).utcoffset()
    except (KeyError, ValueError):
        return None


def _num(valor: Any, tipo: type = float):
    """Convierte un campo de origen; un valor ilegible cuenta como 0 en vez de detener la importación."""
    try:
        return tipo(valor or 0)
    except (TypeError, ValueError):
        return 0


def _calidad(pedidos: list[dict[str, Any]], productos: list[dict[str, Any]]) -> list[m.CalidadDatosModel]:
    ids_producto = {int(p["id"]) for p in productos}
    zonas = [_zona(p) for p in pedidos]
    lineas = [l for p in pedidos for l in p.get("productos") or [] if isinstance(l, dict)]

    def desviado(p: dict[str, Any]) -> bool:
        suma = sum(_num(l.get("qty")) * _num(l.get("precio")) for l in p.get("productos") or [] if isinstance(l, dict))
        return abs(suma - _num(p.get("total"))) > TOLERANCIA_TOTAL

    reglas = [
        ("fechas_con_zona_utc", "Fechas de pedido con desfase +00:00 (UTC)", sum(z == timedelta(0) for z in zonas),
         "Se convierten a America/Bogota (UTC-5) y se guardan como hora local naive"),
        ("fechas_con_zona_bogota", "Fechas de pedido con desfase -05:00 (Bogotá)",
         sum(z == timedelta(hours=-5) for z in zonas), "Se guardan como hora local naive sin cambio de hora"),
        ("pedidos_sin_canal", "Pedidos sin tipo (mesa/llevar/domicilio)", sum(canal_de(p) == "sin_dato" for p in pedidos),
         "Se conservan con canal 'sin_dato'"),
        ("mesero_texto_libre", "Campo mesero en texto libre sin catálogo; se cuentan los valores distintos",
         len({p.get("mesero") for p in pedidos if p.get("mesero")}),
         "Campo descartado: no se almacena ni se usa en el análisis"),
        ("productos_costo_cero", "Productos del catálogo con costo 0 o vacío", sum(not p.get("costo") for p in productos),
         "Costo 0 equivale a dato faltante: no se interpreta como margen del 100 %"),
        ("total_no_cuadra", f"Pedidos cuyo total difiere de la suma de qty*precio en más de {TOLERANCIA_TOTAL}",
         sum(desviado(p) for p in pedidos), "Se conserva el total de origen; queda marcado para revisión"),
        ("pedidos_cancelados", "Pedidos con estado distinto de pagado/entregado",
         sum(str(p.get("estado") or "").lower() not in ESTADOS_PAGADOS for p in pedidos),
         "Se cargan como CANCELLED y no suman a ventas ni ingresos"),
        ("pago_sin_dato", "Pedidos sin método de pago reconocido",
         sum(str(p.get("metodo_pago") or "").lower() not in PAGOS for p in pedidos),
         "Se asigna EFECTIVO (columna obligatoria); en cancelados no afecta los ingresos"),
        ("lineas_omitidas", "Líneas con producto inexistente en el catálogo o cantidad <= 0",
         sum(_num(l.get("id"), int) not in ids_producto or _num(l.get("qty"), int) <= 0 for l in lineas),
         "Se omiten al cargar el detalle del pedido"),
    ]
    return [m.CalidadDatosModel(regla=r, descripcion=d, registros_afectados=int(n), tratamiento=t)
            for r, d, n, t in reglas]


def reconstruir(session: Session, pedidos: list[dict[str, Any]], productos: list[dict[str, Any]]) -> None:
    """Reemplaza las tres tablas con el estado actual de ventas y del JSON de origen."""
    session.execute(delete(m.VentaDiariaModel))
    session.execute(delete(m.DimFechaModel))
    session.execute(delete(m.CalidadDatosModel))
    primera, ultima = session.execute(select(func.min(m.SaleModel.created_at), func.max(m.SaleModel.created_at))).one()
    if primera is not None:
        primera, ultima = pd.Timestamp(primera).normalize(), pd.Timestamp(ultima).normalize()
        ventas = pd.DataFrame(session.execute(
            select(m.SaleModel.created_at, m.SaleModel.total_amount, m.SaleModel.status)).all(),
            columns=["created_at", "total_amount", "status"])
        session.add_all(_dim_fecha(primera, ultima))
        session.flush()
        session.add_all(_ventas_diarias(ventas, primera, ultima))
    session.add_all(_calidad(pedidos, productos))
    session.flush()
