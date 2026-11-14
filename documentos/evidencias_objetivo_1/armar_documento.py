"""Arma el Word del Objetivo 1 a partir del documento limpio _V1.docx y las evidencias de esta carpeta.

Uso (desde la raíz del proyecto):  python documentos\\evidencias_objetivo_1\\armar_documento.py
Genera documentos\\Proyecto integrador Red Rooster (en plantilla)_Objetivo_1_v2.docx (no sobrescribe otros archivos).
Después se abre en Word por COM para actualizar la tabla de contenido y exportar un PDF de revisión.
"""
from __future__ import annotations

import json
import re
import shutil
import struct
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

AQUI = Path(__file__).resolve().parent
DOCS = AQUI.parent
ORIGEN = DOCS / "Proyecto integrador Red Rooster (en plantilla)_V1.docx"
DESTINO = DOCS / "Proyecto integrador Red Rooster (en plantilla)_Objetivo_1_v2.docx"
ANCHO_EMU = 5486400  # 6 pulgadas, igual que las figuras existentes

MANIFIESTO = {f["id"]: f for f in json.loads((AQUI / "manifiesto.json").read_text(encoding="utf-8"))["figuras"]}


def lineas(fid: str) -> str:
    return MANIFIESTO[fid]["lineas_texto"].replace("-", "–")


# ---------------------------------------------------------------- contenido
# Cada elemento: ("h", titulo) | ("p", texto) | ("fig", [ids_png], titulo, nota)
def codigo(fid: str, archivo: str) -> str:
    return f"Fragmento de {archivo}, líneas {lineas(fid)}. Elaboración propia."


RR = "backend/app/etl/red_rooster.py"
RA = "backend/app/etl/red_rooster_analitica.py"
EJEC = "Captura de la ejecución real del pipeline. Elaboración propia con datos del sistema de pedidos de Red Rooster."

