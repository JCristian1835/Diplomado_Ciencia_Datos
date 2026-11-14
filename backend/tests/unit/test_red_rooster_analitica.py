"""Tablas analíticas dim_fecha, ventas_diarias y calidad_datos con orígenes sintéticos y SQLite temporal.

Todos los valores esperados están calculados a mano en los comentarios.
"""
import json
from datetime import date

import pytest
from sqlalchemy import func, select

from app.adapters.outbound.persistence import models as m
from app.etl.red_rooster import importar
from tests.unit.rr_helpers import CLAVE_QA, escribir_origen, pedido

HORA = "T12:00:00-05:00"


def _dia(texto):
    return date.fromisoformat(texto)


def _dim(db_session):
    return {f.fecha: f for f in db_session.scalars(select(m.DimFechaModel).order_by(m.DimFechaModel.fecha))}


# ----------------------------------------------------------------------------- dim_fecha
def test_dim_fecha_continua_festivo_martes_y_quincena(db_session, tmp_path):
    # Rango 2026-02-26 .. 2026-03-24 con pedidos solo en los extremos: 3 días de febrero + 24 de marzo = 27 filas.
    pedidos = [pedido(1, "2026-02-26" + HORA), pedido(2, "2026-03-24" + HORA)]
    importar(db_session, escribir_origen(tmp_path, pedidos), CLAVE_QA)
    dim = _dim(db_session)

    assert len(dim) == 27
    assert min(dim) == _dia("2026-02-26") and max(dim) == _dia("2026-03-24")
    # sin huecos: cada día consecutivo está
    dias = sorted(dim)
    assert all((b - a).days == 1 for a, b in zip(dias, dias[1:]))
    # el 2026-03-05 no tuvo pedidos y aun así existe
    assert _dia("2026-03-05") in dim

    # Festivo: San José 2026 cae jueves 19 y se traslada al lunes 23 de marzo; es el único del rango.
    assert [d for d, f in dim.items() if f.es_festivo] == [_dia("2026-03-23")]
    lunes = dim[_dia("2026-03-23")]
    assert (lunes.dia_semana, lunes.nombre_dia_semana) == (0, "lunes")

    # Descanso: martes 3, 10, 17 y 24 de marzo (1 de marzo de 2026 es domingo).
    assert [d for d, f in dim.items() if f.es_descanso] == [_dia(f"2026-03-{n:02d}") for n in (3, 10, 17, 24)]
    martes = dim[_dia("2026-03-03")]
    assert (martes.dia_semana, martes.nombre_dia_semana) == (1, "martes")

    # Quincena: 28 de febrero (último día, 2026 no es bisiesto) y 15 de marzo.
    assert [d for d, f in dim.items() if f.es_quincena] == [_dia("2026-02-28"), _dia("2026-03-15")]

    f = dim[_dia("2026-03-15")]
    assert (f.anio, f.mes, f.dia, f.dia_semana, f.nombre_dia_semana) == (2026, 3, 15, 6, "domingo")


@pytest.mark.parametrize("desde,hasta,quincenas", [
    ("2026-03-30", "2026-04-01", ["2026-03-31"]),                 # mes de 31 días: el 30 NO es quincena
    ("2026-04-29", "2026-05-01", ["2026-04-30"]),                 # mes de 30 días
    ("2028-02-28", "2028-03-01", ["2028-02-29"]),                 # bisiesto: el 28 NO, el 29 sí
    ("2026-12-30", "2027-01-01", ["2026-12-31"]),                 # cambio de año
])
def test_dim_fecha_quincena_es_ultimo_dia_del_mes(db_session, tmp_path, desde, hasta, quincenas):
    pedidos = [pedido(1, desde + HORA), pedido(2, hasta + HORA)]
    importar(db_session, escribir_origen(tmp_path, pedidos), CLAVE_QA)
    assert [d.isoformat() for d, f in _dim(db_session).items() if f.es_quincena] == quincenas


def test_dim_fecha_incluye_dias_de_pedidos_cancelados_y_no_se_acumula_al_reimportar(db_session, tmp_path):
    pedidos = [pedido(1, "2026-04-01" + HORA), pedido(2, "2026-04-03" + HORA, estado="cancelado")]
    ruta = escribir_origen(tmp_path, pedidos)
    importar(db_session, ruta, CLAVE_QA)
    assert sorted(_dim(db_session)) == [_dia("2026-04-01"), _dia("2026-04-02"), _dia("2026-04-03")]
    importar(db_session, ruta, CLAVE_QA, force=True)
    assert db_session.scalar(select(func.count()).select_from(m.DimFechaModel)) == 3
    assert db_session.scalar(select(func.count()).select_from(m.VentaDiariaModel)) == 3


