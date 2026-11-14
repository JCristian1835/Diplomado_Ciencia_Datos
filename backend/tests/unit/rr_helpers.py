"""Constructores de origen Red Rooster sintético para las pruebas del ETL (sin datos reales)."""
import json

CLAVE_QA = "clave-de-pruebas-no-reutilizable-0123456789"


def pedido(sid, fecha, total=10000, lineas=None, **extra):
    """Pedido sintético. Una clave con valor None se omite (campo ausente en el origen).

    Por defecto: mesa, pagado, efectivo y una línea del producto 501 que cuadra con el total.
    """
    base = {"id": sid, "fecha": fecha, "tipo": "mesa", "estado": "pagado", "metodo_pago": "efectivo",
            "total": total,
            "productos": [{"id": pid, "qty": qty, "precio": precio}
                          for pid, qty, precio in (lineas or [(501, 1, total)])]}
    base.update(extra)
    return {k: v for k, v in base.items() if v is not None}


def catalogo():
    return [{"id": 501, "nombre": "Producto ficticio uno", "precio": 10000, "costo": 4000,
             "categoria": "Pruebas", "activo": True}]


def escribir_origen(carpeta, pedidos, productos=None):
    """Escribe pedidos_24meses.json + productos.json en `carpeta` y devuelve la ruta de pedidos."""
    ruta = carpeta / "pedidos_24meses.json"
    ruta.write_text(json.dumps(pedidos, ensure_ascii=False), encoding="utf-8")
    (carpeta / "productos.json").write_text(
        json.dumps(catalogo() if productos is None else productos, ensure_ascii=False), encoding="utf-8")
    return ruta