CONTENIDO = [
    ("p", "En este objetivo construimos el pipeline ETL que lleva los registros del sistema de pedidos de Red Rooster a una "
          "base de datos relacional analítica en SQLite. Lo implementamos dentro del backend de la plataforma Micronegocio "
          "(FastAPI y SQLAlchemy), principalmente en los módulos backend/app/etl/red_rooster.py y "
          "backend/app/etl/red_rooster_analitica.py. A continuación documentamos el proceso paso a paso: en cada paso "
          "explicamos qué hicimos y por qué, mostramos el fragmento de código con sus números de línea reales y agregamos "
          "la evidencia de su ejecución."),
    ("p", "Todas las capturas se tomaron con Playwright a partir de una ejecución real del pipeline sobre una copia de los "
          "archivos de origen (BD/pedidos.json, con 3.042 pedidos, y BD/productos.json, con 44 productos), con corte al "
          "13 de noviembre de 2026. El script que las regenera, documentos/evidencias_objetivo_1/generar_evidencias.py, "
          "queda en el proyecto para que cualquier persona pueda reproducirlas."),

    ("h", "Paso 1. Diseñamos la arquitectura del pipeline"),
    ("p", "Antes de programar definimos el flujo completo (Figura {f}). El pipeline tiene tres etapas. En la extracción "
          "leemos los dos archivos JSON y calculamos una huella de su contenido para saber si cambiaron. En la "
          "transformación convertimos las fechas, estandarizamos los estados, los métodos de pago y el canal, reemplazamos "
          "los datos personales por un código anónimo y medimos la calidad de los datos. En la carga guardamos todo en "
          "SQLite dentro de una sola transacción y reconstruimos las tablas analíticas. La misma función importar() se "
          "invoca desde tres lugares: el endpoint POST /api/v1/etl/import, la carga automática al iniciar el backend y un "
          "proceso vigilante que revisa los archivos de forma periódica."),
    ("fig", ["01a_arquitectura"], "Arquitectura del pipeline ETL de Red Rooster",
     "Los nombres de las funciones y de las tablas se tomaron directamente del código fuente. Elaboración propia."),

    ("h", "Paso 2. Perfilamos los archivos de origen"),
    ("p", "El primer paso fue conocer los datos tal como los entrega el sistema del restaurante. Escribimos un perfil que "
          "recorre los archivos y cuenta registros, campos y valores sin imprimir ningún dato personal (Figura {f}). El "
          "archivo de pedidos tiene 3.042 pedidos con identificador único, entre el 23 de marzo y el 13 de noviembre de "
          "2026, y 5.022 líneas de producto. Cada pedido trae 17 campos, y cinco de ellos contienen datos personales: "
          "cliente (en 3.042 pedidos), ip (3.042), nota (280), teléfono (236) y dirección (235)."),
    ("p", "Los estados son pagado (3.016), cancelado (25) y entregado (1). Los canales son para llevar (1.528), mesa "
          "(1.278) y domicilio (231), con 5 pedidos sin canal. Los métodos de pago son Bre-B (1.695), efectivo (1.153), "
          "tarjeta (110) y Nequi (59), con 25 pedidos sin método. El catálogo tiene 44 productos, 8 de ellos con costo en "
          "cero. Este perfil nos indicó qué había que limpiar y qué había que proteger."),
    ("fig", ["02a_perfil_fuente"], "Perfil de los archivos de origen",
     "Solo se muestran conteos; ningún valor personal aparece en la salida. Elaboración propia con datos del sistema de "
     "pedidos de Red Rooster."),

    ("h", "Paso 3. Configuramos el origen y protegimos las claves"),
    ("p", "Configuramos la ruta del origen y la clave de privacidad en backend/app/core/config.py (Figura {f}). La ruta por "
          "defecto apunta a BD/pedidos.json y se puede cambiar con una variable de entorno sin tocar el código. La clave "
          "con la que se seudonimizan los clientes se lee de la variable DATA_PRIVACY_KEY o, si no existe, de un archivo "
          "local data/.privacy_key que se genera una sola vez con un generador aleatorio criptográfico."),
    ("fig", ["03a_codigo_config"], "Configuración de la ruta del origen y de la clave de privacidad",
     codigo("03a_codigo_config", "backend/app/core/config.py")),
    ("p", "Para que ni los datos de origen ni las claves terminen en el control de versiones, excluimos en los archivos "
          ".gitignore la carpeta BD/, las bases de datos y los archivos de clave (Figura {f}). En la evidencia solo "
          "mostramos la longitud de la clave (64 caracteres), nunca su valor."),
    ("fig", ["03b_terminal_seguridad"], "Archivos excluidos del repositorio y existencia de la clave de privacidad",
     "El valor de la clave nunca se imprime. " + EJEC),

    ("h", "Paso 4. Extrajimos los datos y calculamos la huella del origen"),
    ("p", "La extracción está en las funciones _leer_json y _fingerprint (Figura {f}). Leemos los archivos con la "
          "codificación utf-8-sig, que tolera la marca BOM que a veces agregan los editores de Windows. Además, calculamos "
          "una huella SHA-256 sobre el nombre y el contenido de ambos archivos, leyéndolos por bloques para no cargarlos "
          "completos en memoria. Esa huella es la que después nos permite saber si el origen cambió desde la última carga."),
    ("fig", ["04a_codigo_extraccion"], "Lectura de los archivos JSON y cálculo de la huella SHA-256",
     codigo("04a_codigo_extraccion", RR)),
    ("p", "Para la copia usada en la evidencia, la huella empieza por cbf2b0fd8d03f9c5 y coincide con un cálculo "
          "independiente hecho sobre los mismos archivos (Figura {f})."),
    ("fig", ["04b_terminal_huella"], "Huella SHA-256 calculada sobre los archivos de origen", EJEC),

    ("h", "Paso 5. Unificamos las fechas en la hora de Colombia"),
    ("p", "Durante el perfil encontramos que las fechas vienen en dos zonas horarias: 91 pedidos en UTC (+00:00) y 2.951 en "
          "hora de Colombia (−05:00). Si se dejaran así, un pedido de las 8 p. m. registrado en UTC quedaría en el día "
          "siguiente. La función _fecha convierte todas las fechas a la zona America/Bogota y luego quita la zona, "
          "siguiendo la convención del sistema de guardar las fechas en hora local (Figura {f})."),
    ("fig", ["05a_codigo_fecha"], "Conversión de las fechas a hora local de Bogotá", codigo("05a_codigo_fecha", RR)),
    ("p", "La Figura {f} muestra tres casos reales. El pedido 101 pasa de las 18:49 en UTC a las 13:49 en hora local; el "
          "172, que ya venía en hora de Bogotá, no cambia; y el 110 pasa del 24 al 23 de marzo, un cambio de día que habría "
          "alterado las ventas diarias si no se hubiera corregido."),
    ("fig", ["05b_terminal_fechas"], "Fechas antes y después de la conversión", EJEC),

    ("h", "Paso 6. Estandarizamos estados, métodos de pago y canal"),
    ("p", "El sistema del restaurante usa sus propios valores para el estado, el método de pago y el canal. Los llevamos al "
          "vocabulario de la plataforma con dos diccionarios y una función (Figura {f}). ESTADOS_PAGADOS define que solo "
          "pagado y entregado cuentan como venta completada (COMPLETED) y que el resto queda como CANCELLED; PAGOS traduce "
          "breb a TRANSFERENCIA y conserva efectivo, tarjeta y Nequi; y canal_de normaliza el tipo de pedido y asigna "
          "sin_dato cuando falta."),
    ("fig", ["06a_codigo_estandarizacion"], "Reglas de estandarización de estados, métodos de pago y canal",
     codigo("06a_codigo_estandarizacion", RR)),
    ("p", "La Figura {f} muestra el mapeo con los conteos reales y confirma que coincide con lo guardado en la base: 3.017 "
          "pedidos completados y 25 cancelados; 1.695 pagos por transferencia; y 5 pedidos con canal sin_dato. Los 25 "
          "pedidos sin método de pago quedan como efectivo, que es el valor por defecto del sistema; 24 de ellos están "
          "cancelados, por lo que no afectan las ventas."),
    ("fig", ["06b_terminal_mapeo"], "Mapeo de los valores de origen a los de la plataforma, con conteos", EJEC),

    ("h", "Paso 7. Anonimizamos a los clientes"),
    ("p", "Para cumplir la Ley 1581 de 2012 (Congreso de la República de Colombia, 2012), ningún nombre, teléfono, "
          "dirección, nota ni IP llega a la base. En su lugar, la función _huella_cliente calcula un HMAC-SHA256 "
          "(Krawczyk et al., 1997) con la clave privada del paso 3 (Figura {f}). Usamos el teléfono reducido a solo "
          "dígitos y sin el indicativo 57, para que un mismo número escrito de dos formas dé el mismo cliente; si no hay "
          "teléfono y el pedido es a domicilio, usamos la dirección en minúsculas. Elegimos HMAC y no un hash simple porque, "
          "sin la clave, no se puede recuperar el teléfono probando números posibles."),
    ("p", "Después, la función _asignar_codigos le da a cada cliente un código legible C001, C002… por orden de primera "
          "compra. Un código ya asignado nunca cambia entre cargas, así que los análisis de recurrencia siguen siendo "
          "comparables en el tiempo."),
    ("fig", ["07a_codigo_anonimizacion"], "Seudonimización del cliente con HMAC y asignación del código anónimo",
     codigo("07a_codigo_anonimizacion", RR)),
    ("p", "El resultado son 126 clientes, del C001 al C126, cada uno con una huella distinta y sin correo ni teléfono "
          "guardados (Figura {f}). Para comprobarlo, buscamos en todas las tablas de la base los 464 nombres, 219 "
          "teléfonos, 134 direcciones y 664 IP del origen: no apareció ninguno."),
    ("fig", ["07b_terminal_clientes"], "Clientes anonimizados en SQLite y verificación de ausencia de datos personales",
     "Las consultas se ejecutaron sobre la base cargada por la aplicación. " + EJEC),

    ("h", "Paso 8. Medimos y registramos la calidad de los datos"),
    ("p", "En lugar de corregir los problemas en silencio, los medimos y los dejamos registrados en la tabla calidad_datos. "
          "La función _calidad aplica nueve reglas sobre el origen (Figura {f}), y el endpoint GET /api/v1/etl/quality las "
          "expone para consultarlas desde la plataforma."),
    ("fig", ["08a_codigo_calidad"], "Reglas de calidad aplicadas sobre los archivos de origen",
     codigo("08a_codigo_calidad", RA)),
    ("p", "La Figura {f} muestra la respuesta real del endpoint. Encontramos fechas en dos zonas horarias (91 en UTC y "
          "2.951 en hora de Bogotá), que resolvimos en el paso 5, y 5 pedidos sin canal, que quedaron como sin_dato. "
          "El campo mesero se usaba como texto libre, con 77 valores distintos (“cris”, “Cris”, "
          "“Mesa 1”…); lo descartamos porque no identifica al mesero de forma confiable. Además, hay "
          "8 productos con costo en cero, que registramos como costo faltante para no interpretar un margen falso de "
          "100 %, y 1 pedido cuyo total no coincide con la suma de sus productos, en el que conservamos el total de "
          "origen. Por último, contamos 25 pedidos cancelados y 25 sin método de pago, y ninguna línea quedó omitida."),
    ("fig", ["08b_terminal_calidad"], "Respuesta del endpoint de calidad de datos", EJEC),

    ("h", "Paso 9. Cargamos los pedidos en una sola transacción"),
    ("p", "La carga está en el bucle principal de importar() (Figura {f}). Para cada pedido buscamos si ya existe por su "
          "identificador de origen: si no existe, lo insertamos; si existe, comparamos su contenido (fecha, cliente, "
          "total, estado, método de pago, canal y productos) con lo que trae el archivo, y solo lo contamos como "
          "actualizado cuando algo cambió de verdad. Todo ocurre en una sola transacción, de modo que, si algo falla, "
          "no queda una carga a medias."),
    ("fig", ["09a_codigo_upsert_p1", "09a_codigo_upsert_p2"], "Bucle de inserción o actualización de pedidos",
     f"Fragmento de {RR}, líneas {lineas('09a_codigo_upsert_p1').split('–')[0]}–"
     f"{lineas('09a_codigo_upsert_p2').split('–')[1]}, mostrado en dos partes consecutivas. Elaboración propia."),
    ("p", "Antes de la primera carga, la página Datos de la plataforma mostraba 3.042 pedidos en el JSON y 0 en SQLite "
          "(Figura {f})."),
    ("fig", ["09b_app_antes"], "Página Datos de la plataforma antes de la carga inicial",
     "Captura de la aplicación real con una base de datos vacía. Elaboración propia."),
    ("p", "Al pulsar «Sincronizar pedidos», la importación terminó en 9,5 segundos con 3.042 pedidos nuevos y 5.022 "
          "líneas de producto procesadas (Figura {f})."),
    ("fig", ["09c_app_despues"], "Página Datos de la plataforma después de la carga inicial",
     "Captura de la aplicación real. Elaboración propia con datos del sistema de pedidos de Red Rooster."),

    ("h", "Paso 10. Construimos el modelo analítico"),
    ("p", "Para que la base sirva al análisis, además de las tablas transaccionales construimos dos tablas analíticas "
          "siguiendo el modelo dimensional (Kimball & Ross, 2013). La tabla dim_fecha es un calendario continuo con el día "
          "de la semana, los festivos de Colombia, las quincenas y el martes de descanso del restaurante. La tabla "
          "ventas_diarias tiene, para cada día, los pedidos pagados, los ingresos, el ticket promedio, los rezagos de 1 y "
          "7 días y la media móvil de 7 días (Figura {f})."),
    ("p", "Para evitar fuga de información, la media móvil se calcula aplicando shift(1) antes de rolling(7), es decir, "
          "solo con días anteriores; así, un modelo nunca ve el valor del mismo día que intenta predecir."),
    ("fig", ["10a_codigo_modelo_analitico"], "Construcción de las tablas dim_fecha y ventas_diarias",
     codigo("10a_codigo_modelo_analitico", RA)),
    ("p", "La función reconstruir() reemplaza las tres tablas analíticas en cada carga, dentro de la misma transacción "
          "que los pedidos, para que nunca queden desalineadas con ellos (Figura {f})."),
    ("fig", ["10b_codigo_reconstruir"], "Reconstrucción de las tablas analíticas dentro de la transacción",
     codigo("10b_codigo_reconstruir", RA)),
    ("p", "Ambas tablas quedaron con 236 filas, una por cada día entre el 23 de marzo y el 13 de noviembre de 2026 "
          "(Figura {f})."),
    ("fig", ["10c_terminal_esquema"], "Esquema y tamaño de las tablas dim_fecha y ventas_diarias", EJEC),
    ("p", "La Figura {f} muestra una semana real. El lunes 20 de julio aparece como festivo; el martes 21, como día de "
          "descanso con 0 pedidos; y la media móvil del 20 de julio (12,14) coincide con el promedio de los siete días "
          "anteriores calculado de forma independiente."),
    ("fig", ["10d_terminal_semana"], "Ocho días de la tabla ventas_diarias y su calendario", EJEC),
    ("p", "La Figura {f} resume los registros de cada tabla después de la carga inicial: 3.042 pedidos, 5.022 líneas, "
          "44 productos, 126 clientes, 236 días y 9 reglas de calidad. Las tablas de resultados de los modelos "
          "(analytics_*) siguen vacías porque se llenan en el objetivo 2."),
    ("fig", ["10e_terminal_conteos"], "Registros por tabla después de la carga inicial", EJEC),
    ("p", "Para cerrar este paso dibujamos el modelo de datos completo de la base (Figura {f}). El diagrama no se hizo "
          "a mano: lo generamos leyendo el esquema real de red_rooster.db, de modo que muestra las 14 tablas con todas "
          "sus columnas, las llaves foráneas que las relacionan y el número de registros de cada una. Agrupamos las "
          "tablas según su papel: las transaccionales que llena el ETL (products, customers, sales y sale_items), las "
          "analíticas que construye el ETL (dim_fecha, ventas_diarias y calidad_datos), las de control de cargas, las "
          "que guardarán los resultados de los modelos del objetivo 2 y las propias de la operación de la plataforma. "
          "La relación entre las ventas y el calendario es lógica, por la fecha del pedido, y no necesita llave foránea."),
    ("fig", ["10f_diagrama_bd"], "Modelo de datos completo de la base red_rooster.db",
     "Diagrama generado a partir del esquema real de la base (tablas, columnas, llaves y número de registros). "
     "Los registros se contaron en la base de la corrida de evidencias, que ya incluye la reimportación forzada del "
     "paso 11; por eso source_import_runs muestra 2 cargas. PK: llave primaria; FK: llave foránea; la línea punteada "
     "indica una relación lógica sin llave foránea. Elaboración propia.", "horizontal"),

    ("h", "Paso 11. Comprobamos que la carga sea repetible"),
    ("p", "Un ETL que se ejecuta muchas veces no debe duplicar ventas. Por eso, al comienzo de importar() comparamos la "
          "huella actual con la de la última carga exitosa: si son iguales y no se pide force, el proceso termina sin "
          "tocar la base y responde SIN_CAMBIOS (Figura {f})."),
    ("fig", ["11a_codigo_sin_cambios"], "Detección de un origen sin cambios", codigo("11a_codigo_sin_cambios", RR)),
    ("p", "Lo comprobamos desde la documentación interactiva de la API (Swagger): la segunda ejecución respondió "
          "SIN_CAMBIOS, con 0 pedidos insertados y 0 actualizados (Figura {f})."),
    ("fig", ["11b_swagger_import"], "Segunda ejecución de la importación desde Swagger",
     "Se ocultó el bloque «curl» de Swagger porque contenía el token de acceso. Captura de la aplicación real. "
     "Elaboración propia."),
    ("p", "Luego forzamos una reconciliación completa con force=true. El sistema volvió a comparar los 3.042 pedidos uno "
          "por uno, no encontró cambios, y la base siguió con 3.042 ventas, 3.042 identificadores distintos y 5.022 "
          "líneas (Figura {f})."),
    ("fig", ["11c_terminal_force"], "Reimportación forzada sin registros duplicados", EJEC),

    ("h", "Paso 12. Probamos la carga incremental"),
    ("p", "El sistema del restaurante sigue registrando pedidos, y un pedido puede cambiar de estado después de cargado. "
          "Para probar ese caso trabajamos sobre una copia del archivo: agregamos un pedido nuevo (identificador 3149) y "
          "cambiamos el pedido 1625 de pagado a cancelado. La comparación entre el pedido guardado y el del archivo "
          "(Figura {f}) es la que decide si cada pedido es nuevo, cambió o sigue igual."),
    ("fig", ["12a_codigo_incremental"], "Comparación del pedido guardado con el del archivo",
     codigo("12a_codigo_incremental", RR)),
    ("p", "El ETL detectó exactamente esos dos cambios: 1 pedido insertado, 1 actualizado y 3.041 sin cambios. Los "
          "cancelados pasaron de 25 a 26, y una nueva ejecución volvió a responder SIN_CAMBIOS (Figura {f})."),
    ("fig", ["12b_terminal_incremental"], "Importación incremental con un pedido nuevo y un pedido cancelado",
     "Las modificaciones se hicieron solo sobre una copia del archivo y de la base. " + EJEC),

    ("h", "Paso 13. Dejamos la carga en vigilancia continua"),
    ("p", "Para que la base se mantenga al día sin intervención, implementamos un vigilante que se ejecuta como un "
          "proceso independiente del servidor web y llama a importar() en cada intervalo: 60 segundos por defecto, "
          "configurable con la variable RED_ROOSTER_POLL_SECONDS. Si una carga falla, registra el error y lo intenta "
          "de nuevo en el siguiente ciclo (Figura {f})."),
    ("fig", ["13a_codigo_vigilante"], "Proceso vigilante de la fuente", codigo("13a_codigo_vigilante",
                                                                                "backend/app/etl/watch_red_rooster.py")),
    ("p", "Lo ejecutamos con un intervalo de 5 segundos sobre la copia de trabajo. La Figura {f} muestra el registro "
          "real. La primera revisión respondió SIN_CAMBIOS. Luego cambiamos solo la fecha de modificación del archivo "
          "y siguió en SIN_CAMBIOS, porque la huella depende del contenido y no de la fecha. Al agregar un pedido, la "
          "siguiente revisión lo cargó (SUCCESS, 1 insertado)."),
    ("fig", ["13b_terminal_vigilante"], "Registro del vigilante durante la prueba",
     "El vigilante trabajó sobre una copia del archivo y de la base. " + EJEC),

    ("h", "Paso 14. Automatizamos las pruebas del ETL"),
    ("p", "Por último, automatizamos la verificación con pytest. Las pruebas usan archivos JSON sintéticos y bases "
          "temporales, así que nunca tocan los datos reales. Cubren la huella del cliente, la ausencia de datos "
          "personales en todas las tablas, la estabilidad de los códigos C###, el canal, la idempotencia y la carga "
          "incremental, el calendario, los rezagos sin fuga, cada regla de calidad, la protección del endpoint con "
          "token y la migración de bases anteriores. Las 43 pruebas del ETL pasaron (Figura {f}). Con ellas, la suite "
          "completa del backend suma 215 pruebas, todas aprobadas."),
    ("fig", ["14a_terminal_pruebas_p1", "14a_terminal_pruebas_p2"], "Ejecución de las pruebas automáticas del ETL",
     "Salida real de pytest, mostrada en dos partes consecutivas. Elaboración propia."),

    ("h", "Resultado del objetivo 1"),
    ("p", "Con este pipeline cumplimos el objetivo específico 1. Extraemos los registros del sistema de Red Rooster, los "
          "limpiamos con nueve reglas de calidad medidas y documentadas, los estandarizamos (fechas, estados, métodos de "
          "pago y canal) y los almacenamos de forma segura en una base relacional analítica, sin datos personales y con "
          "los clientes identificados solo por un código anónimo."),
    ("p", "La base resultante tiene 3.042 pedidos, 5.022 líneas, 44 productos, 126 clientes anónimos y 236 días de "
          "calendario y de ventas diarias. Además, se actualiza de forma incremental sin duplicar registros y está "
          "respaldada por 43 pruebas automáticas. Esta base es el punto de partida para el análisis de los objetivos 2 "
          "y 3."),
]


