"""Utilidades compartidas por los pasos del análisis del Objetivo 2 (Red Rooster).

Definiciones del análisis (se usan igual en todos los pasos):
- Día abierto: cualquier día que no es martes (el martes es el descanso del restaurante).
- El 13-nov-2026 se excluye de las comparaciones: es el último día de la BD y está incompleto.
- Marzo y abril (23-mar a 30-abr) son el arranque del sistema: se muestran, pero no entran
  en la comparación entre periodos.
- Periodo base: 1-may a 31-ago-2026. Periodo caída: 1-sep a 12-nov-2026.
- Métricas "por día abierto" = pedidos pagados del periodo / días abiertos del periodo.
- Costo faltante (0, nulo o no menor al precio de lista): costo estimado = precio x mediana(costo/precio)
  de los productos de la misma categoría con costo real; si la categoría no tiene ninguno, la mediana
  global. Es la misma regla que usa la plataforma (app/domain/costos.py).
- Precio real de un producto = mediana de sale_items.unit_price de los pedidos pagados (el precio de
  lista del catálogo puede estar mal cargado); los márgenes y combos usan el precio real.

La BD se abre siempre en solo lectura. Las salidas (JSON, TXT, PNG) van a analisis/salidas/.
"""
import io
import json
import math
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter, MaxNLocator

from app.domain.costos import costo_es_real, costo_unitario, razones_costo  # requiere ejecutar desde backend/

RAIZ = Path(__file__).resolve().parent
DB_RUTA = Path(os.environ.get("ANALISIS_DB", RAIZ.parent / "data" / "red_rooster.db"))
SALIDAS = RAIZ / "salidas"