# ------------------------------------------------------------------------- ventas_diarias
# Pedidos pagados por día, 2026-04-01 .. 2026-04-10:
PAGADOS = [2, 0, 1, 3, 2, 1, 2, 4, 1, 1]


def _origen_ventas(pico=None):
    """Día 1: dos pedidos (10000 y 20000); el resto 10000 c/u; el día 2 solo tiene un pedido cancelado enorme."""
    pedidos, sid = [], 100
    for i, n in enumerate(pico or PAGADOS):
        dia = f"2026-04-{i + 1:02d}" + HORA
        for k in range(n):
            pedidos.append(pedido(sid, dia, total=20000 if (i == 0 and k == 1) else 10000))
            sid += 1
    pedidos.append(pedido(1, "2026-04-02" + HORA, total=999000, estado="cancelado"))
    pedidos.append(pedido(2, "2026-04-01" + HORA, total=777000, estado="cancelado"))
    return pedidos


def _ventas(db_session):
    return {v.fecha: v for v in db_session.scalars(select(m.VentaDiariaModel).order_by(m.VentaDiariaModel.fecha))}


def test_ventas_diarias_solo_pagados_lags_nulos_y_ticket(db_session, tmp_path):
    importar(db_session, escribir_origen(tmp_path, _origen_ventas()), CLAVE_QA)
    v = _ventas(db_session)
    dias = [_dia(f"2026-04-{n:02d}") for n in range(1, 11)]
    assert list(v) == dias                                          # un renglón por día, también los de 0 pedidos

    assert [v[d].pedidos_pagados for d in dias] == PAGADOS          # los cancelados no suman
    # ingresos: día 1 = 10000 + 20000 (no 777000); día 2 = 0 (no 999000); resto 10000 * n
    assert [v[d].ingresos for d in dias] == [30000, 0, 10000, 30000, 20000, 10000, 20000, 40000, 10000, 10000]
    # ticket = ingresos / pedidos; NULL cuando no hubo pedidos (no 0)
    assert v[dias[0]].ticket_promedio == 15000
    assert v[dias[1]].ticket_promedio is None
    assert v[dias[3]].ticket_promedio == 10000

    # lag_1: NULL el primer día; después el valor del día previo (un 0 real sigue siendo 0, no NULL)
    assert v[dias[0]].lag_1 is None
    assert [v[d].lag_1 for d in dias[1:]] == PAGADOS[:-1]
    assert v[dias[2]].lag_1 == 0
    # lag_7: NULL los primeros 7 días; después el valor de 7 días atrás
    assert [v[d].lag_7 for d in dias[:7]] == [None] * 7
    assert [v[d].lag_7 for d in dias[7:]] == PAGADOS[:3]            # [2, 0, 1]


def test_media_movil_no_incluye_el_dia_actual(db_session, tmp_path):
    importar(db_session, escribir_origen(tmp_path, _origen_ventas()), CLAVE_QA)
    v = _ventas(db_session)
    dias = [_dia(f"2026-04-{n:02d}") for n in range(1, 11)]
    # NULL mientras no haya 7 días previos (índices 0..6)
    assert [v[d].media_movil_7 for d in dias[:7]] == [None] * 7
    # índice 7 (día 8): días 1..7 = 2+0+1+3+2+1+2 = 11 -> 11/7
    assert v[dias[7]].media_movil_7 == pytest.approx(11 / 7)
    # índice 8 (día 9): días 2..8 = 0+1+3+2+1+2+4 = 13 -> 13/7
    assert v[dias[8]].media_movil_7 == pytest.approx(13 / 7)
    # índice 9 (día 10): días 3..9 = 1+3+2+1+2+4+1 = 14 -> 2.0
    assert v[dias[9]].media_movil_7 == pytest.approx(2.0)


