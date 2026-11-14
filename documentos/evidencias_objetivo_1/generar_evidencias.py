"""Genera las evidencias reproducibles (PNG) del proceso ETL del caso Red Rooster.

Uso (desde cualquier carpeta, con el venv del backend):
    backend\\venv\\Scripts\\python documentos\\evidencias_objetivo_1\\generar_evidencias.py
    backend\\venv\\Scripts\\python documentos\\evidencias_objetivo_1\\generar_evidencias.py --solo-pruebas   (paso 14)

Todo se ejecuta sobre COPIAS del JSON y SQLite temporales en C:\\rr_evid (variable RR_EVIDENCIAS_TRABAJO);
no se toca backend\\data\\*.db ni BD\\*.json. Las salidas quedan en salidas\\ (texto y HTML) y los PNG junto a este script.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import copy
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

AQUI = Path(__file__).resolve().parent
PROYECTO = AQUI.parents[1]
BACKEND = PROYECTO / "backend"
BD_ORIGEN = PROYECTO / "BD"
TRABAJO = Path(os.environ.get("RR_EVIDENCIAS_TRABAJO", r"C:\rr_evid"))
SALIDAS = AQUI / "salidas"
HTML = SALIDAS / "html"
PY = BACKEND / "venv" / "Scripts" / "python.exe"
API = "http://localhost:8010"
FRONT = "http://localhost:5180"

DB_CARGA = TRABAJO / "db" / "carga.db"
DB_INC = TRABAJO / "db" / "incremental.db"
DB_VIG = TRABAJO / "db" / "vigilante.db"
ORIGEN = TRABAJO / "origen"
ORIGEN_INC = TRABAJO / "incremental"
ORIGEN_VIG = TRABAJO / "vigilante"

# Las importaciones de la aplicación se hacen contra rutas temporales, nunca contra backend\data.
os.environ["DATABASE_URL"] = f"sqlite:///{DB_CARGA.as_posix()}"
os.environ["RED_ROOSTER_JSON"] = str(ORIGEN / "pedidos.json")
sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings, obtener_clave_privacidad  # noqa: E402
from app.core.db import Base, crear_motor  # noqa: E402
from app.etl import red_rooster as rr  # noqa: E402
from app.etl import red_rooster_analitica as rra  # noqa: E402

import paneles  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

FIGURAS: list[dict] = []


# ------------------------------------------------------------------ utilidades generales

def miles(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def ruta_rel(ruta: Path) -> str:
    return ruta.relative_to(PROYECTO).as_posix()


def ejecutar(funcion, *args):
    """Ejecuta una función que imprime y devuelve (texto impreso, cifras)."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        cifras = funcion(*args)
    return buffer.getvalue(), cifras


def registrar(id_, paso, tipo, titulo, html=None, **extra):
    if html is not None:
        paneles.guardar(HTML / f"{id_}.html", html)
    FIGURAS.append({"id": id_, "archivo": f"{id_}.png", "paso": paso, "tipo": tipo, "titulo": titulo,
                    "archivo_codigo": None, "lineas": None, "comando": None, "cifras": {}, "nota": None, **extra})


def guardar_texto(id_: str, texto: str) -> None:
    paneles.guardar(SALIDAS / f"{id_}.txt", texto)


def terminal(id_, paso, titulo, bloques, cifras=None, nota=None, resaltar=(), ubicacion="proyecto Diplomado · backend"):
    texto = "\n\n".join(f"$ {b[0]}\n{b[1]}" for b in bloques)
    guardar_texto(id_, texto)
    comando = " && ".join(b[0].replace("\n", " ") for b in bloques)
    registrar(id_, paso, "terminal", titulo, paneles.panel_terminal(bloques, ubicacion=ubicacion, resaltar=resaltar),
              comando=comando, cifras=cifras or {}, nota=nota)


def ejecutar_script(comando_mostrado: str, funcion, *args):
    return ejecutar(funcion, *args), comando_mostrado


# ------------------------------------------------------------------ localizar código por nombre (sin números fijos)

def _fuente(ruta: Path) -> list[str]:
    lineas = re.split(r"\r\n|\r|\n", ruta.read_text(encoding="utf-8"))
    return lineas[:-1] if lineas and lineas[-1] == "" else lineas


def _nodos(ruta: Path, tipos):
    return [n for n in ast.walk(ast.parse(ruta.read_text(encoding="utf-8"))) if isinstance(n, tipos)]


def rango_funcion(ruta: Path, nombre: str) -> tuple[int, int]:
    nodo = next(n for n in _nodos(ruta, (ast.FunctionDef, ast.AsyncFunctionDef)) if n.name == nombre)
    return min([d.lineno for d in nodo.decorator_list] + [nodo.lineno]), nodo.end_lineno


def rango_asignaciones(ruta: Path, nombres: tuple[str, ...]) -> tuple[int, int]:
    nodos = [n for n in ast.parse(ruta.read_text(encoding="utf-8")).body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id in nombres for t in n.targets)]
    return min(n.lineno for n in nodos), max(n.end_lineno for n in nodos)


def linea_de(ruta: Path, texto: str, desde: int = 1) -> int:
    for n, linea in enumerate(_fuente(ruta), 1):
        if n >= desde and texto in linea:
            return n
    raise LookupError(f"{texto!r} no está en {ruta.name} (desde la línea {desde})")


def rango_texto(ruta: Path, funcion: str, inicio: str, fin: str) -> tuple[int, int]:
    """Desde la primera línea con `inicio` dentro de la función hasta la primera con `fin` a continuación."""
    f_desde, f_hasta = rango_funcion(ruta, funcion)
    desde = linea_de(ruta, inicio, f_desde)
    hasta = linea_de(ruta, fin, desde)
    if hasta > f_hasta:
        raise LookupError(f"{fin!r} queda fuera de {funcion}")
    return desde, hasta


def rango_clase(ruta: Path, nombre: str) -> int:
    return next(n for n in _nodos(ruta, ast.ClassDef) if n.name == nombre).lineno


def _sangria(linea: str) -> int:
    return len(linea) - len(linea.lstrip())


def partir(ruta: Path, desde: int, hasta: int, maximo: int) -> list[tuple[int, int]]:
    """Divide un bloque largo en partes en límites de sentencia (cerca de la mitad)."""
    if hasta - desde + 1 <= maximo:
        return [(desde, hasta)]
    lineas = _fuente(ruta)
    umbral = _sangria(lineas[desde - 1]) + 8
    medio = (desde + hasta) // 2
    candidatos = [n for n in range(desde + 1, hasta + 1) if lineas[n - 1].strip() and _sangria(lineas[n - 1]) <= umbral
                  and not lineas[n - 1].lstrip().startswith(("except", "else", "elif", "finally"))]
    corte = min(candidatos, key=lambda n: abs(n - medio))
    izq, der = (desde, corte - 1), (corte, hasta)
    while not lineas[izq[1] - 1].strip():
        izq = (izq[0], izq[1] - 1)
    return partir(ruta, *izq, maximo) + partir(ruta, *der, maximo)


def codigo(id_, paso, ruta: Path, segmentos, titulo, destacar=(), maximo=45, nota=None):
    """Panel(es) de código; un bloque único se divide si supera `maximo` líneas."""
    partes = ([[s] for s in partir(ruta, *segmentos[0], maximo)] if len(segmentos) == 1 else [list(segmentos)])
    texto = _fuente(ruta)
    for k, parte in enumerate(partes, 1):
        sufijo = f"_p{k}" if len(partes) > 1 else ""
        etiqueta = f" (parte {k} de {len(partes)})" if len(partes) > 1 else ""
        registrar(f"{id_}{sufijo}", paso, "codigo", titulo + etiqueta,
                  paneles.panel_codigo(ruta_rel(ruta), texto, parte, destacar),
                  archivo_codigo=ruta_rel(ruta), lineas=[list(s) for s in parte],
                  lineas_texto=" y ".join(f"{d}-{h}" for d, h in parte), nota=nota)


