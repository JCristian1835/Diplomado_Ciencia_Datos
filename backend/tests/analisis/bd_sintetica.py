"""BD SQLite sintetica con el esquema real (creado con los modelos) para probar el paquete analisis/.

Todo es inventado: ningun dato real, ningun correo ni telefono real. Los nombres, correos y telefonos de los
clientes llevan marcas unicas (PII_*) para poder comprobar que nunca llegan a las salidas del analisis.
"""
from datetime import date, datetime, timedelta

import holidays
import numpy as np
from sqlalchemy import insert

from app.adapters.outbound.persistence import models as m
from app.core.db import Base, crear_motor

INICIO = date(2026, 3, 23)
FIN = date(2026, 11, 13)
N_CLIENTES = 40

# (id, nombre, categoria, precio de lista, costo registrado)
PRODUCTOS = [
    (1, "Hamburguesa", "platos", 15000, 6000),
    (2, "Pizza", "platos", 20000, 8000),          # se cobra a 30000: lista distinta al cobrado
    (3, "Gaseosa", "bebidas", 4000, 1500),
    (4, "Jugo", "bebidas", 5000, 0),              # costo faltante (0)
    (5, "Cerveza", "bebidas", 6000, 2400),
    (6, "Postre", "postres", 5000, 6000),         # costo >= precio de lista
    (7, "Prod_Cerca", "platos", 10000, 4000),     # se cobra a 11000: dentro de la tolerancia del 20 %
    (8, "Prod_Mediana", "platos", 9000, 3600),    # cobrado 8000, 9000, 20000 (y uno cancelado a 1.000.000)
    (9, "Prod_SinVentas", "platos", 7000, 2800),  # nunca se vende: el precio real es el de lista
]
PRECIO_COBRADO = {1: 15000, 2: 30000, 3: 4000, 4: 5000, 5: 6000, 6: 5000, 7: 11000}

# Canastas (ids de producto); 100 posiciones que se recorren en ciclo tras barajarlas con semilla fija.
CANASTAS = ([[1, 3]] * 20 + [[2, 4]] * 14 + [[1]] * 8 + [[2]] * 8 + [[5]] * 8 + [[6]] * 27 + [[3]] * 5
            + [[4]] * 5 + [[7]] * 5)

# Dias de la caida con casi ningun pedido (todos lunes) y martes con ventas (el martes no abre).
DIAS_VACIOS = {date(2026, 9, 14): 2, date(2026, 10, 5): 3, date(2026, 10, 19): 1}
MARTES_CON_VENTAS = [date(2026, 6, 2), date(2026, 7, 7), date(2026, 10, 13)]


def _fecha_dim(d):
    festivos = holidays.Colombia(years=[d.year])
    manana = d + timedelta(days=1)
    return {"fecha": d, "anio": d.year, "mes": d.month, "dia": d.day, "dia_semana": d.weekday(),
            "nombre_dia_semana": "x", "es_festivo": d in festivos,
            "es_quincena": d.day == 15 or manana.month != d.month, "es_descanso": d.weekday() == 1}


def _periodo(d):
    return "arranque" if d < date(2026, 5, 1) else "base" if d <= date(2026, 8, 31) else "caida"


def construir_bd(ruta):
    """Crea la BD en `ruta` y devuelve datos utiles para las pruebas (codigos y marcas de PII)."""
    motor = crear_motor(f"sqlite:///{ruta.as_posix()}")
    Base.metadata.create_all(motor)
    rng = np.random.default_rng(7)
    ciclo = list(rng.permutation(len(CANASTAS)))
    canal_p = {"arranque": [0.55, 0.35, 0.05, 0.05], "base": [0.50, 0.30, 0.15, 0.05],
               "caida": [0.55, 0.35, 0.05, 0.05]}
    canales = ["mesa", "llevar", "domicilio", "sin_dato"]

    clientes = [{"id": i, "first_name": f"PII_Nombre{i:02d}", "last_name": f"PII_Apellido{i:02d}",
                 "encrypted_email": f"PII_correo{i:02d}@ficticio.test", "encrypted_phone": f"PII_tel_300000{i:04d}",
                 "source_key": f"clave{i}", "codigo_anonimo": f"C{i:03d}", "created_at": datetime(2026, 3, 1)}
                for i in range(1, N_CLIENTES + 1)]
    productos = [{"id": i, "sku": f"S{i}", "name": nombre, "category": cat, "unit_price": precio, "unit_cost": costo,
                  "stock": 10, "is_active": True, "created_at": datetime(2026, 3, 1)}
                 for i, nombre, cat, precio, costo in PRODUCTOS]
    dim = [_fecha_dim(INICIO + timedelta(days=k)) for k in range((FIN - INICIO).days + 1)]

    ventas, items = [], []

    def vender(momento, canasta, estado="COMPLETED", canal="mesa", cliente=None, precios=None):
        sid = len(ventas) + 1
        precios = precios or [PRECIO_COBRADO[p] for p in canasta]
        ventas.append({"id": sid, "customer_id": cliente, "total_amount": sum(precios), "payment_method": "efectivo",
                       "status": estado, "canal": canal, "created_at": momento})
        for p, precio in zip(canasta, precios):
            items.append({"sale_id": sid, "product_id": p, "quantity": 1, "unit_price": precio, "subtotal": precio})

    contador = 0
    for d in (INICIO + timedelta(days=k) for k in range((FIN - INICIO).days + 1)):
        if d.weekday() == 1:
            cantidad = 2 if d in MARTES_CON_VENTAS else 0
        elif d == FIN:
            cantidad = 3                                   # 13-nov: dia incompleto
        elif d in DIAS_VACIOS:
            cantidad = DIAS_VACIOS[d]
        else:
            media = {"arranque": 6, "base": 11, "caida": 8}[_periodo(d)] + (2 if d.weekday() >= 4 else 0)
            cantidad = max(6, int(round(rng.normal(media, 1.5))))
        periodo = _periodo(d)
        for j in range(cantidad):
            canasta = CANASTAS[ciclo[contador % len(CANASTAS)]]
            canal = str(rng.choice(canales, p=canal_p[periodo]))
            cliente = int(1 + rng.random() ** 2 * N_CLIENTES) if canal in ("domicilio",) or (
                canal == "sin_dato" and rng.random() < 0.3) else None
            estado = "CANCELLED" if contador % 25 == 24 else "COMPLETED"
            vender(datetime(d.year, d.month, d.day, 12 + j % 9, (7 * j) % 60), canasta, estado, canal, cliente)
            contador += 1

    # Producto con precios cobrados 8000, 9000, 20000 (mediana 9000) y una venta cancelada a 1.000.000
    # que no debe contar. Productos y fechas fijos para poder calcular a mano.
    for k, (precio, estado) in enumerate([(8000, "COMPLETED"), (9000, "COMPLETED"), (20000, "COMPLETED"),
                                          (1_000_000, "CANCELLED")]):
        vender(datetime(2026, 7, 8, 21, k), [8], estado, "mesa", None, [precio])

    motor_tablas = [(m.CustomerModel, clientes), (m.ProductModel, productos), (m.DimFechaModel, dim),
                    (m.SaleModel, ventas), (m.SaleItemModel, items)]
    with motor.begin() as con:
        for modelo, filas in motor_tablas:
            con.execute(insert(modelo.__table__), filas)
    motor.dispose()
    return {"codigos": {c["codigo_anonimo"] for c in clientes},
            "marcas_pii": [c[campo] for c in clientes for campo in ("first_name", "last_name", "encrypted_email",
                                                                     "encrypted_phone")]}