INICIO_BASE = pd.Timestamp("2026-05-01")
FIN_BASE = pd.Timestamp("2026-08-31")
INICIO_CAIDA = pd.Timestamp("2026-09-01")
FIN_CAIDA = pd.Timestamp("2026-11-12")
SEMILLA = 42
# Día "casi sin pedidos": 5 o menos. Ningún día del periodo base bajó de 7 pedidos, así que
# 5 o menos es un nivel que el restaurante no había registrado en su operación normal.
UMBRAL_CASI_SIN_PEDIDOS = 5

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = {1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio", 7: "julio",
         8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"}
ETIQUETA_PERIODO = {"arranque": "Arranque", "base": "Base", "caida": "Caída"}

COLOR_BASE = "#2a6f97"
COLOR_CAIDA = "#d1603d"
COLOR_NEUTRO = "#8a8f98"
COLOR_TEXTO = "#2b2f36"


# ---------------------------------------------------------------- formato es-CO

def n(valor, decimales=0):
    """Número con miles en punto y decimales en coma (es-CO)."""
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return "-"
    texto = f"{valor:,.{decimales}f}"
    return texto.replace(",", "\0").replace(".", ",").replace("\0", ".")


def pesos(valor, decimales=0):
    return "$ " + n(valor, decimales)


def pct(fraccion, decimales=1):
    """Recibe una fracción (0,25) y la muestra como porcentaje (25,0 %)."""
    return n(fraccion * 100, decimales) + " %"


def fmt_p(p):
    return "< 0,0001" if p < 0.0001 else n(p, 4)


def texto_p(p):
    return "p < 0,0001" if p < 0.0001 else f"p = {n(p, 4)}"


def fecha_corta(fecha):
    return pd.Timestamp(fecha).strftime("%d-%m-%Y")


# ---------------------------------------------------------------- salida por consola

def titulo(texto):
    print("\n" + "=" * 78)
    print(f" {texto}")
    print("=" * 78)


def subtitulo(texto):
    print(f"\n--- {texto} ---")


def tabla(encabezados, filas, izquierda=(0,)):
    """Imprime una tabla alineada: columnas de texto (por defecto la primera) a la izquierda, el resto a la derecha."""
    filas = [[str(c) for c in fila] for fila in filas]
    anchos = [max(len(str(e)), *(len(f[i]) for f in filas)) if filas else len(str(e))
              for i, e in enumerate(encabezados)]

    def linea(celdas):
        partes = [str(c).ljust(anchos[i]) if i in izquierda else str(c).rjust(anchos[i])
                  for i, c in enumerate(celdas)]
        return "  ".join(partes)

    print(linea(encabezados))
    print("  ".join("-" * a for a in anchos))
    for fila in filas:
        print(linea(fila))


class _Duplicado:
    """Escribe a la consola y a un búfer a la vez (para guardar el .txt de evidencia)."""

    def __init__(self, consola, bufer):
        self.consola, self.bufer = consola, bufer

    def write(self, texto):
        self.consola.write(texto)
        self.bufer.write(texto)

    def flush(self):
        self.consola.flush()


def _limpiar(obj):
    """Convierte tipos de numpy/pandas a tipos JSON y redondea decimales."""
    if isinstance(obj, dict):
        return {str(k): _limpiar(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_limpiar(v) for v in obj]
    if isinstance(obj, np.datetime64):
        obj = pd.Timestamp(obj)
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        return obj.strftime("%Y-%m-%d")
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return None if math.isnan(obj) or math.isinf(obj) else round(float(obj), 6)
    if obj is None or obj is pd.NaT or obj is pd.NA:
        return None
    return obj


class Reporte:
    """Contexto de un paso: duplica la consola a un .txt y guarda `datos` como .json."""

    def __init__(self, nombre):
        self.nombre = nombre
        self.datos = {}
        self.graficas = []

    def __enter__(self):
        SALIDAS.mkdir(exist_ok=True)
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        self._consola = sys.stdout
        self._bufer = io.StringIO()
        sys.stdout = _Duplicado(self._consola, self._bufer)
        return self

    def __exit__(self, tipo, valor, traza):
        sys.stdout = self._consola
        if tipo is not None:
            return False
        self.datos["graficas"] = self.graficas
        (SALIDAS / f"{self.nombre}.txt").write_text(self._bufer.getvalue(), encoding="utf-8")
        (SALIDAS / f"{self.nombre}.json").write_text(
            json.dumps(_limpiar(self.datos), ensure_ascii=False, indent=2), encoding="utf-8")
        return False

    def guardar_figura(self, fig, sufijo):
        archivo = f"{self.nombre}_{sufijo}.png"
        fig.savefig(SALIDAS / archivo, dpi=150)
        plt.close(fig)
        self.graficas.append(archivo)
        print(f"\nGráfica guardada: analisis/salidas/{archivo}")


# ---------------------------------------------------------------- gráficas

def nueva_figura():
    """Lienzo de 1600 x 900 px a 150 dpi con estilo sobrio."""
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": "#b8bcc4",
        "axes.labelcolor": COLOR_TEXTO, "text.color": COLOR_TEXTO,
        "xtick.color": COLOR_TEXTO, "ytick.color": COLOR_TEXTO,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": "#e3e5e9", "grid.linewidth": 0.8,
        "axes.axisbelow": True, "axes.titlesize": 14, "axes.titleweight": "bold",
        "axes.titlelocation": "left", "figure.facecolor": "white",
    })
    fig, ax = plt.subplots(figsize=(1600 / 150, 900 / 150))
    return fig, ax


def formato_es(eje, decimales=0):
    """Pone el eje (ax.xaxis / ax.yaxis) con separadores es-CO."""
    if decimales == 0:
        eje.set_major_locator(MaxNLocator(integer=True))  # evita marcas 2,5 redondeadas a "2"
    eje.set_major_formatter(FuncFormatter(lambda v, _: n(v, decimales)))


# ---------------------------------------------------------------- carga de datos