# ------------------------------------------------------------------ entorno de trabajo

def preparar_trabajo() -> None:
    for sub in ("origen", "incremental", "vigilante", "db"):
        (TRABAJO / sub).mkdir(parents=True, exist_ok=True)
    for destino in (ORIGEN, ORIGEN_INC, ORIGEN_VIG):
        for nombre in ("pedidos.json", "productos.json"):
            shutil.copy2(BD_ORIGEN / nombre, destino / nombre)
    for db in (DB_CARGA, DB_INC, DB_VIG):
        db.write_bytes(b"")  # SQLite vacía: la aplicación crea las tablas al arrancar


def sql(db: Path, consulta: str):
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        cur = con.execute(consulta)
        filas = cur.fetchall()
        return [d[0] for d in cur.description], filas
    finally:
        con.close()


def salida_sql(db: Path, consulta: str, alinear=None) -> tuple[str, list, list]:
    encabezados, filas = sql(db, consulta)
    texto = paneles.tabla_texto(encabezados, [["NULL" if c is None else c for c in f] for f in filas], alinear)
    return f"{texto}\n({len(filas)} fila{'s' if len(filas) != 1 else ''})", encabezados, filas


def escalar(db: Path, consulta: str):
    return sql(db, consulta)[1][0][0]


def http(metodo: str, ruta: str, token: str | None = None, cuerpo=None):
    cabeceras = {"Content-Type": "application/json"}
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(API + ruta, method=metodo, headers=cabeceras,
                                 data=json.dumps(cuerpo).encode() if cuerpo is not None else None)
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.status, json.loads(r.read())


def esperar(url: str, segundos: int = 90) -> None:
    limite = time.time() + segundos
    while time.time() < limite:
        try:
            with urllib.request.urlopen(url, timeout=3):
                return
        except Exception:
            time.sleep(0.7)
    raise TimeoutError(f"No respondió {url}")


def detener(proceso) -> None:
    if proceso and proceso.poll() is None:
        subprocess.run(["taskkill", "/PID", str(proceso.pid), "/T", "/F"], capture_output=True)


@contextlib.contextmanager
def servidores():
    """Backend (8010) con BD temporal vacía y frontend (5180). En modo «synthetic» sin semilla no carga nada al arrancar."""
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{DB_CARGA.as_posix()}", "RED_ROOSTER_JSON": str(ORIGEN / "pedidos.json"),
           "DATA_SOURCE_MODE": "synthetic", "SEED_ON_EMPTY": "false", "PYTHONIOENCODING": "utf-8"}
    back = front = None
    try:
        back = subprocess.Popen([str(PY), "-m", "uvicorn", "app.main:app", "--port", "8010"], cwd=BACKEND, env=env,
                                stdout=(TRABAJO / "backend.log").open("w"), stderr=subprocess.STDOUT)
        front = subprocess.Popen(["node", "node_modules/vite/bin/vite.js"], cwd=PROYECTO / "frontend", env=env,
                                 stdout=(TRABAJO / "frontend.log").open("w"), stderr=subprocess.STDOUT)
        esperar(f"{API}/api/v1/health")
        esperar(FRONT)
        yield
    finally:
        detener(front)
        detener(back)


# ------------------------------------------------------------------ pasos 1 a 5 (no requieren servidor)

def paso1_arquitectura(pedidos, productos):
    etl = BACKEND / "app" / "etl"
    nombres = {"red_rooster.py": ("_leer_json", "_fingerprint", "_fecha", "canal_de", "_huella_cliente",
                                  "_asignar_codigos", "importar"),
               "red_rooster_analitica.py": ("_calidad", "reconstruir")}
    for archivo, funciones in nombres.items():
        existentes = {n.name for n in _nodos(etl / archivo, ast.FunctionDef)}
        assert set(funciones) <= existentes, (archivo, set(funciones) - existentes)
    assert "ESTADOS_PAGADOS" in (etl / "red_rooster.py").read_text(encoding="utf-8")
    etl_api = (BACKEND / "app/adapters/inbound/api/v1/etl.py").read_text(encoding="utf-8")
    assert 'prefix="/etl"' in etl_api and '@router.post("/import")' in etl_api
    assert "importar_red_rooster" in (BACKEND / "app/main.py").read_text(encoding="utf-8")
    assert (etl / "watch_red_rooster.py").is_file()
    tablas = ["products", "customers", "sales", "sale_items", "dim_fecha", "ventas_diarias", "calidad_datos",
              "source_import_runs"]
    import app.adapters.outbound.persistence.models  # noqa: F401  (registra las tablas)
    assert set(tablas) <= set(Base.metadata.tables), set(tablas) - set(Base.metadata.tables)
    reglas = len(rra._calidad(pedidos, productos))
    html = paneles.panel_diagrama(
        origenes=[f"BD/pedidos.json · {miles(len(pedidos))} pedidos", f"BD/productos.json · {len(productos)} productos"],
        disparadores=["POST /api/v1/etl/import", "Carga al iniciar (main.py)", "Vigilante (watch_red_rooster.py)"],
        extraer=["_leer_json: JSON en utf-8-sig", "_fingerprint: SHA-256 de ambos", "archivos (nombre + contenido)",
                 "Misma huella → SIN_CAMBIOS", "(salvo force=true)"],
        transformar=["_fecha: UTC/Bogotá → hora local", "canal_de: mesa/llevar/domicilio/sin_dato",
                     "ESTADOS_PAGADOS · PAGOS", "_huella_cliente: HMAC-SHA256", "_asignar_codigos: C001, C002…",
                     f"_calidad: {reglas} reglas de calidad"],
        cargar=["importar(): upsert por id en", "una sola transacción (commit al final)",
                "reconstruir(): dim_fecha,", "ventas_diarias, calidad_datos",
                "Registro de la corrida en", "source_import_runs"],
        tablas=tablas, motor="SQLite · backend/data/red_rooster.db")
    registrar("01a_arquitectura", 1, "diagrama", "Arquitectura del proceso ETL (extraer, transformar, cargar)", html,
              archivo_codigo="backend/app/etl/red_rooster.py · red_rooster_analitica.py · watch_red_rooster.py",
              cifras={"pedidos_origen": len(pedidos), "productos_origen": len(productos), "reglas_calidad": reglas,
                      "tablas_destino": tablas},
              nota="Diagrama generado con nombres verificados contra el código (funciones por AST y tablas por "
                   "Base.metadata); no es una captura de una herramienta externa.")