# ---------------------------------------------------------------- utilidades XML
def run(texto: str, rpr: str = "") -> str:
    return f'<w:r>{f"<w:rPr>{rpr}</w:rPr>" if rpr else ""}<w:t xml:space="preserve">{escape(texto)}</w:t></w:r>'


def parrafo(texto: str) -> str:
    return f"<w:p>{run(texto)}</w:p>"


def titulo3(texto: str) -> str:
    return f'<w:p><w:pPr><w:pStyle w:val="Ttulo3"/></w:pPr>{run(texto)}</w:p>'


def tam_png(ruta: Path) -> tuple[int, int]:
    with ruta.open("rb") as f:
        cab = f.read(24)
    return struct.unpack(">II", cab[16:24])


class Imagenes:
    def __init__(self) -> None:
        self.n = 0
        self.rels: list[str] = []
        self.archivos: list[tuple[Path, str]] = []

    def dibujo(self, fid: str, descr: str, mantener: bool = True,
               ancho_max: int = ANCHO_EMU, alto_max: int | None = None) -> str:
        self.n += 1
        rid = f"rIdObj1_{self.n}"
        nombre = f"obj1_{self.n:02d}.png"
        ruta = AQUI / f"{fid}.png"
        self.archivos.append((ruta, nombre))
        self.rels.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                         f'relationships/image" Target="media/{nombre}"/>')
        w, h = tam_png(ruta)
        cx, cy = ancho_max, round(ancho_max * h / w)
        if alto_max and cy > alto_max:
            cx, cy = round(alto_max * w / h), alto_max
        did = 2000 + self.n
        d = escape(descr, {'"': "&quot;"})
        return (
            f'<w:p><w:pPr>{"<w:keepNext/>" if mantener else ""}<w:spacing w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/></w:pPr>'
            '<w:r><w:rPr><w:noProof/></w:rPr><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:effectExtent l="0" t="0" r="0" b="0"/>'
            f'<wp:docPr id="{did}" name="Imagen {did}" descr="{d}"/>'
            '<wp:cNvGraphicFramePr><a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'noChangeAspect="1"/></wp:cNvGraphicFramePr>'
            '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:nvPicPr><pic:cNvPr id="{did}" name="{nombre}"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>'
            '</wp:inline></w:drawing></w:r></w:p>'
        )