def test_un_pico_en_el_dia_d_no_cambia_su_propia_media_pero_si_la_de_d_mas_1(db_session, tmp_path):
    ruta = escribir_origen(tmp_path, _origen_ventas())
    importar(db_session, ruta, CLAVE_QA)
    antes = _ventas(db_session)
    d8, d9 = _dia("2026-04-08"), _dia("2026-04-09")
    assert antes[d8].media_movil_7 == pytest.approx(11 / 7)
    assert antes[d9].media_movil_7 == pytest.approx(13 / 7)

    pico = list(PAGADOS)
    pico[7] = 10                                                    # el día 8 pasa de 4 a 10 pedidos
    escribir_origen(tmp_path, _origen_ventas(pico))
    importar(db_session, ruta, CLAVE_QA, force=True)
    despues = _ventas(db_session)
    assert despues[d8].pedidos_pagados == 10
    assert despues[d8].media_movil_7 == pytest.approx(11 / 7)       # igual: el día 8 no entra en su media
    # día 9: días 2..8 = 0+1+3+2+1+2+10 = 19 -> 19/7 (antes 13/7)
    assert despues[d9].media_movil_7 == pytest.approx(19 / 7)
    assert despues[d9].lag_1 == 10


def test_sin_ventas_no_hay_filas_analiticas_pero_si_calidad(db_session, tmp_path):
    importar(db_session, escribir_origen(tmp_path, []), CLAVE_QA)
    assert db_session.scalar(select(func.count()).select_from(m.DimFechaModel)) == 0
    assert db_session.scalar(select(func.count()).select_from(m.VentaDiariaModel)) == 0
    assert db_session.scalar(select(func.count()).select_from(m.CalidadDatosModel)) == 9


# ---------------------------------------------------------------------------- calidad_datos
REGLAS = ["fechas_con_zona_utc", "fechas_con_zona_bogota", "pedidos_sin_canal", "mesero_texto_libre",
          "productos_costo_cero", "total_no_cuadra", "pedidos_cancelados", "pago_sin_dato", "lineas_omitidas"]


def _productos_calidad():
    return [{"id": 501, "nombre": "uno", "precio": 10000, "costo": 4000, "categoria": "Q", "activo": True},
            {"id": 502, "nombre": "dos", "precio": 10000, "costo": 0, "categoria": "Q", "activo": True},
            {"id": 503, "nombre": "tres", "precio": 10000, "categoria": "Q", "activo": True},
            {"id": 504, "nombre": "cuatro", "precio": 10000, "costo": None, "categoria": "Q", "activo": True}]


def _pedidos_calidad():
    """Diez pedidos; cada regla tiene un conteo distinto y calculado a mano (ver ESPERADO)."""
    return [
        pedido(1, "2026-05-01T12:00:00-05:00", mesero="Ana"),                                    # bogota
        pedido(2, "2026-05-01T17:00:00+00:00", tipo="llevar", estado="entregado", metodo_pago="nequi",
               mesero="ana"),                                                                    # utc
        pedido(3, "2026-05-02T12:00:00-05:00", tipo=None, metodo_pago="tarjeta", mesero="Ana"),  # sin canal
        pedido(4, "2026-05-02T13:00:00-05:00", tipo="otro", estado="cancelado", metodo_pago="breb",
               mesero=""),                                                                       # sin canal + cancelado
        pedido(5, "2026-05-03T12:00:00-05:00", metodo_pago="cheque"),                            # pago sin dato
        pedido(6, "2026-05-03T09:00:00", metodo_pago=None),                                      # sin zona + pago sin dato
        pedido(7, "2026-05-04T12:00:00-05:00", total=10001, lineas=[(501, 1, 10000)]),           # dif 1: NO cuenta
        pedido(8, "2026-05-04T13:00:00-05:00", total=10002, lineas=[(501, 1, 10000)]),           # dif 2: cuenta
        pedido(9, "2026-05-04T14:00:00-05:00", total=9998, lineas=[(501, 1, 10000)]),            # dif -2: cuenta
        pedido(10, "2026-05-05T12:00:00-05:00", total=15000,
               lineas=[(501, 1, 10000), (999, 1, 5000), (501, 0, 10000)]),                       # 2 líneas omitidas
    ]


ESPERADO = {
    "fechas_con_zona_utc": 1,       # P2
    "fechas_con_zona_bogota": 8,    # 10 pedidos - P2 (UTC) - P6 (sin zona)
    "pedidos_sin_canal": 2,         # P3 (sin tipo) y P4 ("otro")
    "mesero_texto_libre": 2,        # {"Ana", "ana"}; "" y ausentes no cuentan
    "productos_costo_cero": 3,      # 502 (0), 503 (sin costo), 504 (None)
    "total_no_cuadra": 2,           # P8 y P9; P7 (dif 1) y P10 (cuadra con sus 3 líneas) no
    "pedidos_cancelados": 1,        # P4
    "pago_sin_dato": 2,             # P5 ("cheque") y P6 (ausente)
    "lineas_omitidas": 2,           # producto 999 inexistente y qty 0
}