def perfil_fuente(ruta_pedidos: Path, ruta_productos: Path):
    pedidos, productos = rr._leer_json(ruta_pedidos), rr._leer_json(ruta_productos)
    con_valor = lambda k: sum(p.get(k) not in (None, "", []) for p in pedidos)  # noqa: E731
    instantes = [(datetime.fromisoformat(p["fecha"].replace("Z", "+00:00")), p["fecha"]) for p in pedidos]
    primero, ultimo = min(instantes)[1], max(instantes)[1]
    print(f"Archivo: {ruta_pedidos.name} ({miles(ruta_pedidos.stat().st_size)} bytes) · {ruta_productos.name} "
          f"({miles(ruta_productos.stat().st_size)} bytes)")
    print(f"Pedidos: {miles(len(pedidos))}   ids distintos: {miles(len({p['id'] for p in pedidos}))}   "
          f"id mínimo-máximo: {min(p['id'] for p in pedidos)}-{max(p['id'] for p in pedidos)}")
    print(f"Rango de fechas (comparado en UTC): {primero}  ->  {ultimo}")
    campos = list(dict.fromkeys(k for p in pedidos for k in p))
    print("\nCampos de cada pedido y pedidos que traen valor:")
    print(paneles.tabla_texto(["campo", "pedidos_con_valor"], [[k, miles(con_valor(k))] for k in campos], "lr"))
    personales = ["cliente", "telefono", "direccion", "nota", "ip"]
    print("\nCampos personales (solo conteos; no se muestran valores):")
    print(paneles.tabla_texto(["campo", "pedidos_con_valor", "valores_distintos"],
                              [[k, miles(con_valor(k)), miles(len({p[k] for p in pedidos if p.get(k)}))] for k in personales],
                              "lrr"))
    conteos = {}
    for campo in ("estado", "tipo", "metodo_pago"):
        c = Counter(p.get(campo) or "(vacío)" for p in pedidos)
        conteos[campo] = dict(c.most_common())
        print(f"\n{campo}: " + " · ".join(f"{k} {miles(v)}" for k, v in c.most_common()))
    lineas = [l for p in pedidos for l in p.get("productos") or []]
    sin_costo = sum(not q.get("costo") for q in productos)
    print(f"\nLíneas de pedido: {miles(len(lineas))}   pedidos sin líneas: {sum(not p.get('productos') for p in pedidos)}   "
          f"promedio de líneas por pedido: {len(lineas) / len(pedidos):.2f}")
    print(f"Catálogo: {len(productos)} productos · con costo 0 o vacío: {sin_costo}")
    return {"pedidos": len(pedidos), "ids_distintos": len({p["id"] for p in pedidos}), "fecha_primera_utc": primero,
            "fecha_ultima_utc": ultimo, "campos": campos, "personales_con_valor": {k: con_valor(k) for k in personales},
            "personales_distintos": {k: len({p[k] for p in pedidos if p.get(k)}) for k in personales}, **conteos,
            "lineas": len(lineas), "productos_catalogo": len(productos), "productos_costo_cero": sin_costo}


def paso2():
    (texto, cifras), cmd = ejecutar_script("python generar_evidencias.py   # paso 2: perfil_fuente(BD/pedidos.json, BD/productos.json)",
                                           perfil_fuente, ORIGEN / "pedidos.json", ORIGEN / "productos.json")
    terminal("02a_perfil_fuente", 2, "Perfil de la fuente: BD/pedidos.json y BD/productos.json", [(cmd, texto, "$ ")],
             cifras, "Solo conteos: ningún valor personal aparece en la salida.")


def paso3():
    cfg = BACKEND / "app" / "core" / "config.py"
    clase = rango_clase(cfg, "Settings")
    campos = (linea_de(cfg, "red_rooster_json:"), linea_de(cfg, "data_privacy_key:"))
    codigo("03a_codigo_config", 3, cfg, [(clase, clase), campos, rango_funcion(cfg, "obtener_clave_privacidad")],
           "Configuración: ruta del origen y clave de privacidad", destacar=("red_rooster_json:", "data_privacy_key:"))

    def ps(comando: str) -> str:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", comando], cwd=PROYECTO, capture_output=True,
                           text=True, encoding="utf-8")
        return (r.stdout + r.stderr).strip()

    clave = BACKEND / "data" / ".privacy_key"
    bloques = [(c, ps(c), "PS proyecto> ") for c in (
        r"Get-Content .gitignore", r"Get-Content backend\.gitignore", r"Test-Path backend\data\.privacy_key",
        r"(Get-Content backend\data\.privacy_key -Raw).Trim().Length")]
    bloques[3] = (bloques[3][0] + "   # solo la longitud; el valor nunca se imprime", bloques[3][1], "PS proyecto> ")
    terminal("03b_terminal_seguridad", 3, "Archivos excluidos del repositorio y existencia de la clave de privacidad", bloques,
             {"gitignore_raiz_excluye_BD": any(l.strip() == "BD/" for l in bloques[0][1].splitlines()),
              "gitignore_raiz_excluye_privacy_key": "data/.privacy_key" in bloques[0][1],
              "gitignore_backend_excluye_privacy_key": "data/.privacy_key" in bloques[1][1],
              "privacy_key_existe": bloques[2][1] == "True", "privacy_key_longitud": int(bloques[3][1])},
             "El valor de la clave nunca se muestra.", resaltar=("BD/", "data/.privacy_key", "*.db"),
             ubicacion="proyecto Diplomado")


def paso4():
    ruta = BACKEND / "app" / "etl" / "red_rooster.py"
    codigo("04a_codigo_extraccion", 4, ruta, [(rango_funcion(ruta, "_leer_json")[0], rango_funcion(ruta, "_fingerprint")[1])],
           "Extracción: lectura del JSON y huella SHA-256 de los archivos de origen")

    def huella():
        p, c = ORIGEN / "pedidos.json", ORIGEN / "productos.json"
        for f in (p, c):
            print(f"{f.name:<15} {miles(f.stat().st_size):>10} bytes   elementos leídos: {len(rr._leer_json(f))}")
        h = rr._fingerprint(p, c)
        h2 = hashlib.sha256()
        for f in (p, c):
            h2.update(f.name.encode() + f.read_bytes())
        print(f"\n_fingerprint(pedidos.json, productos.json) = {h[:16]}…  ({len(h)} caracteres hexadecimales)")
        print(f"Cálculo independiente (hashlib): coincide = {h == h2.hexdigest()}")
        print(f"Segunda ejecución sobre los mismos archivos: misma huella = {h == rr._fingerprint(p, c)}")
        print(f"Huella de la copia == huella de BD/ originales: {h == rr._fingerprint(BD_ORIGEN / 'pedidos.json', BD_ORIGEN / 'productos.json')}")
        return {"huella_16": h[:16], "huella_longitud": len(h), "bytes_pedidos": p.stat().st_size,
                "bytes_productos": c.stat().st_size, "pedidos": len(rr._leer_json(p)),
                "productos": len(rr._leer_json(c)), "calculo_independiente_coincide": h == h2.hexdigest()}

    (texto, cifras), cmd = ejecutar_script("python generar_evidencias.py   # paso 4: rr._leer_json y rr._fingerprint sobre la copia de trabajo",
                                           huella)
    terminal("04b_terminal_huella", 4, "Huella SHA-256 del origen", [(cmd, texto, "$ ")], cifras,
             "La huella completa son 64 hex; en el documento basta citar los 16 primeros caracteres.")


def paso5(pedidos):
    ruta = BACKEND / "app" / "etl" / "red_rooster.py"
    codigo("05a_codigo_fecha", 5, ruta, [(linea_de(ruta, "BOGOTA ="),) * 2, rango_funcion(ruta, "_fecha")],
           "Fechas: conversión a hora local de Bogotá (UTC-5) sin zona", destacar=("astimezone(BOGOTA)",))

    def ejemplos():
        utc = [p for p in pedidos if p["fecha"].endswith("+00:00")]
        local = [p for p in pedidos if p["fecha"].endswith("-05:00")]
        cruza = next(p for p in utc if datetime.fromisoformat(p["fecha"]).hour < 5)
        elegidos = [("+00:00 (UTC)", utc[0]), ("-05:00 (Bogotá)", local[0]), ("+00:00 cambia de día", cruza)]
        filas = []
        for rotulo, p in elegidos:
            nuevo = rr._fecha(p["fecha"])
            filas.append([p["id"], rotulo, p["fecha"], nuevo.isoformat(sep=" ")])
        print(paneles.tabla_texto(["id", "caso", "fecha en el origen", "rr._fecha(...)"], filas, "rlll"))
        print(f"\nPedidos con desfase +00:00: {miles(len(utc))} · con -05:00: {miles(len(local))} · total {miles(len(utc) + len(local))}")
        return {"ejemplos": [{"id": f[0], "caso": f[1], "origen": f[2], "destino": f[3]} for f in filas],
                "pedidos_utc": len(utc), "pedidos_bogota": len(local)}

    (texto, cifras), cmd = ejecutar_script("python generar_evidencias.py   # paso 5: rr._fecha() sobre 3 pedidos reales", ejemplos)
    terminal("05b_terminal_fechas", 5, "Conversión de fechas: antes y después de _fecha()", [(cmd, texto, "$ ")], cifras,
             "Solo id y fecha; el tercer ejemplo muestra un pedido UTC que cae el día anterior en hora de Bogotá.")