SECCION = {"vertical": ""}  # sectPr del cuerpo (carta vertical); se llena en principal()


def salto_seccion(horizontal: bool) -> str:
    """Párrafo que cierra la sección actual; la siguiente empieza en página nueva."""
    s = SECCION["vertical"]
    if horizontal:
        s = s.replace('<w:pgSz w:w="12240" w:h="15840" w:code="1"/>',
                      '<w:pgSz w:w="15840" w:h="12240" w:orient="landscape" w:code="1"/>')
        assert 'w:orient="landscape"' in s
    s = re.sub(r"<w:sectPr[^>]*>", '<w:sectPr><w:type w:val="nextPage"/>', s, count=1)
    return f'<w:p><w:pPr>{s}</w:pPr></w:p>'


def figura(num: int, ids: list[str], titulo: str, nota: str, img: Imagenes, horizontal: bool = False) -> str:
    xml = (f'<w:p><w:pPr><w:keepNext/><w:ind w:firstLine="0"/></w:pPr>{run(f"Figura {num}", "<w:b/>")}</w:p>'
           f'<w:p><w:pPr><w:keepNext/><w:ind w:firstLine="0"/></w:pPr>{run(titulo, "<w:i/>")}</w:p>')
    # Horizontal: hasta 9" de ancho y 4,6" de alto (el encabezado con logo resta alto útil) para que título, imagen y Nota quepan en la misma página.
    tam = {"ancho_max": 9 * 914400, "alto_max": round(4.6 * 914400)} if horizontal else {}
    # En figuras de varias imágenes solo la última se ata a la Nota; así la primera no arrastra página en blanco.
    xml += "".join(img.dibujo(i, titulo, mantener=(k == len(ids) - 1), **tam) for k, i in enumerate(ids))
    xml += ('<w:p><w:pPr><w:spacing w:after="240" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/></w:pPr>'
            f'{run("Nota.", "<w:i/><w:sz w:val=\"20\"/>")}{run(" " + nota, "<w:sz w:val=\"20\"/>")}</w:p>')
    # La sección vertical previa se cierra antes de la figura; la horizontal, después de su Nota.
    return salto_seccion(False) + xml + salto_seccion(True) if horizontal else xml