def _calidad(db_session):
    return {c.regla: c for c in db_session.scalars(select(m.CalidadDatosModel).order_by(m.CalidadDatosModel.id))}


def test_calidad_nueve_reglas_con_conteos_exactos(db_session, tmp_path):
    importar(db_session, escribir_origen(tmp_path, _pedidos_calidad(), _productos_calidad()), CLAVE_QA)
    calidad = _calidad(db_session)
    assert list(calidad) == REGLAS
    assert {r: c.registros_afectados for r, c in calidad.items()} == ESPERADO
    assert all(c.descripcion and c.tratamiento for c in calidad.values())


def test_calidad_tolerancia_del_total_uno_no_cuenta_dos_si(db_session, tmp_path):
    base = [pedido(1, "2026-05-04T12:00:00-05:00", total=10001, lineas=[(501, 1, 10000)]),
            pedido(2, "2026-05-04T13:00:00-05:00", total=9999, lineas=[(501, 1, 10000)])]
    ruta = escribir_origen(tmp_path, base)
    importar(db_session, ruta, CLAVE_QA)
    assert _calidad(db_session)["total_no_cuadra"].registros_afectados == 0          # ambos con diferencia 1

    base[0]["total"] = 10002
    escribir_origen(tmp_path, base)
    importar(db_session, ruta, CLAVE_QA, force=True)
    assert _calidad(db_session)["total_no_cuadra"].registros_afectados == 1          # dif 2 sí; dif 1 no


def test_calidad_se_reemplaza_y_no_se_acumula_al_reimportar_con_force(db_session, tmp_path):
    pedidos = _pedidos_calidad()
    ruta = escribir_origen(tmp_path, pedidos, _productos_calidad())
    importar(db_session, ruta, CLAVE_QA)
    importar(db_session, ruta, CLAVE_QA, force=True)
    assert db_session.scalar(select(func.count()).select_from(m.CalidadDatosModel)) == 9

    pedidos[3]["estado"] = "pagado"                                 # P4 deja de estar cancelado
    escribir_origen(tmp_path, pedidos, _productos_calidad())
    importar(db_session, ruta, CLAVE_QA, force=True)
    calidad = _calidad(db_session)
    assert db_session.scalar(select(func.count()).select_from(m.CalidadDatosModel)) == 9
    assert calidad["pedidos_cancelados"].registros_afectados == 0


def test_sin_cambios_no_toca_calidad_ni_las_tablas_analiticas(db_session, tmp_path):
    ruta = escribir_origen(tmp_path, _pedidos_calidad(), _productos_calidad())
    importar(db_session, ruta, CLAVE_QA)
    marca = db_session.scalars(select(m.CalidadDatosModel).where(m.CalidadDatosModel.regla == "pedidos_cancelados")).one()
    ids_antes = [c.id for c in _calidad(db_session).values()]
    marca.registros_afectados = 4242                                # centinela: si se reconstruye, desaparece
    db_session.commit()

    r = importar(db_session, ruta, CLAVE_QA)
    assert r["status"] == "SIN_CAMBIOS"
    calidad = _calidad(db_session)
    assert calidad["pedidos_cancelados"].registros_afectados == 4242
    assert [c.id for c in calidad.values()] == ids_antes


def test_import_fallido_conserva_calidad_y_en_primera_carga_no_crea_tablas(db_session, tmp_path):
    ruta = escribir_origen(tmp_path, _pedidos_calidad(), _productos_calidad())
    importar(db_session, ruta, CLAVE_QA)
    antes = {r: c.registros_afectados for r, c in _calidad(db_session).items()}
    n_dim = db_session.scalar(select(func.count()).select_from(m.DimFechaModel))

    ruta.write_text("{json truncado", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        importar(db_session, ruta, CLAVE_QA, force=True)
    assert {r: c.registros_afectados for r, c in _calidad(db_session).items()} == antes
    assert db_session.scalar(select(func.count()).select_from(m.DimFechaModel)) == n_dim
    # y no se registra una corrida SUCCESS adicional
    assert db_session.scalar(select(func.count()).select_from(m.SourceImportRunModel)) == 1


def test_primera_carga_invalida_deja_vacias_las_tablas_analiticas(db_session, tmp_path):
    ruta = escribir_origen(tmp_path, [pedido(1, "2026-05-01" + HORA)])
    ruta.write_text("{json truncado", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        importar(db_session, ruta, CLAVE_QA)
    for modelo in (m.DimFechaModel, m.VentaDiariaModel, m.CalidadDatosModel):
        assert db_session.scalar(select(func.count()).select_from(modelo)) == 0