# ------------------------------------------------------------------ pasos que usan la BD cargada por la aplicación

def paso6(pedidos):
    ruta = BACKEND / "app" / "etl" / "red_rooster.py"
    destino_est = lambda p: "COMPLETED" if str(p.get("estado") or "").lower() in rr.ESTADOS_PAGADOS else "CANCELLED"  # noqa: E731
    destino_pago = lambda p: rr.PAGOS.get(str(p.get("metodo_pago") or "").lower(), "EFECTIVO")  # noqa: E731
    codigo("06a_codigo_estandarizacion", 6, ruta,
           [rango_asignaciones(ruta, ("ESTADOS_PAGADOS", "PAGOS", "CANALES")), rango_funcion(ruta, "canal_de"),
            rango_texto(ruta, "importar", 'status = "COMPLETED"', "canal = canal_de(pedido)")],
           "Estandarización: estados, métodos de pago y canal", destacar=("ESTADOS_PAGADOS =", "PAGOS =", "CANALES ="))

    def mapeo():
        bloques, cifras = [], {}
        especificaciones = [("estado", "status", destino_est, "SELECT status AS destino, COUNT(*) AS n FROM sales GROUP BY status"),
                            ("metodo_pago", "payment_method", destino_pago,
                             "SELECT payment_method AS destino, COUNT(*) AS n FROM sales GROUP BY payment_method"),
                            ("tipo", "canal", rr.canal_de, "SELECT canal AS destino, COUNT(*) AS n FROM sales GROUP BY canal")]
        for origen, columna, destino, consulta in especificaciones:
            cuenta = Counter((p.get(origen) or "(vacío)", destino(p)) for p in pedidos)
            filas = [[o, d, miles(n)] for (o, d), n in sorted(cuenta.items(), key=lambda kv: -kv[1])]
            print(f"{origen} (origen)  ->  {columna} (destino)")
            print(paneles.tabla_texto([origen, columna, "pedidos"], filas, "llr"))
            esperado = Counter()
            for (o, d), n in cuenta.items():
                esperado[d] += n
            real = dict(sql(DB_CARGA, consulta)[1])
            coincide = dict(esperado) == real
            print(f"Verificación en SQLite ({consulta.split(' FROM')[0].replace('SELECT ', '').split(' AS')[0]} agrupado): "
                  f"coincide con la BD = {coincide}\n")
            cifras[origen] = {"mapeo": [{"origen": o, "destino": d, "pedidos": n} for (o, d), n in cuenta.items()],
                              "coincide_con_bd": coincide, "total": sum(cuenta.values())}
        return cifras

    (texto, cifras), cmd = ejecutar_script("python generar_evidencias.py   # paso 6: mapeo origen -> destino calculado con el código del ETL y cotejado con SQLite",
                                           mapeo)
    terminal("06b_terminal_mapeo", 6, "Mapeo origen → destino con conteos reales", [(cmd, texto, "$ ")], cifras,
             "Los destinos se calculan con ESTADOS_PAGADOS, PAGOS y canal_de del código; el estado vacío/otro cae en CANCELLED y el pago vacío en EFECTIVO.")