def texto_de(p: str) -> str:
    return "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))


def bloques(xml_cuerpo: str) -> list[str]:
    return re.findall(r"<w:tbl>.*?</w:tbl>|<w:p[ >].*?</w:p>|<w:sectPr.*?</w:sectPr>", xml_cuerpo, re.S)


# ---------------------------------------------------------------- armado
def construir_seccion(img: Imagenes) -> tuple[str, int]:
    num = 0
    partes = []
    pendientes: list[str] = []  # párrafos que citan la próxima figura
    for el in CONTENIDO:
        if el[0] == "h":
            partes.append(titulo3(el[1]))
        elif el[0] == "p":
            if "{f}" in el[1]:
                pendientes.append(len(partes))
            partes.append(el[1])
        else:
            num += 1
            for i in pendientes:
                partes[i] = parrafo(partes[i].replace("{f}", str(num)))
            pendientes = []
            partes.append(figura(num, el[1], el[2], el[3], img, horizontal=len(el) > 4 and el[4] == "horizontal"))
    partes = [p if p.startswith("<w:p") else parrafo(p) for p in partes]
    if pendientes:
        raise SystemExit("Hay párrafos que citan una figura que no existe")
    return "".join(partes), num


def reemplazar_texto(bloque: str, viejo: str, nuevo: str) -> str:
    """Reemplaza todo el texto de un párrafo (que contiene `viejo`) por `nuevo`, conservando pPr y el primer rPr."""
    assert viejo in texto_de(bloque), viejo
    ppr = re.search(r"<w:pPr>.*?</w:pPr>", bloque, re.S)
    apertura = re.match(r"<w:p[^>]*>", bloque).group(0)
    return f'{apertura}{ppr.group(0) if ppr else ""}{run(nuevo)}</w:p>'


