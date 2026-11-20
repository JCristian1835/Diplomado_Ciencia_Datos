"""Genera las evidencias reproducibles (PNG) de los Objetivos 2 (análisis) y 3 (plataforma) del caso Red Rooster.

Uso (con el venv del backend):
    backend\\venv\\Scripts\\python documentos\\evidencias_objetivos_2_3\\generar_evidencias.py
    backend\\venv\\Scripts\\python documentos\\evidencias_objetivos_2_3\\generar_evidencias.py --solo-asesor   (o3_08b)

Todo se ejecuta sobre una COPIA de backend\\data\\red_rooster.db en C:\\rr_evid2 (variable RR_EVIDENCIAS_TRABAJO_2); no se
toca backend\\data\\*.db ni BD\\. Los scripts del análisis se ejecutan de nuevo con ANALISIS_DB apuntando a la copia.
Reutiliza las utilidades de documentos\\evidencias_objetivo_1 (paneles HTML, localización de código por AST, capturas).
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
PROYECTO = AQUI.parents[1]
BACKEND = PROYECTO / "backend"
ANALISIS = BACKEND / "analisis"
OBJ1 = AQUI.parent / "evidencias_objetivo_1"
TRABAJO = Path(os.environ.get("RR_EVIDENCIAS_TRABAJO_2", r"C:\rr_evid2"))
DB_COPIA = TRABAJO / "red_rooster.db"
DB_ORIGEN = BACKEND / "data" / "red_rooster.db"
SALIDAS = AQUI / "salidas"
HTML = SALIDAS / "html"
PY = BACKEND / "venv" / "Scripts" / "python.exe"

sys.dont_write_bytecode = True  # no tocar la carpeta del Objetivo 1 al importarla
sys.path.insert(0, str(OBJ1))
import generar_evidencias as g1  # noqa: E402  (importa paneles, localizadores de código y utilidades de servidores)
import paneles  # noqa: E402
from app.core.config import get_settings  # noqa: E402  (el módulo del Objetivo 1 ya puso backend en sys.path)

# El módulo del Objetivo 1 fija rutas propias al importarse: se redirigen a las de este objetivo.
os.environ["DATABASE_URL"] = f"sqlite:///{DB_COPIA.as_posix()}"
os.environ.pop("RED_ROOSTER_JSON", None)
FIGURAS: list[dict] = []
g1.HTML, g1.SALIDAS, g1.FIGURAS = HTML, SALIDAS, FIGURAS

lf, rf, rt = g1.linea_de, g1.rango_funcion, g1.rango_texto
SUFIJO_ESTADO = "Ejecutado sobre la copia de la BD (C:\\rr_evid2\\red_rooster.db, variable ANALISIS_DB); salida completa en "


# ------------------------------------------------------------------ registro de figuras

def etiquetar(desde: int, objetivo: int, ref: str, **extra) -> None:
    for f in FIGURAS[desde:]:
        f.update(objetivo=objetivo, ref=ref, **extra)


def codigo(ref, desc, objetivo, paso, ruta, segmentos, titulo, destacar=(), nota=None):
    n0 = len(FIGURAS)
    g1.codigo(f"{ref}_{desc}", paso, ruta, segmentos, titulo, destacar=destacar, maximo=90, nota=nota)
    etiquetar(n0, objetivo, ref)


def ancho_terminal(texto: str) -> int:
    """Ancho del panel según la línea más larga razonable (las demás se parten); 1100 px mínimo, como en el Objetivo 1."""
    mayor = max((len(l) for l in texto.splitlines() if len(l) <= 150), default=0)
    return max(paneles.ANCHO, int(mayor * 8.4 + 60))


def secciones(texto: str) -> list[list[str]]:
    """Parte la salida de un paso en bloques: el encabezado y cada sección que empieza con '--- '."""
    partes: list[list[str]] = [[]]
    for linea in texto.strip("\n").split("\n"):
        if linea.startswith("--- "):
            partes.append([])
        partes[-1].append(linea)
    return [[l for l in p] for p in partes]


def sin_blancos_al_final(lineas: list[str]) -> list[str]:
    while lineas and not lineas[-1].strip():
        lineas = lineas[:-1]
    return lineas


def terminal(ref, desc, objetivo, paso, titulo, comando, texto, mantener=None, maximo=48, cifras=None, nota=None,
             resaltar=(), prompt="PS backend> ", ubicacion="proyecto Diplomado · backend"):
    """Terminal con la salida real. `mantener`: títulos (subcadenas) de las secciones que se muestran; las demás se
    omiten con una marca visible. Si el resultado supera `maximo` líneas se parte en _p1, _p2... en límites de sección."""
    bloques, omitidas = [], []
    for k, parte in enumerate(secciones(texto)):
        titulo_sec = parte[0].strip("- ").strip() if parte[0].startswith("--- ") else None
        corto = re.split(r" \(| - ", titulo_sec)[0] if titulo_sec else None
        if mantener is not None and titulo_sec is not None and not any(m in titulo_sec for m in mantener):
            omitidas.append(corto)
            continue
        if omitidas:
            bloques[-1] += ["", f"[ ... secciones omitidas en la imagen: {'; '.join(omitidas)} ]"]
            omitidas = []
        bloques.append(sin_blancos_al_final(parte))
    if omitidas:
        bloques[-1] += ["", f"[ ... secciones omitidas en la imagen: {'; '.join(omitidas)} ]"]
    packs, actual = [], []
    for b in bloques:
        if actual and len(actual) + len(b) + 1 > maximo:
            packs.append(actual)
            actual = []
        actual += ([""] if actual else []) + b
    packs.append(actual)
    for k, lineas in enumerate(packs, 1):
        sufijo = f"_p{k}" if len(packs) > 1 else ""
        etiqueta = f" (parte {k} de {len(packs)})" if len(packs) > 1 else ""
        cuerpo = "\n".join(lineas)
        n0 = len(FIGURAS)
        g1.terminal(f"{ref}_{desc}{sufijo}", paso, titulo + etiqueta,
                    [(comando if k == 1 else comando + "   # continuación", cuerpo, prompt)], cifras, nota,
                    resaltar=resaltar, ubicacion=ubicacion)
        ancho = ancho_terminal(cuerpo)
        if ancho != paneles.ANCHO:
            ruta = HTML / f"{ref}_{desc}{sufijo}.html"
            ruta.write_text(ruta.read_text(encoding="utf-8").replace(f"width:{paneles.ANCHO}px", f"width:{ancho}px", 1),
                            encoding="utf-8")
        etiquetar(n0, objetivo, ref)


def dimensiones_png(ruta: Path) -> tuple[int, int]:
    with ruta.open("rb") as f:
        cabecera = f.read(24)
    return struct.unpack(">II", cabecera[16:24])


def copiar_grafica(ref, desc, paso, titulo, origen: Path, cifras=None, nota=None) -> None:
    id_ = f"{ref}_{desc}"
    shutil.copy2(origen, AQUI / f"{id_}.png")
    ancho, alto = dimensiones_png(AQUI / f"{id_}.png")
    n0 = len(FIGURAS)
    g1.registrar(id_, paso, "grafica", titulo, None, archivo_codigo=f"backend/analisis/{origen.name.split('_')[0]}_*.py",
                 cifras={**(cifras or {}), "dimensiones_px": [ancho, alto]},
                 nota=nota or f"Gráfica generada por el paso del análisis; se copia tal cual desde backend/analisis/salidas/{origen.name}.")
    etiquetar(n0, 2, ref)


# ------------------------------------------------------------------ Objetivo 2: análisis

def ejecutar_paso(nombre: str) -> str:
    r = subprocess.run([str(PY), "-m", f"analisis.{nombre}"], cwd=BACKEND, capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "ANALISIS_DB": DB_COPIA.as_posix(), "PYTHONIOENCODING": "utf-8"})
    if r.returncode:
        raise RuntimeError(f"{nombre} falló:\n{r.stderr[-1500:]}")
    return r.stdout.strip("\n")


def salida_json(nombre: str) -> dict:
    return json.loads((ANALISIS / "salidas" / f"{nombre}.json").read_text(encoding="utf-8"))


def objetivo2() -> None:
    comun = ANALISIS / "comun.py"
    codigo("o2_01a", "codigo_comun", 2, 1, comun,
           [(1, lf(comun, "La BD se abre siempre") + 1),
            (lf(comun, "INICIO_BASE ="), lf(comun, "UMBRAL_CASI_SIN_PEDIDOS =")),
            rf(comun, "conectar"), rf(comun, "estimar_costos"),
            rt(comun, "cargar", "cancelados = int(", "items = items[items"),
            rt(comun, "cargar", "precio_real = items", 'productos["precio_real"] =')],
           "Paquete de análisis: definiciones de periodos y día abierto, carga en solo lectura, precio real y costo",
           destacar=("mode=ro", 'ventas["abierto"]', 'ventas["periodo"]', "precio_real =", "costo_unitario("))

    a01 = ANALISIS / "a01_perfil_ventas.py"
    codigo("o2_02a", "codigo_a01", 2, 2, a01, [rf(a01, "por_mes"), rf(a01, "main")],
           "Paso 1, perfil de ventas: pedidos por día abierto de cada mes y orden de ejecución",
           destacar=("dias_abiertos =", "pedidos_abiertos =", 'groupby(v["fecha"]'))
    t01 = ejecutar_paso("a01_perfil_ventas")
    j = salida_json("a01_perfil_ventas")
    terminal("o2_02b", "terminal_a01", 2, 2, "Paso 1, perfil de ventas (resumen, meses y estadísticos por periodo)",
             "venv\\Scripts\\python -m analisis.a01_perfil_ventas", t01,
             mantener=("Resumen general", "por mes", "estadísticos descriptivos"),
             cifras={"pedidos_pagados": j["resumen"]["pedidos_pagados"], "ingresos": j["resumen"]["ingresos"],
                     "no_pagados": j["resumen"]["pedidos_no_pagados"],
                     "media_base": j["descriptivos_pedidos_por_dia_abierto"]["base"]["media"],
                     "media_caida": j["descriptivos_pedidos_por_dia_abierto"]["caida"]["media"],
                     "variacion_media": j["variacion_media"]},
             nota=SUFIJO_ESTADO + "backend/analisis/salidas/a01_perfil_ventas.txt; en la imagen se omiten las secciones "
                                  "por día, franja, canal, pago y hora (aparecen marcadas).",
             resaltar=("Variación de la media",))
    graficas = ANALISIS / "salidas"
    copiar_grafica("o2_02c", "grafica_mes", 2, "Pedidos por día abierto, por mes",
                   graficas / "a01_perfil_ventas_pedidos_por_dia_abierto_mes.png",
                   {"pedidos_por_dia_abierto": {m["mes"]: round(m["pedidos_por_dia_abierto"], 1) for m in j["por_mes"]}})

    a02 = ANALISIS / "a02_estacionalidad_anomalias.py"
    codigo("o2_03a", "codigo_a02", 2, 3, a02,
           [rf(a02, "con_indice"), rf(a02, "efecto_dia_semana"),
            rt(a02, "anomalias", "q1, q3, iqr, valla = valla_tukey", "marcados_base = c[")],
           "Paso 2, estacionalidad por día de la semana y días anómalos con la regla de Tukey",
           destacar=('c["indice"] =', "valla_tukey(", "marcados ="))
    t02 = ejecutar_paso("a02_estacionalidad_anomalias")
    j2 = salida_json("a02_estacionalidad_anomalias")
    copiar_grafica("o2_03b", "grafica_dia_semana", 3, "Pedidos por día de la semana, base contra caída",
                   graficas / "a02_estacionalidad_anomalias_pedidos_dia_semana_base_vs_caida.png",
                   {"variacion_por_dia": {d["dia"]: round(d["variacion"], 3) for d in j2["efecto_dia_semana"]["dias"]}})
    copiar_grafica("o2_03c", "grafica_serie_anomalias", 3, "Serie diaria de pedidos con los días anómalos",
                   graficas / "a02_estacionalidad_anomalias_serie_diaria_anomalias.png",
                   {"dias_casi_sin_pedidos": j2["casi_sin_pedidos"]["dias"], "valla_tukey": j2["tukey"]["valla_inferior"]})
    terminal("o2_03d", "terminal_a02", 2, 3, "Paso 2, estacionalidad y días anómalos",
             "venv\\Scripts\\python -m analisis.a02_estacionalidad_anomalias", t02,
             mantener=("día de la semana", "Tukey", "casi sin pedidos", "domicilio"),
             cifras={"valla_inferior_tukey": j2["tukey"]["valla_inferior"],
                     "dias_bajo_la_valla": len(j2["tukey"]["dias_anomalos"]),
                     "dias_casi_sin_pedidos": j2["casi_sin_pedidos"]["dias"],
                     "indice_festivo_dif": j2["efecto_festivo"]["diferencia_indice"],
                     "indice_quincena_dif": j2["efecto_quincena"]["diferencia_indice"]},
             nota=SUFIJO_ESTADO + "backend/analisis/salidas/a02_estacionalidad_anomalias.txt; se omiten las secciones "
                                  "de quincena y festivo (aparecen marcadas).",
             resaltar=("valla inferior", "casi sin pedidos"))

    a03 = ANALISIS / "a03_inferencia.py"
    codigo("o2_04a", "codigo_a03", 2, 4, a03,
           [rf(a03, "magnitud"), rf(a03, "mann_whitney"), rf(a03, "bootstrap_diferencia_medias"),
            rt(a03, "chi_cuadrado", "v = ventas[", "esperado_min =")],
           "Paso 3, inferencia: Mann-Whitney, delta de Cliff, bootstrap de la diferencia de medias y chi-cuadrado",
           destacar=("mannwhitneyu(", "delta =", "rng.choice(", "chi2_contingency(", "v_cramer ="))
    t03 = ejecutar_paso("a03_inferencia")
    j3 = salida_json("a03_inferencia")
    mw = j3["pedidos_por_dia_abierto"]
    terminal("o2_04b", "terminal_a03", 2, 4, "Paso 3, pruebas de inferencia", "venv\\Scripts\\python -m analisis.a03_inferencia",
             t03, maximo=36,
             cifras={"mann_whitney_U": mw["mann_whitney"]["U"], "mann_whitney_p": mw["mann_whitney"]["p"],
                     "delta_cliff": mw["mann_whitney"]["delta_cliff"], "ic95_bootstrap": mw["ic95_bootstrap"],
                     "sin_dias_casi_vacios_p": mw["sin_dias_casi_vacios"]["mann_whitney"]["p"],
                     "chi2_canal_periodo": j3["chi2_canal_periodo"]["chi2"], "chi2_p": j3["chi2_canal_periodo"]["p"]},
             nota=SUFIJO_ESTADO + "backend/analisis/salidas/a03_inferencia.txt; salida completa repartida en dos imágenes.",
             resaltar=("p = ", "p < ", "IC 95"))

    a04 = ANALISIS / "a04_descomposicion_caida.py"
    codigo("o2_05a", "codigo_a04", 2, 5, a04, [rf(a04, "resumen_periodo"), rf(a04, "descomponer")],
           "Paso 4, descomposición de la caída en domicilios, días casi sin pedidos y demanda en días normales",
           destacar=('partes = {', "porcentajes", "cuadre"))
    t04 = ejecutar_paso("a04_descomposicion_caida")
    j4 = salida_json("a04_descomposicion_caida")["descomposicion"]
    terminal("o2_05b", "terminal_a04", 2, 5, "Paso 4, descomposición de la caída",
             "venv\\Scripts\\python -m analisis.a04_descomposicion_caida", t04,
             cifras={"caida_total_pedidos_por_dia": j4["caida_total"],
                     "porcentajes": {k: round(v, 3) for k, v in j4["porcentajes"].items()}, "cuadra": j4["cuadre"]},
             nota=SUFIJO_ESTADO + "backend/analisis/salidas/a04_descomposicion_caida.txt.",
             resaltar=("Total de la caída", "cuadra"))
    copiar_grafica("o2_05c", "grafica_cascada", 5, "Cascada de la caída de pedidos por día abierto",
                   graficas / "a04_descomposicion_caida_cascada_caida.png",
                   {"porcentajes": {k: round(v, 3) for k, v in j4["porcentajes"].items()}})

    a05 = ANALISIS / "a05_demanda.py"
    codigo("o2_06a", "codigo_a05", 2, 6, a05,
           [rf(a05, "pares"), rf(a05, "entrenar_xgboost"), rf(a05, "pronostico_m1"), rf(a05, "validar"),
            rf(a05, "elegir_modelo")],
           "Paso 5, pronóstico de demanda: pares sin fuga de información, XGBoost, línea base y validación walk-forward",
           destacar=("hasta=origen", "& (t <= hasta)", "XGBRegressor(", "origen = fin -", "nivel[origen]"))
    t05 = ejecutar_paso("a05_demanda")
    j5 = salida_json("a05_demanda")
    terminal("o2_06b", "terminal_a05", 2, 6, "Paso 5, comparación de modelos e importancia de variables",
             "venv\\Scripts\\python -m analisis.a05_demanda", t05,
             mantener=("Comparación de modelos", "Importancia de variables"),
             cifras={"modelo_elegido": j5["modelo_elegido"], "mae_banda": j5["mae_banda"],
                     "mae_7d": {m: round(j5["metricas"]["7"][m]["mae"], 2) for m in ("M1", "M2", "M3")},
                     "mae_30d": {m: round(j5["metricas"]["30"][m]["mae"], 2) for m in ("M1", "M2", "M3")},
                     "importancia_xgboost": {k: round(v, 3) for k, v in j5["importancia_xgboost"].items()},
                     "pronostico_promedio_por_dia_abierto": j5["pronostico_promedio_por_dia_abierto"],
                     "pronostico_total_pedidos": j5["pronostico_total_pedidos"]},
             nota=SUFIJO_ESTADO + "backend/analisis/salidas/a05_demanda.txt; se omiten las ventanas de prueba y la tabla "
                                  "del pronóstico día a día (aparecen marcadas).",
             resaltar=("<- mejor", "Modelo usado"))
    copiar_grafica("o2_06c", "grafica_pronostico", 6, "Pronóstico de pedidos por día abierto a 30 días",
                   graficas / "a05_demanda_pronostico_30_dias.png",
                   {"modelo": j5["modelo_elegido"], "banda_mae": j5["mae_banda"]})

    a06 = ANALISIS / "a06_venta_cruzada.py"
    codigo("o2_07a", "codigo_a06", 2, 7, a06,
           [rt(a06, "reglas_de", "reglas = minar_reglas", "top = reglas"),
            rt(a06, "hallazgos_catalogo", "desviado =", '"costo_usado": r["costo"]})'),
            rf(a06, "armar_combo"), rt(a06, "combos", "pares = {}", "sugeridos = [armar_combo")],
           "Paso 6, venta cruzada: reglas Apriori, hallazgos de calidad del catálogo y armado de combos",
           destacar=("minar_reglas(", "TOLERANCIA_PRECIO", "DESCUENTO_COMBO", "LIFT_COMBO"))
    t06 = ejecutar_paso("a06_venta_cruzada")
    j6 = salida_json("a06_venta_cruzada")
    terminal("o2_07b", "terminal_a06", 2, 7, "Paso 6, venta cruzada: reglas, hallazgos del catálogo y combos",
             "venv\\Scripts\\python -m analisis.a06_venta_cruzada", t06,
             mantener=("Tamaño de la canasta", "Reglas Apriori", "Pedidos sin bebida", "Hallazgos", "Combos"),
             cifras={"reglas_por_producto": j6["apriori_producto"]["n_reglas"],
                     "reglas_por_categoria": j6["apriori_categoria"]["n_reglas"],
                     "lift_maximo_producto": j6["apriori_producto"]["lift_maximo"],
                     "pct_canastas_2_o_mas": j6["canastas"]["pct_con_2_o_mas"],
                     "pares_plato_bebida_lift_2": j6["combos"]["pares_candidatos"],
                     "combos_sugeridos": [f'{c["plato"]} + {c["bebida"]}' for c in j6["combos"]["sugeridos"]],
                     "hallazgos_catalogo": [h["producto"] for h in j6["hallazgos_catalogo"]]},
             nota=SUFIJO_ESTADO + "backend/analisis/salidas/a06_venta_cruzada.txt; se omite la tabla de margen por "
                                  "producto (aparece marcada).",
             resaltar=("Número de reglas", "Pares plato"))
    copiar_grafica("o2_07c", "grafica_sin_bebida", 7, "Pedidos sin bebida por categoría de plato",
                   graficas / "a06_venta_cruzada_pedidos_sin_bebida.png",
                   {"pct_sin_bebida": {f["categoria"]: round(f["pct_sin_bebida"], 3) for f in j6["sin_bebida"]["por_categoria"]},
                    "todos_los_platos": round(j6["sin_bebida"]["total"]["pct_sin_bebida"], 3)})

    a07 = ANALISIS / "a07_segmentacion.py"
    codigo("o2_08a", "codigo_a07", 2, 8, a07,
           [(lf(a07, "# Reglas de segmento"), lf(a07, "]", lf(a07, "SEGMENTOS = ["))), rf(a07, "puntaje"),
            rf(a07, "asignar_segmentos"), rt(a07, "kmeans", "X = StandardScaler", "etiquetas = modelos")],
           "Paso 7, segmentación: reglas de segmento RFM, puntajes por quintiles y K-Means",
           destacar=("SEGMENTOS = [", "quantile(", "KMeans(", "silhouette_score("))
    t07 = ejecutar_paso("a07_segmentacion")
    j7 = salida_json("a07_segmentacion")
    terminal("o2_08b", "terminal_a07", 2, 8, "Paso 7, segmentación RFM y K-Means", "venv\\Scripts\\python -m analisis.a07_segmentacion",
             t07, maximo=40,
             cifras={"clientes_segmentados": sum(s["clientes"] for s in j7["segmentos"]["tabla"]),
                     "dinero_total": j7["segmentos"]["dinero_total"],
                     "k_kmeans": j7["kmeans"]["mejor_k"], "silueta": j7["kmeans"]["silueta_mejor"],
                     "rand_ajustado": j7["kmeans"]["rand_ajustado_vs_reglas"]},
             nota=SUFIJO_ESTADO + "backend/analisis/salidas/a07_segmentacion.txt; solo agregados y códigos anónimos C###.",
             resaltar=("<- mejor", "Total:"))
    copiar_grafica("o2_08c", "grafica_clientes_dinero", 8, "Participación de cada segmento en clientes y dinero",
                   graficas / "a07_segmentacion_clientes_vs_dinero.png", {"k_kmeans": j7["kmeans"]["mejor_k"]})

    comando = "venv\\Scripts\\python -m pytest tests/analisis -v"
    r = subprocess.run([str(PY), "-m", "pytest", "tests/analisis", "-v"], cwd=BACKEND, capture_output=True, text=True,
                       encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    salida = (r.stdout + r.stderr).strip()
    g1.guardar_texto("o2_09a_pruebas_analisis", salida)
    resumen = salida.splitlines()[-1]
    mitad = len(salida.splitlines()) // 2
    lineas = salida.splitlines()
    for k, trozo in enumerate((lineas[:mitad], lineas[mitad:]), 1):
        n0 = len(FIGURAS)
        cuerpo = "\n".join(trozo)
        g1.terminal(f"o2_09a_terminal_pruebas_p{k}", 9, f"Pruebas del paquete de análisis (pytest -v), parte {k} de 2",
                    [(comando if k == 1 else comando + "   # continuación", cuerpo, "PS backend> ")],
                    {"resumen": resumen.strip("= "), "codigo_salida": r.returncode,
                     **{kw: int(v) for v, kw in re.findall(r"(\d+) (passed|failed|errors?|skipped)", resumen)}},
                    "Salida real de pytest; la segunda imagen continúa la lista y trae el resumen final.",
                    resaltar=("FAILED", "ERROR", " passed", " failed"))
        ruta = HTML / f"o2_09a_terminal_pruebas_p{k}.html"
        ruta.write_text(ruta.read_text(encoding="utf-8").replace(f"width:{paneles.ANCHO}px",
                                                                 f"width:{ancho_terminal(cuerpo)}px", 1), encoding="utf-8")
        etiquetar(n0, 2, "o2_09a")


# ------------------------------------------------------------------ Objetivo 3: plataforma

def diagrama_arquitectura() -> str:
    """Diagrama hexagonal de la plataforma y flujo ETL -> modelos -> analytics_* -> tableros/asesor (SVG propio)."""
    s = ['<defs><marker id="pta" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto">'
         '<path d="M0,0 L10,5 L0,10 z" fill="#4a5563"/></marker></defs>']

    def caja(x, y, w, titulo, lineas, relleno, borde, tam=14):
        h = 46 + 20 * len(lineas) + 12
        s.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{relleno}" stroke="{borde}" stroke-width="1.6"/>'
                 f'<text x="{x + 12}" y="{y + 25}" font-size="16" font-weight="700" fill="#1f2933">{titulo}</text>')
        for i, linea in enumerate(lineas):
            s.append(f'<text x="{x + 12}" y="{y + 48 + i * 20}" font-size="{tam}" fill="#2f3a48">{linea}</text>')
        return h

    def flecha(puntos, discontinua=False):
        trazo = ' stroke-dasharray="6 5"' if discontinua else ""
        s.append(f'<polyline points="{puntos}" fill="none" stroke="#4a5563" stroke-width="2"{trazo} marker-end="url(#pta)"/>')

    def etiqueta(x, y, texto, ancla="start"):
        s.append(f'<text x="{x}" y="{y}" font-size="13" font-weight="600" fill="#4a5563" text-anchor="{ancla}">{texto}</text>')

    # columna izquierda: capas de la arquitectura hexagonal (ancho 560)
    s.append('<text x="20" y="26" font-size="16" font-weight="700" fill="#4a5563">Arquitectura hexagonal (backend/app)</text>')
    capas = [("1 · Frontend React + Vite (puerto 5180)", ["Inicio · Analítica · Clientes · Asesor · Datos · POS · Productos",
                                                          "Cliente HTTP con JWT (services/api.ts)"], "#e8f1fb", "#4f86c6"),
             ("2 · API FastAPI (puerto 8010), adaptadores de entrada", ["/api/v1: auth · products · customers · sales · inventory",
                                                                        "kpis · analytics · advisor · etl   (JWT y esquemas Pydantic)"],
              "#e9f6ec", "#4f9a63"),
             ("3 · Casos de uso (application/ y etl/pipeline.py)", ["ServicioAnalitica · ServicioKpis · ServicioAsesor (guardrails)",
                                                                   "PipelineETL: extraer, transformar, entrenar y cargar"],
              "#f3ecfa", "#8a63b8"),
             ("4 · Puertos (domain/ports.py, Protocol)", ["AnalyticsRepo · SaleRepo · CustomerRepo · EtlRunRepo",
                                                          "AdvisorPort · CipherPort    (domain no importa adapters)"],
              "#fff8e1", "#c9a227")]
    y = 36
    for titulo, lineas, relleno, borde in capas:
        h = caja(20, y, 560, titulo, lineas, relleno, borde)
        if y > 36:
            flecha(f"300,{y - 18} 300,{y - 2}")
        y += h + 18
    y += 26  # espacio para el rótulo de los adaptadores
    flecha(f"300,{y - 44} 300,{y - 2}")
    y_ad = y
    adaptadores = [("Fernet", ["crypto/", "cifra correo y", "teléfono"], 20), ("Gemini", ["llm/", "con IA o modo", "simulado"], 166),
                   ("ML", ["ml/ (DataFrames)", "XGBoost · Apriori", "K-Means RFM"], 312), ("SQLite", ["persistence/", "SQLAlchemy", "red_rooster.db"], 458)]
    for titulo, lineas, x in adaptadores:
        caja(x, y_ad, 122, titulo, lineas, "#f4f6f8", "#4a5563", tam=13)
    s.append(f'<text x="20" y="{y_ad - 8}" font-size="13" font-weight="600" fill="#4a5563">5 · Adaptadores de salida y modelos</text>')
    alto_ad = 46 + 20 * 3 + 12
    s.append(f'<text x="20" y="{y_ad + alto_ad + 28}" font-size="14" fill="#2f3a48">Sentido de las dependencias: frontend → API → casos de uso → puertos ← adaptadores.</text>')
    s.append(f'<text x="20" y="{y_ad + alto_ad + 50}" font-size="14" fill="#2f3a48">etl/ y ml/ trabajan sobre DataFrames y puertos, sin SQLAlchemy.</text>')

    # columna derecha: flujo de datos (ancho 380)
    xr, wr = 700, 380
    s.append(f'<text x="{xr}" y="26" font-size="16" font-weight="700" fill="#4a5563">Flujo de datos</text>')
    pasos = [("BD/pedidos.json · productos.json", ["Fuente real (no se versiona)"], "#fff8e1", "#c9a227"),
             ("ETL de carga (etl/red_rooster.py)", ["importar(): upsert de sales, sale_items,", "customers y products; reconstruir():",
                                                    "dim_fecha, ventas_diarias, calidad_datos"], "#e9f6ec", "#4f9a63"),
             ("Pipeline de modelos (etl/pipeline.py)", ["Extrae por watermark, imputa costos y entrena:", "XGBoost (demanda) · Apriori · K-Means",
                                                        "Registra la corrida en etl_runs"], "#f3ecfa", "#8a63b8")]
    y = 36
    for titulo, lineas, relleno, borde in pasos:
        h = caja(xr, y, wr, titulo, lineas, relleno, borde)
        flecha(f"{xr + wr // 2},{y + h} {xr + wr // 2},{y + h + 18}") if titulo.startswith(("BD", "ETL")) else None
        y += h + 18
    flecha(f"{xr + wr // 2},{y - 18} {xr + wr // 2},{y_ad - 2}")
    h_tab = caja(xr, y_ad, wr, "Tablas analytics_* y etl_runs (SQLite)",
                 ["analytics_demand_forecast", "analytics_market_basket_rules", "analytics_customer_segments",
                  "etl_runs (MAE, R², n_reglas, k, silueta)"], "#f4f6f8", "#4a5563")
    flecha(f"{458 + 122},{y_ad + alto_ad // 2} {xr - 2},{y_ad + alto_ad // 2}", True)
    etiqueta(640, y_ad + alto_ad // 2 - 8, "lee y escribe", "middle")
    y_c = y_ad + h_tab + 18
    flecha(f"{xr + wr // 2},{y_ad + h_tab} {xr + wr // 2},{y_c - 2}")
    caja(xr, y_c, wr, "Consumo", ["Tableros Inicio y Analítica (/kpis, /analytics)", "Asesor: contexto analítico → Gemini →",
                                  "guardrails (máx. 30 % de descuento)"], "#e8f1fb", "#4f86c6")
    alto = y_c + 46 + 20 * 3 + 12 + 20
    cab = ('<div class="cab"><span>Arquitectura de la plataforma Red Rooster</span>'
           '<span class="der">React → FastAPI → casos de uso → puertos → adaptadores · ETL → modelos → analytics_*</span></div>')
    return paneles._pagina("Arquitectura de la plataforma",
                           f'<div class="panel">{cab}<svg width="{paneles.ANCHO - 2}" height="{alto}" viewBox="0 0 {paneles.ANCHO - 2} {alto}" '
                           f'role="img" aria-label="Diagrama de la arquitectura de la plataforma"><rect width="100%" height="100%" fill="#fff"/>'
                           f'{"".join(s)}</svg></div>')


def panel_codigo_dos(archivos: list[tuple[Path, list[tuple[int, int]]]], titulo: str, destacar=()) -> str:
    """Un solo panel con el código de varios archivos (cada uno con su cabecera y números de línea reales)."""
    inner = []
    for ruta, segmentos in archivos:
        pagina = paneles.panel_codigo(g1.ruta_rel(ruta), g1._fuente(ruta), segmentos, destacar)
        inner.append(re.search(r'<div class="panel">(.*)</div></body></html>', pagina, re.S).group(1))
    return paneles._pagina(titulo, '<div class="panel">' + "".join(inner) + "</div>")


def objetivo3_codigo() -> None:
    app = BACKEND / "app"
    config, env = app / "core" / "config.py", BACKEND / ".env.example"
    seg_cfg, seg_env = (lf(config, "gemini_api_key:"), lf(config, "demanda_test_dias:")), (
        lf(env, "APRIORI_MIN_SUPPORT"), lf(env, "APRIORI_MIN_LIFT"))
    n0 = len(FIGURAS)
    g1.registrar("o3_02a_codigo_umbrales", 2, "codigo", "Umbrales de Apriori y Gemini: valores por defecto y archivo de ejemplo",
                 panel_codigo_dos([(config, [seg_cfg]), (env, [seg_env])], "Umbrales", destacar=("apriori_min", "APRIORI_MIN")),
                 archivo_codigo=f"{g1.ruta_rel(config)} · {g1.ruta_rel(env)}", lineas=[list(seg_cfg), list(seg_env)],
                 lineas_texto=f"{seg_cfg[0]}-{seg_cfg[1]} y {seg_env[0]}-{seg_env[1]}",
                 nota="Se muestra .env.example (plantilla sin secretos); el .env real no se publica.")
    etiquetar(n0, 3, "o3_02a")
    costos = app / "domain" / "costos.py"
    codigo("o3_02b", "codigo_costos", 3, 2, costos, [(1, len(g1._fuente(costos)))],
           "Regla única del costo faltante (domain/costos.py)", destacar=("0 < costo < precio", "por_categoria.get("))
    rfm = app / "ml" / "rfm_kmeans.py"
    codigo("o3_03a", "codigo_etiquetas_rfm", 3, 3, rfm,
           [(lf(rfm, "# Etiquetas de mejor a peor"), g1.rango_asignaciones(rfm, ("_ETIQUETAS_POR_K",))[1]), rf(rfm, "_etiquetar")],
           "Etiquetas de segmento por número de clusters y asignación por puntaje RFM",
           destacar=("_ETIQUETAS_POR_K[", "orden =", '"Nuevos"'))
    asesor = app / "application" / "asesor.py"
    codigo("o3_08a", "codigo_guardrails", 3, 8, asesor, [rf(asesor, "_cifras_inexistentes"), rf(asesor, "aplicar_guardrails")],
           "Asesor: verificación de cifras citadas y guardrails (descuento máximo y datos obligatorios)",
           destacar=("inventadas =", "if descuento >", "descuento = max(", "if not citados"))


def sql_una_fila(consulta: str):
    cols, filas = g1.sql(DB_COPIA, consulta)
    return dict(zip(cols, filas[0]))


def preparar() -> None:
    TRABAJO.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DB_ORIGEN, DB_COPIA)
    asegurar_playwright()


def asegurar_playwright() -> None:
    """playwright-core: el de frontend/node_modules si existe; si no, se instala fuera del proyecto (en la carpeta de trabajo)."""
    if (PROYECTO / "frontend" / "node_modules" / "playwright-core" / "index.mjs").is_file():
        return
    destino = TRABAJO / "pw"
    if not (destino / "node_modules" / "playwright-core" / "index.mjs").is_file():
        destino.mkdir(exist_ok=True)
        subprocess.run(["npm.cmd", "init", "-y"], cwd=destino, check=True, capture_output=True)
        subprocess.run(["npm.cmd", "install", "playwright-core"], cwd=destino, check=True, capture_output=True)
    os.environ["PLAYWRIGHT_CORE"] = str(destino / "node_modules" / "playwright-core")


@contextlib.contextmanager
def servidores():
    """Backend (8010) y frontend (5180) sobre la COPIA; en modo «synthetic» no recarga el JSON al arrancar."""
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{DB_COPIA.as_posix()}", "DATA_SOURCE_MODE": "synthetic",
           "SEED_ON_EMPTY": "false", "PYTHONIOENCODING": "utf-8"}
    back = front = None
    try:
        back = subprocess.Popen([str(PY), "-m", "uvicorn", "app.main:app", "--port", "8010"], cwd=BACKEND, env=env,
                                stdout=(TRABAJO / "backend.log").open("w"), stderr=subprocess.STDOUT)
        front = subprocess.Popen(["node", "node_modules/vite/bin/vite.js"], cwd=PROYECTO / "frontend", env=env,
                                 stdout=(TRABAJO / "frontend.log").open("w"), stderr=subprocess.STDOUT)
        g1.esperar(f"{g1.API}/api/v1/health")
        g1.esperar(g1.FRONT)
        yield
    finally:
        g1.detener(front)
        g1.detener(back)


def tiene_clave_gemini() -> bool:
    return bool(get_settings().gemini_api_key.strip())


def capturar_app(modo: str, datos_json: Path) -> dict:
    cfg = get_settings()
    entorno = {**os.environ, "RR_USER": cfg.admin_user, "RR_PASS": cfg.admin_password}
    subprocess.run(["node", str(AQUI / "capturar.mjs"), modo, str(AQUI), str(datos_json)], check=True, env=entorno)
    return json.loads(datos_json.read_text(encoding="utf-8"))


def objetivo3_app(datos: dict, token: str) -> None:
    api = lambda ruta: g1.http("GET", f"/api/v1{ruta}", token)[1]  # noqa: E731
    metricas, kpis = api("/analytics/metrics"), api("/kpis/resumen?dias=30&top=8")
    segmentos, reglas = api("/analytics/segments"), api("/analytics/basket?limit=100")
    runs = api("/etl/runs?limit=20")
    det = metricas["detalle"]

    def app_fig(ref, desc, paso, titulo, cifras, nota=None, comando=None):
        n0 = len(FIGURAS)
        g1.registrar(f"{ref}_{desc}", paso, "app", titulo, None, cifras=cifras, comando=comando, nota=nota)
        etiquetar(n0, 3, ref)

    app_fig("o3_04a", "app_datos_antes", 4, "Página Datos antes de ejecutar el pipeline",
            {"metricas_visibles": datos["datos_antes"]["metricas"], "corridas_en_historial": datos["datos_antes"]["corridas"]},
            "Corrida previa de la copia de la BD: se hizo con los umbrales antiguos de Apriori (soporte 0,02; confianza 0,3; lift 1,2).")
    app_fig("o3_04b", "app_datos_despues", 4, "Página Datos después de «Ejecutar pipeline» con «Forzar reentrenamiento»",
            {"metricas_visibles": datos["datos_despues"]["metricas"], "corridas_en_historial": datos["datos_despues"]["corridas"],
             "aviso": datos["aviso_pipeline"], "ultima_corrida_api": {k: runs[0][k] for k in ("id", "status", "rows_extracted")}})
    consulta = """SELECT id, status AS estado, rows_extracted AS filas,
       round(json_extract(metrics,'$.demanda.mae'),4) AS mae, round(json_extract(metrics,'$.demanda.r2'),4) AS r2,
       round(json_extract(metrics,'$.demanda.mae_baseline_lag7'),4) AS mae_base_lag7,
       round(json_extract(metrics,'$.demanda.r2_baseline_lag7'),4) AS r2_base_lag7,
       json_extract(metrics,'$.canasta.n_canastas') AS canastas, json_extract(metrics,'$.canasta.n_reglas') AS n_reglas,
       json_extract(metrics,'$.segmentos.k') AS k, round(json_extract(metrics,'$.segmentos.silhouette'),4) AS silueta,
       json_extract(metrics,'$.segmentos.n_clientes') AS n_clientes