def verificar_sin_pii(pedidos):
    """Busca en las tablas de datos los valores personales del JSON; solo se reportan conteos."""
    # Etiquetas de servicio que el origen guarda en «cliente» pero que no identifican a nadie.
    etiqueta = lambda v: v.lower() in ("llevar", "cliente") or re.fullmatch(r"mesa( \d+)?", v.lower())  # noqa: E731
    nombres = {str(p["cliente"]).strip() for p in pedidos if p.get("cliente")}
    etiquetas = {v for v in nombres if etiqueta(v)}
    nombres = {v for v in nombres - etiquetas if len(v) >= 3 and re.fullmatch(r"[^\W\d_]+(?: [^\W\d_]+)*", v)}
    telefonos = set()
    for p in pedidos:
        if p.get("telefono"):
            solo = re.sub(r"\D", "", str(p["telefono"]))
            telefonos |= {str(p["telefono"]).strip(), solo, solo[2:] if len(solo) == 12 and solo.startswith("57") else solo}
    direcciones = {" ".join(str(p["direccion"]).lower().split()) for p in pedidos if p.get("direccion")}
    ips = {str(p["ip"]) for p in pedidos if p.get("ip")}
    buscados = {"nombres": nombres, "telefonos": {v for v in telefonos if len(v) >= 7},
                "direcciones": {v for v in direcciones if len(v) >= 3}, "ips": ips}
    con = sqlite3.connect(f"file:{DB_CARGA.as_posix()}?mode=ro", uri=True)
    # products (catálogo de productos.json) y users no contienen campos del pedido; se omiten.
    omitidas = {"products", "users"}
    celdas, tablas, texto = 0, 0, []
    for (tabla,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
        if tabla in omitidas:
            continue
        tablas += 1
        for fila in con.execute(f'SELECT * FROM "{tabla}"'):
            for v in fila:
                if isinstance(v, str):
                    celdas += 1
                    texto.append(v.lower())
    con.close()
    pajar = "\n".join(texto)
    print(f"Tablas revisadas: {tablas} (se omiten {', '.join(sorted(omitidas))}) · celdas de texto revisadas: {miles(celdas)}")
    print(f"Búsqueda sin distinguir mayúsculas; nombres como palabra completa; se excluyen {len(etiquetas)} etiquetas de servicio "
          f"del campo cliente (Llevar, Cliente, Mesa, Mesa n)")
    encontrados = {}
    for categoria, valores in buscados.items():
        patron = (lambda v: rf"(?<!\w){re.escape(v.lower())}(?!\w)") if categoria == "nombres" else (lambda v: re.escape(v.lower()))
        hallados = [v for v in valores if re.search(patron(v), pajar)]
        encontrados[categoria] = len(hallados)
        print(f"  {categoria:<12} buscados (distintos): {miles(len(valores)):>5}   encontrados en la BD: {len(hallados)}")
    total = sum(encontrados.values())
    print(f"\nvalores personales del origen encontrados en la BD: {total}")
    return {"buscados": {k: len(v) for k, v in buscados.items()}, "encontrados": encontrados, "encontrados_total": total,
            "etiquetas_excluidas": len(etiquetas), "tablas_revisadas": tablas, "tablas_omitidas": sorted(omitidas),
            "celdas_texto_revisadas": celdas}


def paso7(pedidos):
    ruta = BACKEND / "app" / "etl" / "red_rooster.py"
    codigo("07a_codigo_anonimizacion", 7, ruta,
           [(rango_funcion(ruta, "_huella_cliente")[0], rango_funcion(ruta, "_asignar_codigos")[1])],
           "Anonimización: HMAC del teléfono y código C### por orden de primera compra",
           destacar=("hmac.new", 'f"C{siguiente:03d}"'))
    q1 = "PRAGMA table_info(customers);"
    q2 = ("SELECT id, codigo_anonimo, substr(source_key, 1, 12) AS source_key_12, first_name FROM customers "
          "ORDER BY id LIMIT 5;")
    q3 = ("SELECT COUNT(*) AS clientes, COUNT(DISTINCT source_key) AS source_key_distintas, "
          "COUNT(DISTINCT codigo_anonimo) AS codigos_distintos, MIN(codigo_anonimo) AS primero, "
          "MAX(codigo_anonimo) AS ultimo, COUNT(encrypted_email) AS con_email, COUNT(encrypted_phone) AS con_telefono "
          "FROM customers;")
    t1, _, _ = salida_sql(DB_CARGA, q1)
    t2, _, filas = salida_sql(DB_CARGA, q2)
    t3, _, f3 = salida_sql(DB_CARGA, q3)
    (t4, v), cmd = ejecutar_script("python generar_evidencias.py   # paso 7: buscar en TODAS las tablas los nombres, teléfonos, direcciones e IP del JSON",
                                   verificar_sin_pii, pedidos)
    c = dict(zip(["clientes", "source_key_distintas", "codigos_distintos", "primero", "ultimo", "con_email", "con_telefono"], f3[0]))
    terminal("07b_terminal_clientes", 7, "Clientes anonimizados en SQLite y verificación de ausencia de datos personales",
             [(q1, t1, "sqlite> "), (q2, t2, "sqlite> "), (q3, t3, "sqlite> "), (cmd, t4, "$ ")],
             {"columnas_customers": [r[1] for r in sql(DB_CARGA, q1)[1]], "muestra": [list(map(str, f)) for f in filas],
              **c, "verificacion": v}, "source_key se muestra truncado a 12 caracteres; first_name es el literal 'Cliente'.",
             resaltar=("encontrados en la BD: ",), ubicacion="SQLite temporal (carga.db) · base cargada por la aplicación")


def paso8(token):
    ruta = BACKEND / "app" / "etl" / "red_rooster_analitica.py"
    desde, hasta = rango_funcion(ruta, "_calidad")
    codigo("08a_codigo_calidad", 8, ruta, [(desde, hasta)], "Calidad de datos: nueve reglas medidas sobre el origen")
    estado, cuerpo = http("GET", "/api/v1/etl/quality", token)
    filas = [[r["regla"], miles(r["registros_afectados"])] for r in cuerpo["reglas"]]
    ancho = max(len(f[0]) for f in filas)
    lineas = [f"HTTP {estado} · reglas: {len(cuerpo['reglas'])}", ""]
    lineas += [paneles.tabla_texto(["regla", "registros_afectados"], filas, "lr"), ""]
    for r in cuerpo["reglas"]:
        lineas.append(f"{r['regla']:<{ancho}}  {r['descripcion']}")
        lineas.append(f"{'':<{ancho}}  -> {r['tratamiento']}")
    lineas += ["", "conteos:", paneles.tabla_texto(["tabla", "registros"], [[k, miles(v)] for k, v in cuerpo["conteos"].items()], "lr")]
    terminal("08b_terminal_calidad", 8, "Respuesta de GET /api/v1/etl/quality (reglas de calidad y conteos)",
             [("GET http://localhost:8010/api/v1/etl/quality   (Authorization: Bearer <token del login>)", "\n".join(lineas), "HTTP> ")],
             {"http": estado, "reglas": {r["regla"]: r["registros_afectados"] for r in cuerpo["reglas"]},
              "conteos": cuerpo["conteos"]}, "Respuesta real del servidor en el puerto 8010 sobre la BD cargada.",
             ubicacion="API FastAPI · puerto 8010")


def paso9(datos):
    ruta = BACKEND / "app" / "etl" / "red_rooster.py"
    f_desde, f_hasta = rango_funcion(ruta, "importar")
    bucle = next(n for n in _nodos(ruta, ast.For) if f_desde <= n.lineno <= f_hasta and getattr(n.iter, "id", "") == "pedidos")
    codigo("09a_codigo_upsert", 9, ruta, [(bucle.lineno, bucle.end_lineno)],
           "Carga: bucle de upsert de pedidos dentro de importar()", destacar=("session.get(m.SaleModel, sid)", "actual == objetivo"))
    registrar("09b_app_antes", 9, "app", "Pantalla «Datos reales · Red Rooster» antes de sincronizar (base vacía)",
              archivo_codigo="frontend/src/ui/CargaFuenteReal.tsx", cifras={"tarjeta_antes": datos["antes"], "ruta_configurada": datos["ruta_configurada"]},
              nota="Captura de la aplicación real (Vite 5180 + FastAPI 8010) con SQLite temporal vacía.")
    registrar("09c_app_despues", 9, "app", "Pantalla «Datos reales · Red Rooster» después de pulsar «Sincronizar pedidos»",
              archivo_codigo="frontend/src/ui/CargaFuenteReal.tsx",
              cifras={"tarjeta_despues": datos["despues"], "mensaje": datos["mensaje"], "resultado": datos["resultado"],
                      "alertas": datos["alertas"]},
              nota="Captura de la aplicación real tras la sincronización inicial.")


def paso10():
    ruta = BACKEND / "app" / "etl" / "red_rooster_analitica.py"
    codigo("10a_codigo_modelo_analitico", 10, ruta, [(rango_funcion(ruta, "_dim_fecha")[0], rango_funcion(ruta, "_ventas_diarias")[1])],
           "Modelo analítico: dim_fecha y ventas_diarias (variables rezagadas sin fuga)",
           destacar=("# shift(1) antes", 'df["media_movil_7"]'))
    codigo("10b_codigo_reconstruir", 10, ruta, [rango_funcion(ruta, "reconstruir")],
           "reconstruir(): reemplaza las tres tablas analíticas dentro de la transacción")
    q1, q2 = "PRAGMA table_info(dim_fecha);", "PRAGMA table_info(ventas_diarias);"
    q3 = ("SELECT COUNT(*) AS filas, MIN(fecha) AS desde, MAX(fecha) AS hasta, "
          "CAST(julianday(MAX(fecha)) - julianday(MIN(fecha)) AS INTEGER) + 1 AS dias_calendario FROM dim_fecha;")
    q4 = "SELECT COUNT(*) AS filas, MIN(fecha) AS desde, MAX(fecha) AS hasta FROM ventas_diarias;"
    partes = [salida_sql(DB_CARGA, q) for q in (q1, q2, q3, q4)]
    terminal("10c_terminal_esquema", 10, "Esquema y tamaño de dim_fecha y ventas_diarias",
             [(q, p[0], "sqlite> ") for q, p in zip((q1, q2, q3, q4), partes)],
             {"columnas_dim_fecha": [r[1] for r in partes[0][2]], "columnas_ventas_diarias": [r[1] for r in partes[1][2]],
              "filas_dim_fecha": partes[2][2][0][0], "desde": partes[2][2][0][1], "hasta": partes[2][2][0][2],
              "dias_calendario": partes[2][2][0][3], "filas_ventas_diarias": partes[3][2][0][0]},
             ubicacion="SQLite temporal (carga.db)")
    medio = datetime.fromisoformat(partes[2][2][0][1]) + (datetime.fromisoformat(partes[2][2][0][2]) - datetime.fromisoformat(partes[2][2][0][1])) / 2
    lunes = medio + timedelta(days=(7 - medio.weekday()) % 7)
    d0, d1 = lunes.date().isoformat(), (lunes + timedelta(days=7)).date().isoformat()
    q5 = f"SELECT * FROM ventas_diarias WHERE fecha BETWEEN '{d0}' AND '{d1}' ORDER BY fecha;"
    q6 = (f"SELECT fecha, nombre_dia_semana, es_festivo, es_quincena, es_descanso FROM dim_fecha "
          f"WHERE fecha BETWEEN '{d0}' AND '{d1}' ORDER BY fecha;")
    t5, _, f5 = salida_sql(DB_CARGA, q5)
    t6, _, f6 = salida_sql(DB_CARGA, q6)
    previos = [r[0] for r in sql(DB_CARGA, f"SELECT pedidos_pagados FROM ventas_diarias WHERE fecha >= date('{d0}', '-7 day') "
                                           f"AND fecha < '{d0}' ORDER BY fecha")[1]]
    guardado, calculado = f5[0][6], sum(previos) / len(previos)
    verifica = (f"Verificación independiente de media_movil_7 en {d0}: promedio de los {len(previos)} días previos = "
                f"{calculado:.4f}; guardado = {guardado:.4f}; coincide = {abs(guardado - calculado) < 1e-6}\n"
                f"lag_7 de {d1} = pedidos_pagados de {d0}: {f5[-1][5] == f5[0][1]}")
    terminal("10d_terminal_semana", 10, f"Ocho días reales de ventas_diarias ({d0} a {d1}) y su calendario",
             [(q5, t5, "sqlite> "), (q6, t6, "sqlite> "), ("python generar_evidencias.py   # paso 10: verificación independiente", verifica, "$ ")],
             {"desde": d0, "hasta": d1, "ventas_diarias": [dict(zip(["fecha", "pedidos_pagados", "ingresos", "ticket_promedio", "lag_1", "lag_7", "media_movil_7"], f)) for f in f5],
              "media_movil_7_recalculada": round(calculado, 4), "media_movil_7_guardada": guardado,
              "coincide": abs(guardado - calculado) < 1e-6},
             f"Semana elegida por regla: primer lunes después del punto medio del rango ({d0}), más 7 días para que lag_7 y la media móvil tengan valor.",
             ubicacion="SQLite temporal (carga.db)")
    tablas = [r[0] for r in sql(DB_CARGA, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")[1]]
    conteos = [[t, miles(escalar(DB_CARGA, f'SELECT COUNT(*) FROM "{t}"'))] for t in tablas]
    terminal("10e_terminal_conteos", 10, "Registros por tabla después de la carga inicial",
             [("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;  -- y SELECT COUNT(*) FROM <tabla> por cada una",
               paneles.tabla_texto(["tabla", "registros"], conteos, "lr"), "sqlite> ")],
             {"conteos": {t: escalar(DB_CARGA, f'SELECT COUNT(*) FROM "{t}"') for t in tablas}},
             "Las tablas analytics_* y users pertenecen a la aplicación; no las llena el ETL de Red Rooster.", ubicacion="SQLite temporal (carga.db)")


GRUPOS_BD = {
    "a": {"etiqueta": "Transaccionales (carga del ETL)", "color": "#2f6fb5", "fondo": "#eef4fb"},
    "b": {"etiqueta": "Analíticas del ETL", "color": "#2e7d4f", "fondo": "#edf7f0"},
    "c": {"etiqueta": "Control de cargas", "color": "#a8650c", "fondo": "#fbf3e6"},
    "d": {"etiqueta": "Resultados de modelos (objetivo 2)", "color": "#7a4fb0", "fondo": "#f4eefa"},
    "e": {"etiqueta": "Operación de la plataforma", "color": "#566273", "fondo": "#f0f2f5"},
}
# Agrupación y disposición del diagrama (decisión de diseño); el resto sale del esquema real.
TABLAS_BD = {"customers": ("a", 0, 0), "sales": ("a", 1, 0), "sale_items": ("a", 2, 0), "products": ("a", 3, 0),
             "inventory_movements": ("e", 4, 0),
             "analytics_customer_segments": ("d", 0, 1), "dim_fecha": ("b", 1, 1), "ventas_diarias": ("b", 2, 1),
             "analytics_demand_forecast": ("d", 3, 1), "users": ("e", 4, 1),
             "analytics_market_basket_rules": ("d", 0, 2), "calidad_datos": ("b", 1, 2),
             "source_import_runs": ("c", 2, 2), "etl_runs": ("c", 3, 2)}
RELACIONES_LOGICAS_BD = [("sales", "created_at", "dim_fecha", "fecha", "relación lógica por fecha (sin FK)")]


def esquema_bd(db: Path):
    """Tablas, columnas, PK, FK y conteos leídos por introspección (PRAGMA) de una SQLite en solo lectura."""
    tablas, fks = [], []
    for (nombre,) in sql(db, "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")[1]:
        claves = sql(db, f'PRAGMA foreign_key_list("{nombre}")')[1]
        fks += [(nombre, f[3], f[2], f[4]) for f in claves]
        columnas = [(c[1], c[2], c[5] > 0, c[1] in {f[3] for f in claves}) for c in sql(db, f'PRAGMA table_info("{nombre}")')[1]]
        tablas.append({"nombre": nombre, "grupo": TABLAS_BD[nombre][0], "columnas": columnas,
                       "filas_n": escalar(db, f'SELECT COUNT(*) FROM "{nombre}"')})
    for t in tablas:
        t["filas"] = f"{miles(t['filas_n'])} fila" + ("" if t["filas_n"] == 1 else "s")
    return tablas, fks


def paso10f(db: Path):
    tablas, fks = esquema_bd(db)
    assert {t["nombre"] for t in tablas} == set(TABLAS_BD), "El esquema cambió: actualice TABLAS_BD"
    for o, co, d, cd, _ in RELACIONES_LOGICAS_BD:
        assert co in [c[0] for t in tablas if t["nombre"] == o for c in t["columnas"]]
        assert cd in [c[0] for t in tablas if t["nombre"] == d for c in t["columnas"]]
    columnas = sum(len(t["columnas"]) for t in tablas)
    html = paneles.panel_er(
        "Modelo de datos de red_rooster.db",
        f"{len(tablas)} tablas · {columnas} columnas · {len(fks)} claves foráneas · filas contadas en la base cargada por el ETL "
        f"(esquema leído con PRAGMA)", tablas, fks, RELACIONES_LOGICAS_BD, GRUPOS_BD,
        {n: (c, f) for n, (_, c, f) in TABLAS_BD.items()})
    registrar("10f_diagrama_bd", 10, "diagrama", "Modelo de datos de red_rooster.db (diagrama entidad-relación)", html,
              archivo_codigo="backend/app/adapters/outbound/persistence/models.py",
              cifras={"tablas": len(tablas), "columnas": columnas, "claves_foraneas": len(fks),
                      "fks": [f"{o}.{co} -> {d}.{cd}" for o, co, d, cd in fks],
                      "relaciones_logicas": [f"{o}.{co} -> {d}.{cd}" for o, co, d, cd, _ in RELACIONES_LOGICAS_BD],
                      "filas_por_tabla": {t["nombre"]: t["filas_n"] for t in tablas},
                      "columnas_por_tabla": {t["nombre"]: len(t["columnas"]) for t in tablas}},
              nota=f"Tablas, columnas, tipos, PK, FK y conteos se leen por PRAGMA table_info/foreign_key_list y COUNT(*) sobre "
                   f"{db.name} abierta en solo lectura (base cargada en esta corrida; la red_rooster.db de backend/data puede "
                   f"tener otro contenido). Solo la agrupación por colores, la disposición y la relación lógica sales.created_at "
                   f"-> dim_fecha.fecha son decisiones de diseño. Lienzo 1800x1200 px, PNG a escala 2.")


def paso11(token, datos):
    ruta = BACKEND / "app" / "etl" / "red_rooster.py"
    codigo("11a_codigo_sin_cambios", 11, ruta,
           [rango_texto(ruta, "importar", "firma = _fingerprint", "no han cambiado")],
           "Idempotencia: la huella igual a la última carga devuelve SIN_CAMBIOS", destacar=('== firma and not force', '"SIN_CAMBIOS"'))
    cuerpo = json.loads(datos["swagger"]["cuerpo"])
    registrar("11b_swagger_import", 11, "app", "Swagger (/docs): POST /api/v1/etl/import con Authorize devuelve SIN_CAMBIOS",
              archivo_codigo="backend/app/adapters/inbound/api/v1/etl.py",
              cifras={"codigo_http": datos["swagger"]["codigo"], "respuesta": cuerpo},
              nota="Se oculta en la captura el bloque «curl» de Swagger porque incluía el token JWT completo.")
    conteos = ("SELECT (SELECT COUNT(*) FROM sales) AS sales, (SELECT COUNT(DISTINCT id) FROM sales) AS sales_id_distintos, "
               "(SELECT COUNT(*) FROM sale_items) AS sale_items, (SELECT COUNT(*) FROM customers) AS customers;")
    antes, _, fa = salida_sql(DB_CARGA, conteos)
    estado, r = http("POST", "/api/v1/etl/import?force=true", token)
    resp = "\n".join(f"{k:<10} {r[k]}" for k in ("status", "inserted", "updated", "unchanged", "skipped", "lines", "products", "message"))
    despues, _, fd = salida_sql(DB_CARGA, conteos)
    corridas, _, fr = salida_sql(DB_CARGA, "SELECT id, status, json_extract(report, '$.inserted') AS inserted, "
                                           "json_extract(report, '$.updated') AS updated, json_extract(report, '$.unchanged') AS unchanged "
                                           "FROM source_import_runs ORDER BY id;")
    terminal("11c_terminal_force", 11, "Reimportación forzada: sin duplicados",
             [(conteos, antes, "sqlite> "), ("POST http://localhost:8010/api/v1/etl/import?force=true   (Authorization: Bearer <token>)",
                                             f"HTTP {estado}\n{resp}", "HTTP> "),
              (conteos, despues, "sqlite> "),
              ("SELECT id, status, json_extract(report,'$.inserted') ... FROM source_import_runs ORDER BY id;", corridas, "sqlite> ")],
             {"http": estado, "respuesta_force": {k: r[k] for k in ("status", "inserted", "updated", "unchanged", "skipped", "lines", "products")},
              "antes": dict(zip(["sales", "sales_id_distintos", "sale_items", "customers"], fa[0])),
              "despues": dict(zip(["sales", "sales_id_distintos", "sale_items", "customers"], fd[0])),
              "corridas": [list(f) for f in fr]},
             "force=true vuelve a comparar los 3.042 pedidos uno a uno: ninguno cambió, por eso no inserta ni actualiza.",
             ubicacion="API FastAPI + SQLite temporal")


# ------------------------------------------------------------------ pasos 12 y 13 (copias del origen)

def modificar_origen(ruta: Path, agregar: bool, cancelar: bool) -> dict:
    """Modifica solo la COPIA del JSON: agrega un pedido derivado y/o cancela uno pagado."""
    pedidos = rr._leer_json(ruta)
    cambios = {}
    if cancelar:
        objetivo = next(p for p in pedidos[len(pedidos) // 2:] if p["estado"] == "pagado")
        cambios["cancelado"] = {"id": objetivo["id"], "fecha": objetivo["fecha"], "total": objetivo["total"],
                                "estado_antes": objetivo["estado"], "estado_despues": "cancelado"}
        objetivo["estado"] = "cancelado"
    if agregar:
        base = next(p for p in pedidos if p.get("tipo") == "mesa" and not p.get("telefono") and not p.get("direccion")
                    and not p.get("nota") and re.fullmatch(r"Mesa \d", str(p.get("cliente"))))
        ultima = max(rr._fecha(p["fecha"]) for p in pedidos).replace(tzinfo=rr.BOGOTA) + timedelta(hours=1)
        nuevo = copy.deepcopy(base)
        nuevo.update(id=max(p["id"] for p in pedidos) + 1, fecha=ultima.isoformat(timespec="seconds"), ip="")
        nuevo["pagado_en"] = nuevo["fecha"]
        pedidos.append(nuevo)
        cambios["nuevo"] = {"id": nuevo["id"], "copia_de": base["id"], "fecha": nuevo["fecha"], "tipo": nuevo["tipo"],
                            "total": nuevo["total"], "lineas": len(nuevo["productos"])}
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(pedidos, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporal, ruta)
    return cambios


def paso12():
    shutil.copy2(DB_CARGA, DB_INC)
    ruta = BACKEND / "app" / "etl" / "red_rooster.py"
    codigo("12a_codigo_incremental", 12, ruta,
           [rango_texto(ruta, "importar", "venta = session.get(m.SaleModel, sid)", "actual = None"),
            rango_texto(ruta, "importar", "objetivo = (fecha", "nuevos += 1")],
           "Incremental: comparación del pedido existente con el objetivo y conteo de insertados/actualizados",
           destacar=("actual == objetivo", "actualizados += 1", "nuevos += 1"))
    pedido_json = ORIGEN_INC / "pedidos.json"
    estados_sql = "SELECT status, COUNT(*) AS pedidos FROM sales GROUP BY status ORDER BY status;"

    def incremental():
        motor = crear_motor(f"sqlite:///{DB_INC.as_posix()}")
        cambios = modificar_origen(pedido_json, agregar=True, cancelar=True)
        c, n = cambios["cancelado"], cambios["nuevo"]
        print(f"Modificación 1 (inserción): pedido nuevo id={n['id']}, copia del id={n['copia_de']} sin datos personales, "
              f"fecha {n['fecha']}, tipo {n['tipo']}, total {miles(n['total'])}, {n['lineas']} líneas")
        print(f"Modificación 2 (actualización): pedido id={c['id']} ({c['fecha']}, total {miles(c['total'])}) "
              f"estado '{c['estado_antes']}' -> '{c['estado_despues']}'")
        with Session(motor, expire_on_commit=False) as s:
            r1 = rr.importar(s, pedido_json, obtener_clave_privacidad())
        print("\nimportar(...) sobre la copia modificada:")
        print("  " + " · ".join(f"{k}={r1[k]}" for k in ("status", "inserted", "updated", "unchanged", "skipped", "lines")))
        with Session(motor, expire_on_commit=False) as s:
            r2 = rr.importar(s, pedido_json, obtener_clave_privacidad())
        print(f"Segunda ejecución sin tocar el archivo: status={r2['status']}")
        motor.dispose()
        return {"modificaciones": cambios, "primera": {k: r1[k] for k in ("status", "inserted", "updated", "unchanged", "skipped", "lines")},
                "segunda": r2["status"]}

    antes, _, fa = salida_sql(DB_INC, estados_sql, "lr")
    c_antes = escalar(DB_INC, "SELECT COUNT(*) FROM sales")
    (texto, cifras), cmd = ejecutar_script("python generar_evidencias.py   # paso 12: modificar la COPIA del JSON y llamar a rr.importar() sobre una copia de la BD cargada",
                                           incremental)
    n_id, c_id = cifras["modificaciones"]["nuevo"]["id"], cifras["modificaciones"]["cancelado"]["id"]
    dia_c = cifras["modificaciones"]["cancelado"]["fecha"]
    fila_sql = f"SELECT id, created_at, status, total_amount, canal FROM sales WHERE id IN ({c_id}, {n_id}) ORDER BY id;"
    despues, _, fd = salida_sql(DB_INC, estados_sql, "lr")
    filas, _, ffilas = salida_sql(DB_INC, fila_sql)
    cifras.update({"sales_antes": c_antes, "sales_despues": escalar(DB_INC, "SELECT COUNT(*) FROM sales"),
                   "estados_antes": dict(fa), "estados_despues": dict(fd),
                   "pedidos_afectados": [list(map(str, f)) for f in ffilas]})
    terminal("12b_terminal_incremental", 12, "Importación incremental: un pedido nuevo y un pedido cancelado",
             [(estados_sql + "   -- antes", antes, "sqlite> "), (cmd, texto, "$ "), (estados_sql + "   -- después", despues, "sqlite> "),
              (fila_sql, filas, "sqlite> ")], cifras,
             "Trabajo sobre copias: C:\\rr_evid\\incremental\\pedidos.json (copia de BD/pedidos.json) y una copia de la BD cargada. "
             "Se agregó el pedido id=max+1 (copia de una venta de mesa sin datos personales, ip vacía, una hora después de la última) "
             "y el pedido indicado pasó de 'pagado' a 'cancelado'.",
             resaltar=("inserted=", "status='"), ubicacion="copias temporales del JSON y de SQLite")


def paso13():
    shutil.copy2(DB_CARGA, DB_VIG)
    ruta = BACKEND / "app" / "etl" / "watch_red_rooster.py"
    codigo("13a_codigo_vigilante", 13, ruta, [(1, len(_fuente(ruta)))], "Vigilante: carga periódica del JSON (watch_red_rooster.py)",
           destacar=("time.sleep(intervalo)", "importar(session"), maximo=60)
    pedido_json = ORIGEN_VIG / "pedidos.json"
    registro = TRABAJO / "vigilante.log"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{DB_VIG.as_posix()}", "RED_ROOSTER_JSON": str(pedido_json),
           "RED_ROOSTER_POLL_SECONDS": "5", "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "DATA_SOURCE_MODE": "synthetic"}
    proceso = subprocess.Popen([str(PY), "-m", "app.etl.watch_red_rooster"], cwd=BACKEND, env=env,
                               stdout=registro.open("w", encoding="utf-8"), stderr=subprocess.STDOUT)
    eventos = []

    def cargas() -> int:
        return registro.read_text(encoding="utf-8").count("Carga:")

    def esperar_cargas(n: int):
        limite = time.time() + 40
        while cargas() < n and time.time() < limite:
            time.sleep(0.3)

    try:
        esperar_cargas(1)
        time.sleep(2)
        os.utime(pedido_json, None)
        eventos.append("touch (cambia la fecha de modificación, no el contenido)")
        esperar_cargas(2)
        time.sleep(2)
        cambios = modificar_origen(pedido_json, agregar=True, cancelar=False)
        eventos.append(f"se agrega el pedido id={cambios['nuevo']['id']} a la copia")
        esperar_cargas(3)
        time.sleep(1)
    finally:
        detener(proceso)
        proceso.wait(timeout=15)
    log = registro.read_text(encoding="utf-8").strip()
    lineas_carga = [l for l in log.splitlines() if "Carga:" in l]
    estados = [re.search(r"'status': '(\w+)'", l).group(1) for l in lineas_carga]
    terminal("13b_terminal_vigilante", 13, "Vigilante en ejecución sobre la copia: SIN_CAMBIOS y luego SUCCESS",
             [("$env:RED_ROOSTER_POLL_SECONDS=5; venv\\Scripts\\python -m app.etl.watch_red_rooster   "
               "# RED_ROOSTER_JSON y DATABASE_URL apuntan a las copias de trabajo; se detiene a los ~15 s", log, "PS backend> ")],
             {"cargas_en_el_log": len(lineas_carga), "estados_en_orden": estados, "eventos_durante_la_ejecucion": eventos,
              "pedido_agregado": cambios["nuevo"]["id"]},
             "Mientras corría se hizo (1) touch del archivo y (2) se agregó un pedido a la copia. El proceso se detuvo al terminar.",
             ubicacion="copias temporales del JSON y de SQLite")


def paso14():
    comando = ("venv\\Scripts\\python -m pytest tests/unit/test_red_rooster.py tests/unit/test_red_rooster_analitica.py "
               "tests/unit/test_red_rooster_migracion.py tests/api/test_red_rooster_api.py -v")
    r = subprocess.run([str(PY), "-m", "pytest", "tests/unit/test_red_rooster.py", "tests/unit/test_red_rooster_analitica.py",
                        "tests/unit/test_red_rooster_migracion.py", "tests/api/test_red_rooster_api.py", "-v"],
                       cwd=BACKEND, capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    salida = (r.stdout + r.stderr).strip()
    resumen = salida.splitlines()[-1]
    m = {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|error|errors|skipped|warnings?)", resumen)}
    cifras = {"resumen": resumen.strip("= "), "codigo_salida": r.returncode, **m}
    lineas = salida.splitlines()
    guardar_texto("14_pruebas_completa", salida)
    maximo = 46
    trozos = [lineas] if len(lineas) <= maximo else [lineas[:len(lineas) // 2], lineas[len(lineas) // 2:]]
    for k, trozo in enumerate(trozos, 1):
        etiqueta = f" (parte {k} de {len(trozos)})" if len(trozos) > 1 else ""
        terminal(f"14a_terminal_pruebas{'_p' + str(k) if len(trozos) > 1 else ''}", 14, "Pruebas automáticas del ETL (pytest -v)" + etiqueta,
                 [(comando if k == 1 else comando + "   # continuación", "\n".join(trozo), "PS backend> ")],
                 cifras, "Salida real de pytest; si hay dos imágenes, la segunda continúa la lista y trae el resumen final.",
                 resaltar=("FAILED", "ERROR", " passed", " failed"))


# ------------------------------------------------------------------ orquestación

def escribir_manifiesto(extra: dict) -> None:
    figuras = sorted(FIGURAS, key=lambda f: (f["paso"], f["id"]))
    for orden, f in enumerate(figuras, 1):
        f["orden"] = orden
    manifiesto = {"generado": datetime.now().isoformat(timespec="seconds"), "carpeta_png": ruta_rel(AQUI),
                  "reproducir": "backend\\venv\\Scripts\\python documentos\\evidencias_objetivo_1\\generar_evidencias.py",
                  **extra, "figuras": figuras}
    paneles.guardar(AQUI / "manifiesto.json", json.dumps(manifiesto, ensure_ascii=False, indent=2))
    paneles.guardar(SALIDAS / "registro.json", json.dumps(figuras, ensure_ascii=False, indent=2))


def capturar_html(prefijo: str = "") -> None:
    subprocess.run(["node", str(AQUI / "capturar.mjs"), "html", str(HTML), str(AQUI), prefijo], check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo-pruebas", action="store_true", help="regenera solo el paso 14 y el manifiesto")
    ap.add_argument("--solo-diagrama", action="store_true", help="regenera solo el diagrama de la BD (10f) y el manifiesto")
    args = ap.parse_args()
    if args.solo_diagrama:
        previas = json.loads((SALIDAS / "registro.json").read_text(encoding="utf-8"))
        FIGURAS.extend(f for f in previas if f["id"] != "10f_diagrama_bd")
        manifiesto_previo = json.loads((AQUI / "manifiesto.json").read_text(encoding="utf-8"))
        paso10f(DB_CARGA)
        escribir_manifiesto({k: manifiesto_previo[k] for k in ("notas_generales",) if k in manifiesto_previo})
        capturar_html("10f")
        return
    if args.solo_pruebas:
        previas = json.loads((SALIDAS / "registro.json").read_text(encoding="utf-8"))
        FIGURAS.extend(f for f in previas if f["paso"] != 14)
        manifiesto_previo = json.loads((AQUI / "manifiesto.json").read_text(encoding="utf-8"))
        paso14()
        escribir_manifiesto({k: manifiesto_previo[k] for k in ("notas_generales",) if k in manifiesto_previo})
        capturar_html("14")
        return

    pedidos, productos = rr._leer_json(BD_ORIGEN / "pedidos.json"), rr._leer_json(BD_ORIGEN / "productos.json")
    preparar_trabajo()
    paso1_arquitectura(pedidos, productos)
    paso2()
    paso3()
    paso4()
    paso5(pedidos)
    cfg = get_settings()
    with servidores():
        entorno = {**os.environ, "RR_USER": cfg.admin_user, "RR_PASS": cfg.admin_password}
        datos_app = SALIDAS / "app_datos.json"
        subprocess.run(["node", str(AQUI / "capturar.mjs"), "app", str(AQUI), str(datos_app), "09b_app_antes.png",
                        "09c_app_despues.png", "11b_swagger_import.png"], check=True, env=entorno)
        datos = json.loads(datos_app.read_text(encoding="utf-8"))
        token = http("POST", "/api/v1/auth/login", cuerpo={"username": cfg.admin_user, "password": cfg.admin_password})[1]["access_token"]
        paso6(pedidos)
        paso7(pedidos)
        paso8(token)
        paso9(datos)
        paso10()
        paso11(token, datos)
        paso10f(DB_CARGA)
    paso12()
    paso13()
    paso14()
    escribir_manifiesto({"notas_generales": [
        "Todas las cifras salen de la ejecución real de este script sobre BD/pedidos.json (3.042 pedidos) y BD/productos.json (44).",
        "Las modificaciones de los pasos 12 y 13 se hacen solo en copias del JSON; backend/data/*.db y BD/*.json no se tocan.",
        "El servidor de captura usa SQLite temporal vacía (DATABASE_URL) y DATA_SOURCE_MODE=synthetic sin semilla para que "
        "no cargue solo al arrancar; así el paso 9 muestra la carga inicial desde cero.",
        "Salida de cada terminal en salidas/<id>.txt; HTML en salidas/html/."]})
    capturar_html()


if __name__ == "__main__":
    main()
