"""Regla única del costo faltante: un costo 0, nulo o no menor al precio de lista se estima, no se toma como real."""
from collections.abc import Iterable
from statistics import median


def costo_es_real(precio: float | None, costo: float | None) -> bool:
    """Un costo es real solo si es positivo y menor al precio (costo >= precio indica un dato mal cargado)."""
    return bool(precio and precio > 0 and costo and 0 < costo < precio)


def razones_costo(productos: Iterable[tuple[str | None, float, float | None]]) -> tuple[dict[str | None, float], float]:
    """Mediana de costo/precio por categoría y global, solo con productos de costo real (ver `costo_es_real`).

    `productos` son tuplas (categoría, precio, costo).
    """
    por_categoria: dict[str | None, list[float]] = {}
    for categoria, precio, costo in productos:
        if costo_es_real(precio, costo):
            por_categoria.setdefault(categoria, []).append(costo / precio)
    todas = [r for rs in por_categoria.values() for r in rs]
    return {c: median(rs) for c, rs in por_categoria.items()}, (median(todas) if todas else 0.0)


def costo_unitario(categoria: str | None, precio: float | None, costo: float | None,
                   razones: tuple[dict[str | None, float], float]) -> float:
    """Costo real si lo es; si no, precio x mediana de la categoría (o la global si la categoría no tiene).

    Sin precio válido (nulo, NaN o <= 0) devuelve 0.0.
    """
    if not (precio and precio > 0):
        return 0.0
    if costo_es_real(precio, costo):
        return float(costo)
    por_categoria, global_ = razones
    return float(precio) * por_categoria.get(categoria, global_)