def principal() -> None:
    trabajo = Path(tempfile.mkdtemp(prefix="obj1_docx_"))
    with zipfile.ZipFile(ORIGEN) as z:
        z.extractall(trabajo)
    doc_path = trabajo / "word" / "document.xml"
    xml = doc_path.read_text(encoding="utf-8")
    ini, fin = xml.index("<w:body>") + len("<w:body>"), xml.index("</w:body>")
    bs = bloques(xml[ini:fin])
    SECCION["vertical"] = bs[-1]
    assert bs[-1].startswith("<w:sectPr") and '<w:pgSz w:w="12240" w:h="15840" w:code="1"/>' in bs[-1]
    if "".join(bs) != xml[ini:fin]:
        raise SystemExit("El cuerpo tiene elementos fuera de párrafos/tablas; no se puede reconstruir sin perderlos")

    def idx(pred, desde=0):
        for i in range(desde, len(bs)):
            if pred(bs[i]):
                return i
        raise SystemExit("No se encontró un bloque esperado")

    es_t1 = lambda b: 'w:val="Ttulo1"' in b
    h1 = idx(lambda b: es_t1(b) and texto_de(b).startswith("Desarrollo del objetivo 1"))
    h2 = idx(lambda b: es_t1(b) and texto_de(b).startswith("Desarrollo del objetivo 2"))
    viejo_obj1 = bs[h1 + 1:h2]
    # Los dos primeros párrafos son el resumen del ETL anterior; desde "Diagnóstico de la caída." es el diagnóstico.
    d0 = next(i for i, b in enumerate(viejo_obj1) if texto_de(b).startswith("Diagnóstico de la caída."))
    diagnostico = viejo_obj1[d0:]
    diagnostico[0] = reemplazar_texto(diagnostico[0], "Diagnóstico de la caída.",
                                      "La Figura 1 muestra la caída mensual en pedidos por día abierto.")

    img = Imagenes()
    seccion, n_nuevas = construir_seccion(img)

    # Renumerar figuras antiguas (1–6) en todo lo que queda del documento.
    def renumerar(b: str) -> str:
        return re.sub(r"(<w:t[^>]*>[^<]*?)\bFigura (\d+)\b",
                      lambda m: f"{m.group(1)}Figura {int(m.group(2)) + n_nuevas}", b)

    bs_resto_antes = [renumerar(b) for b in bs[:h1]]
    diagnostico = [renumerar(b) for b in diagnostico]
    bs_desde_obj2 = [renumerar(b) for b in bs[h2:]]

    # Encabezados
    enc1 = bs[h1].replace("Desarrollo del objetivo 1: proceso ETL y diagnóstico de la caída de ventas",
                          "Desarrollo del objetivo 1: proceso ETL")
    bs_desde_obj2[0] = bs_desde_obj2[0].replace(
        "Desarrollo del objetivo 2: modelos de demanda, venta cruzada y segmentación",
        "Desarrollo del objetivo 2: diagnóstico de la caída de ventas, modelos de demanda, venta cruzada y segmentación")
    assert "diagnóstico de la caída de ventas, modelos" in bs_desde_obj2[0]

    # Fuente de datos, Tabla 1 y fases (antes del objetivo 1)
    for i, b in enumerate(bs_resto_antes):
        t = texto_de(b)
        if t.startswith("La fuente son los archivos JSON"):
            bs_resto_antes[i] = reemplazar_texto(
                b, "La fuente son",
                "La fuente son los archivos JSON del sistema de pedidos y caja de Red Rooster, copiados desde su "
                "servidor: BD/pedidos.json, con los pedidos, y BD/productos.json, con el catálogo. La Tabla 1 resume las "
                "tablas que resultan después del ETL, con corte al 13 de noviembre de 2026. El diagnóstico de la caída de "
                "ventas y los modelos del objetivo 2 se calcularon con el corte del 22 de octubre de 2026.")
        elif t.startswith("Nota. Periodo: 23 de marzo a 22 de octubre"):
            bs_resto_antes[i] = b.replace("22 de octubre de 2026. Elaboración propia.",
                                          "13 de noviembre de 2026. Además, la tabla customers guarda 126 clientes "
                                          "anónimos (C001 a C126) y calidad_datos las 9 reglas de calidad. "
                                          "Elaboración propia.")
            assert "13 de noviembre" in bs_resto_antes[i]
        elif t.startswith("1. Preparación (ETL)."):
            bs_resto_antes[i] = reemplazar_texto(
                b, "1. Preparación",
                "1. Preparación (ETL). Lectura de los JSON con una huella SHA-256 que permite cargas repetibles e "
                "incrementales; conversión de todas las fechas a hora de Colombia; estandarización de estados, métodos de "
                "pago y canal; seudonimización de los clientes con HMAC-SHA256 y una clave secreta, que se traduce a un "
                "código C001, C002…; medición de nueve reglas de calidad; y carga en SQLite dentro de una sola "
                "transacción, con un calendario y una tabla de ventas diarias para el análisis. Se verifican 43 pruebas "
                "automáticas de integridad, privacidad e idempotencia.")
        elif b.startswith("<w:tbl>") and ">dim_fecha<" in b and ">ventas_diarias<" in b:
            filas = [("pedidos", "sales", "2.810", "3.042",
                      "Un registro por pedido: fecha y hora, canal, estado, método de pago, total, código anónimo del cliente y zona",
                      "Un registro por pedido: fecha y hora local, canal, estado, método de pago, total y cliente anónimo"),
                     ("detalle_pedido", "sale_items", "4.565", "5.022", None, None),
                     ("productos", "products", "44", "44", "Catálogo con precio, costo y margen", "Catálogo con precio y costo"),
                     ("dim_fecha", "dim_fecha", "244", "236", None, None),
                     ("ventas_diarias", "ventas_diarias", "213", "236",
                      "Pedidos e ingresos por día, con rezagos y promedios móviles",
                      "Pedidos, ingresos y ticket por día, con rezagos y media móvil sin fuga")]
            for nom_v, nom_n, reg_v, reg_n, cont_v, cont_n in filas:
                for v, n in ((nom_v, nom_n), (reg_v, reg_n), (cont_v, cont_n)):
                    if v is None or v == n:
                        continue
                    assert f">{escape(v)}<" in b, v
                    b = b.replace(f">{escape(v)}<", f">{escape(n)}<", 1)
            bs_resto_antes[i] = b

    nuevo_obj2 = [bs_desde_obj2[0], titulo3("Diagnóstico de la caída de ventas")] + diagnostico + bs_desde_obj2[1:]

    # Referencias nuevas, en orden alfabético después de Hyndman.
    refs = ('<w:p><w:pPr><w:pStyle w:val="Bibliografa"/><w:ind w:left="709" w:hanging="709"/></w:pPr>'
            + run("Kimball, R., & Ross, M. (2013). ") + run("The data warehouse toolkit: The definitive guide to "
                                                             "dimensional modeling", "<w:i/>")
            + run(" (3.ª ed.). Wiley.") + "</w:p>"
            + '<w:p><w:pPr><w:pStyle w:val="Bibliografa"/><w:ind w:left="709" w:hanging="709"/></w:pPr>'
            + run("Krawczyk, H., Bellare, M., & Canetti, R. (1997). ")
            + run("HMAC: Keyed-hashing for message authentication", "<w:i/>")
            + run(" (RFC 2104). Internet Engineering Task Force. https://doi.org/10.17487/RFC2104") + "</w:p>")
    k = next(i for i, b in enumerate(nuevo_obj2) if texto_de(b).startswith("Hyndman, R. J."))
    nuevo_obj2.insert(k + 1, refs)

    cuerpo = "".join(bs_resto_antes) + enc1 + seccion + "".join(nuevo_obj2)
    xml = xml[:ini] + cuerpo + xml[fin:]
    doc_path.write_text(xml, encoding="utf-8")

    # Imágenes y relaciones
    media = trabajo / "word" / "media"
    for ruta, nombre in img.archivos:
        shutil.copyfile(ruta, media / nombre)
    rels = trabajo / "word" / "_rels" / "document.xml.rels"
    r = rels.read_text(encoding="utf-8")
    rels.write_text(r.replace("</Relationships>", "".join(img.rels) + "</Relationships>"), encoding="utf-8")
    ct = (trabajo / "[Content_Types].xml").read_text(encoding="utf-8")
    assert 'Extension="png"' in ct

    if DESTINO.exists():
        raise SystemExit(f"Ya existe {DESTINO.name}; muévalo o bórrelo antes de regenerar.")
    with zipfile.ZipFile(DESTINO, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(trabajo.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(trabajo).as_posix())
    shutil.rmtree(trabajo)
    print(f"Figuras nuevas: {n_nuevas}; imágenes: {img.n}; figuras antiguas renumeradas +{n_nuevas}")
    print(f"Escrito: {DESTINO}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    principal()