FROM etl_runs ORDER BY id DESC LIMIT 1;"""
    c = sql_una_fila(consulta)
    tabla = paneles.tabla_texto(list(c), [[c[k] for k in c]], "r" * len(c))
    n0 = len(FIGURAS)
    g1.terminal("o3_04c_terminal_etl_runs", 4, "Consulta de la última fila de etl_runs (métricas de la corrida)",
                [(consulta, f"{tabla}\n(1 fila)", "sqlite> ")], {**c, "r2_en_la_plataforma": metricas["r2"]},
                "Consulta de solo lectura sobre la copia de la BD, después de la corrida forzada.",
                resaltar=("(1 fila)",), ubicacion="copia de SQLite · etl_runs")
    etiquetar(n0, 3, "o3_04c")
    app_fig("o3_05a", "app_inicio_kpis", 5, "Inicio: indicadores de los últimos 30 días",
            {"tarjetas_visibles": datos["inicio"]["tarjetas"],
             "api_kpis_30d": {k: kpis[k] for k in ("total_ventas", "n_ventas", "unidades_vendidas", "ticket_promedio", "margen",
                                                   "margen_pct", "rotacion", "valor_inventario") if k in kpis}})
    app_fig("o3_06a", "app_analitica_demanda", 6, "Analítica, pestaña Demanda",
            {"pastillas_visibles": datos["demanda"]["pastillas"], "mae": metricas["mae"], "r2": metricas["r2"],
             "baseline_lag7_mae": det["demanda"]["mae_baseline_lag7"]})
    app_fig("o3_06b", "app_analitica_venta_cruzada", 6, "Analítica, pestaña Venta cruzada",
            {"reglas_en_api": len(reglas), "filas_visibles": datos["cruzada"]["filas"], "primeras_reglas": datos["cruzada"]["primeras"],
             "n_reglas_metricas": metricas["n_reglas"], "lift_max": det["canasta"]["lift_max"]})
    app_fig("o3_06c", "app_analitica_segmentos", 6, "Analítica, pestaña Segmentos con el tooltip de un punto RFM",
            {"pastillas_visibles": datos["segmentos"]["pastillas"], "tooltip": datos["segmentos"]["tooltip"],
             "segmentos": [{"segmento": s["segmento"], "clientes": s["n_clientes"]} for s in segmentos["resumen"]],
             "k": metricas["k"], "silueta": metricas["silhouette"]})
    app_fig("o3_07a", "app_clientes_busqueda", 7, "Clientes con la búsqueda «C001» aplicada",
            {"busqueda": "C001", "filas_visibles": datos["clientes"]["filas"], "codigos": datos["clientes"]["codigos"]})
    app_fig("o3_09a", "swagger_analytics", 9, "Swagger: sección analytics con GET /analytics/segments ejecutado",
            {"codigo_http": datos["swagger"]["codigo"], "clientes_en_respuesta": len(segmentos["clientes"]),
             "campos_de_cliente": sorted(segmentos["clientes"][0]) if segmentos["clientes"] else [],
             "ejemplo_codigo_anonimo": segmentos["clientes"][0].get("codigo_anonimo") if segmentos["clientes"] else None})


def pendiente_asesor() -> None:
    n0 = len(FIGURAS)
    g1.registrar("o3_08b_app_asesor", 8, "app", "Asesor con una pregunta real y su respuesta", None, estado="pendiente",
                 archivo=None, nota="PENDIENTE: requiere GEMINI_API_KEY en backend/.env. Sin la clave, el asesor responde en modo "
                                    "«simulado» y no se captura como si fuera Gemini. Regenerar con --solo-asesor.")
    etiquetar(n0, 3, "o3_08b")


def asesor_app(datos_json: Path) -> dict:
    datos = capturar_app("asesor", datos_json)
    if datos["modo"] != "gemini":
        raise RuntimeError(f"La respuesta del asesor no fue de Gemini (modo={datos['modo']!r}); no se genera o3_08b")
    n0 = len(FIGURAS)
    g1.registrar("o3_08b_app_asesor", 8, "app", "Asesor con una pregunta real y su respuesta", None,
                 cifras={"modo": datos["modo"], "pregunta": datos["pregunta"], "acciones": datos["acciones"],
                         "resumen": datos["resumen"], "datos_citados": datos["datos_citados"],
                         "advertencias": datos["advertencias"]})
    etiquetar(n0, 3, "o3_08b")
    return datos


def objetivo3_pruebas() -> None:
    comando = "venv\\Scripts\\python -m pytest -q"
    r = subprocess.run([str(PY), "-m", "pytest", "-q"], cwd=BACKEND, capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    salida = (r.stdout + r.stderr).strip()
    resumen = salida.splitlines()[-1]
    n0 = len(FIGURAS)
    g1.guardar_texto("o3_10a_pruebas_completa", salida)
    lineas = salida.splitlines()
    corte = next((k for k, l in enumerate(lineas) if "warnings summary" in l), None)
    if corte is not None:  # el detalle de advertencias de librerías no aporta a la evidencia
        lineas = lineas[:corte + 1] + ["[ ... detalle de las advertencias omitido en la imagen; completo en salidas/o3_10a_pruebas_completa.txt ]",
                                       "", resumen]
    g1.terminal("o3_10a_terminal_pytest", 10, "Suite completa de pruebas (pytest -q)", [(comando, "\n".join(lineas), "PS backend> ")],
                {"resumen": resumen.strip("= "), "codigo_salida": r.returncode,
                 **{kw: int(v) for v, kw in re.findall(r"(\d+) (passed|failed|errors?|skipped)", resumen)}},
                "Salida real de la suite completa (tests/unit, tests/api, tests/analisis).",
                resaltar=("passed", "failed", "FAILED", "ERROR"))
    etiquetar(n0, 3, "o3_10a")


# ------------------------------------------------------------------ orquestación

def escribir_manifiesto() -> None:
    figuras = sorted(FIGURAS, key=lambda f: f["id"])
    for orden, f in enumerate(figuras, 1):
        f["orden"] = orden
    manifiesto = {
        "generado": datetime.now().isoformat(timespec="seconds"), "carpeta_png": g1.ruta_rel(AQUI),
        "reproducir": "backend\\venv\\Scripts\\python documentos\\evidencias_objetivos_2_3\\generar_evidencias.py",
        "notas_generales": [
            "Las cifras salen de la ejecución real de este script sobre una copia de backend/data/red_rooster.db (C:\\rr_evid2).",
            "Los pasos del análisis (Objetivo 2) se ejecutan de nuevo con ANALISIS_DB apuntando a la copia; las gráficas se copian tal cual.",
            "Las capturas de la aplicación son de 1440 x 900 px a factor 2 sobre backend y frontend levantados contra la copia, con DATA_SOURCE_MODE=synthetic para que no recargue el JSON al arrancar.",
            "Salida de cada terminal en salidas/<id>.txt; HTML en salidas/html/; cifras de cada figura en salidas/registro.json."],
        "figuras": figuras}
    paneles.guardar(AQUI / "manifiesto.json", json.dumps(manifiesto, ensure_ascii=False, indent=2))
    paneles.guardar(SALIDAS / "registro.json", json.dumps(figuras, ensure_ascii=False, indent=2))


def capturar_html(prefijo: str = "") -> None:
    asegurar_playwright()
    subprocess.run(["node", str(OBJ1 / "capturar.mjs"), "html", str(HTML), str(AQUI), prefijo], check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo-pruebas", action="store_true", help="regenera solo la suite completa (o3_10a)")
    ap.add_argument("--solo-asesor", action="store_true", help="regenera solo la captura del asesor (o3_08b); requiere GEMINI_API_KEY")
    args = ap.parse_args()
    SALIDAS.mkdir(exist_ok=True)
    datos_json = SALIDAS / "app_datos.json"
    if args.solo_pruebas:
        FIGURAS.extend(f for f in json.loads((SALIDAS / "registro.json").read_text(encoding="utf-8")) if f["ref"] != "o3_10a")
        objetivo3_pruebas()
        escribir_manifiesto()
        capturar_html("o3_10a")
        return
    if args.solo_asesor:
        if not tiene_clave_gemini():
            sys.exit("No hay GEMINI_API_KEY en backend/.env: o3_08b sigue pendiente (no se captura el asesor simulado).")
        FIGURAS.extend(f for f in json.loads((SALIDAS / "registro.json").read_text(encoding="utf-8"))
                       if f["ref"] != "o3_08b")
        preparar()
        with servidores():
            asesor_app(SALIDAS / "app_asesor.json")
        escribir_manifiesto()
        return

    preparar()
    objetivo2()
    objetivo3_codigo()
    g1.registrar("o3_01a_arquitectura", 1, "diagrama", "Arquitectura de la plataforma y flujo de datos", diagrama_arquitectura(),
                 archivo_codigo="backend/app (adapters · application · domain · etl · ml) y frontend/src",
                 nota="Diagrama generado con nombres verificados contra la estructura de carpetas; no es una captura de una herramienta externa.")
    etiquetar(len(FIGURAS) - 1, 3, "o3_01a")
    cfg = get_settings()
    with servidores():
        token = g1.http("POST", "/api/v1/auth/login", cuerpo={"username": cfg.admin_user, "password": cfg.admin_password})[1]["access_token"]
        datos = capturar_app("app", datos_json)
        objetivo3_app(datos, token)
        if tiene_clave_gemini():
            asesor_app(SALIDAS / "app_asesor.json")
        else:
            pendiente_asesor()
    objetivo3_pruebas()
    escribir_manifiesto()
    capturar_html()


if __name__ == "__main__":
    main()