@dataclass
class Datos:
    ventas: pd.DataFrame     # pedidos pagados (COMPLETED) con fecha, hora, periodo, abierto
    cancelados: int          # pedidos no pagados, solo para informar
    items: pd.DataFrame      # líneas de los pedidos pagados
    productos: pd.DataFrame  # catálogo con precio real y costo efectivo
    clientes: pd.DataFrame
    diario: pd.DataFrame     # una fila por fecha de dim_fecha, con pedidos, ingresos, domicilios


def conectar():
    """Conexión de solo lectura: el análisis nunca escribe en la base."""
    return sqlite3.connect(f"file:{DB_RUTA.as_posix()}?mode=ro", uri=True)


def _periodo(fechas):
    return pd.Series(np.select(
        [fechas < INICIO_BASE, fechas <= FIN_BASE, fechas <= FIN_CAIDA],
        ["arranque", "base", "caida"], default="incompleto"), index=fechas.index)


def estimar_costos(productos):
    """Aplica la regla de costo faltante con la misma función que usa la plataforma.

    Agrega `costo` (real o estimado), `costo_estimado` (bool) y `razon_costo` (costo / precio de lista).
    """
    razones = razones_costo(zip(productos["category"], productos["unit_price"], productos["unit_cost"]))
    productos = productos.copy()
    productos["costo_estimado"] = [not costo_es_real(p, k) for p, k in zip(productos["unit_price"], productos["unit_cost"])]
    productos["costo"] = [costo_unitario(c, p, k, razones) for c, p, k in
                          zip(productos["category"], productos["unit_price"], productos["unit_cost"])]
    productos["razon_costo"] = productos["costo"] / productos["unit_price"]
    return productos


def cargar():
    con = conectar()
    try:
        ventas = pd.read_sql("SELECT * FROM sales", con, parse_dates=["created_at"])
        items = pd.read_sql("SELECT * FROM sale_items", con)
        productos = pd.read_sql("SELECT * FROM products", con)
        clientes = pd.read_sql("SELECT id, codigo_anonimo FROM customers", con)
        fechas = pd.read_sql("SELECT * FROM dim_fecha", con, parse_dates=["fecha"])
    finally:
        con.close()

    cancelados = int((ventas["status"] != "COMPLETED").sum())
    ventas = ventas[ventas["status"] == "COMPLETED"].copy()
    ventas["fecha"] = ventas["created_at"].dt.normalize()
    ventas["hora"] = ventas["created_at"].dt.hour
    ventas["dia_semana"] = ventas["fecha"].dt.day_of_week
    ventas["periodo"] = _periodo(ventas["fecha"])
    ventas["abierto"] = ventas["dia_semana"] != 1
    items = items[items["sale_id"].isin(ventas["id"])].copy()

    por_dia = ventas.groupby("fecha").agg(
        pedidos=("id", "count"), ingresos=("total_amount", "sum"),
        domicilios=("canal", lambda s: int((s == "domicilio").sum())))
    diario = fechas.merge(por_dia, how="left", left_on="fecha", right_index=True)
    diario[["pedidos", "ingresos", "domicilios"]] = diario[["pedidos", "ingresos", "domicilios"]].fillna(0)
    diario["periodo"] = _periodo(diario["fecha"])
    diario["abierto"] = diario["es_descanso"] == 0
    precio_real = items.groupby("product_id")["unit_price"].median()
    productos["precio_real"] = productos["id"].map(precio_real).fillna(productos["unit_price"])
    return Datos(ventas, cancelados, items, estimar_costos(productos), clientes, diario)


def valla_tukey(serie):
    """Valla inferior de Tukey: Q1 - 1,5 x IQR. Devuelve (q1, q3, iqr, valla)."""
    q1, q3 = serie.quantile(0.25), serie.quantile(0.75)
    return q1, q3, q3 - q1, q1 - 1.5 * (q3 - q1)


def dias_comparables(diario):
    """Días abiertos de los periodos base y caída (la muestra de las comparaciones)."""
    return diario[diario["abierto"] & diario["periodo"].isin(["base", "caida"])]
