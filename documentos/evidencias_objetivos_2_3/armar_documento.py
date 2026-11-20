"""Arma el documento final (objetivos 2 y 3) a partir de «Proyecto integrador Red Rooster.docx».

Uso (desde la raíz del proyecto):  python documentos\\evidencias_objetivos_2_3\\armar_documento.py
Genera documentos\\Proyecto integrador Red Rooster_final.docx (no sobrescribe otros archivos).
Reutiliza las utilidades XML del armado del Objetivo 1. Las cifras del texto salen de
backend/analisis/salidas/*.txt|json y de salidas/registro.json de esta carpeta.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

AQUI = Path(__file__).resolve().parent
DOCS = AQUI.parent
sys.path.insert(0, str(DOCS / "evidencias_objetivo_1"))
import armar_documento as obj1  # noqa: E402  (run, parrafo, titulo3, tam_png, salto_seccion, texto_de, bloques, reemplazar_texto)

ORIGEN = DOCS / "Proyecto integrador Red Rooster.docx"
DESTINO = DOCS / "Proyecto integrador Red Rooster_final.docx"
ANCHO_EMU = 5486400               # 6 pulgadas
ALTO_MAX = round(7.2 * 914400)    # deja espacio para «Figura N», título y Nota en la misma página
MANIFIESTO = {f["id"]: f for f in json.loads((AQUI / "manifiesto.json").read_text(encoding="utf-8"))["figuras"]}
ASESOR = "o3_08b_app_asesor"
HAY_ASESOR = (AQUI / f"{ASESOR}.png").exists()

run, parrafo, titulo3, texto_de = obj1.run, obj1.parrafo, obj1.titulo3, obj1.texto_de


def codigo(fid: str) -> str:
    f = MANIFIESTO[fid]
    lineas = f["lineas_texto"].replace("-", "–")
    return f"Fragmento de {f['archivo_codigo']}, líneas {lineas}. Elaboración propia."


AN = ("Captura de la salida real del script en la terminal; la salida completa queda en backend/analisis/salidas/. "
      "Elaboración propia con datos del sistema de pedidos de Red Rooster.")
GR = "Gráfica generada por el script de análisis. Elaboración propia con datos del sistema de pedidos de Red Rooster."
APP = ("Captura de la aplicación en ejecución sobre una copia de la base real, tomada con Playwright. "
       "Elaboración propia con datos del sistema de pedidos de Red Rooster.")

# ---------------------------------------------------------------- contenido
# ("h", titulo3) | ("p", texto con {f} = próxima figura y {t} = próxima tabla) | ("fig", [ids], titulo, nota)
# | ("tabla", titulo, encabezados, filas, nota, anchos)
OBJ2 = [
    ("p", "En este objetivo caracterizamos el comportamiento histórico de las ventas de Red Rooster a partir de la base "
          "analítica que construimos en el objetivo 1. Escribimos el análisis como un paquete de scripts de Python "
          "(backend/analisis/), uno por paso, que leen la base en modo de solo lectura y guardan cada resultado en "
          "archivos JSON, de texto y gráficas dentro de backend/analisis/salidas/. Así, cada cifra de este capítulo se "
          "puede reproducir con un solo comando: venv\\Scripts\\python -m analisis.correr_todo."),
    ("p", "Para comparar el antes y el después de la caída definimos dos periodos: un periodo base, del 1 de mayo al 31 "
          "de agosto de 2026, y un periodo de caída, del 1 de septiembre al 12 de noviembre de 2026. Marzo y abril "
          "quedan por fuera porque corresponden al arranque del sistema, y el 13 de noviembre se excluye porque el día "
          "estaba incompleto en el momento del corte. Como el restaurante descansa los martes, todas las comparaciones "
          "se hacen en pedidos pagados por día abierto. Las capturas se tomaron con Playwright a partir de una "
          "ejecución real; el script que las regenera es documentos/evidencias_objetivos_2_3/generar_evidencias.py."),

    ("h", "Paso 1. Preparamos el paquete de análisis"),
    ("p", "El módulo comun.py concentra las definiciones que comparten todos los pasos (Figura {f}): los periodos, la "
          "regla de día abierto, la conexión a la base en modo de solo lectura (mode=ro), que impide modificar los datos "
          "por accidente, y dos correcciones del catálogo. La primera es el precio real de cada producto, que tomamos "
          "como la mediana de lo que efectivamente se cobró en los pedidos pagados, porque el precio de lista no siempre "
          "coincide con el cobrado. La segunda es la regla del costo faltante: cuando el costo registrado es cero o es "
          "igual o mayor que el precio, lo estimamos multiplicando el precio por la mediana de la razón costo/precio de "
          "los productos de la misma categoría. Esta regla vive en un solo lugar del backend (app/domain/costos.py) y la "
          "usan tanto el análisis como la plataforma."),
    ("fig", ["o2_01a_codigo_comun"], "Definiciones comunes del paquete de análisis", codigo("o2_01a_codigo_comun")),

    ("h", "Paso 2. Describimos el comportamiento de las ventas"),
    ("p", "Empezamos con un análisis exploratorio descriptivo (Tukey, 1977) por mes, día de la semana, hora, canal y "
          "método de pago. La Figura {f} muestra el cálculo de los pedidos por día abierto de cada mes, que es la medida "
          "central de todo el capítulo. Entre el 23 de marzo y el 13 de noviembre de 2026 se pagaron 3.017 pedidos por "
          "$138.605.100; los 25 pedidos no pagados se excluyen."),
    ("fig", ["o2_02a_codigo_a01"], "Cálculo de los pedidos por día abierto de cada mes", codigo("o2_02a_codigo_a01")),
    ("p", "En el periodo base el restaurante atendió en promedio 16,46 pedidos por día abierto (mediana de 16 y "
          "desviación estándar de 4,50), y en el periodo de caída 13,11 (mediana de 13 y desviación de 5,83), una baja "
          "del 20,3 % (Figura {f}). La caída empieza en septiembre (14,0 pedidos por día abierto) y es más fuerte en "
          "octubre (12,3). Además, la dispersión aumentó: el mínimo pasó de 7 pedidos a 1, lo que anticipa la presencia "
          "de días anómalos."),
    ("fig", ["o2_02b_terminal_a01"], "Perfil descriptivo de las ventas", AN),
    ("p", "El pico de pedidos es a la 1 p. m., con un segundo repunte entre las 7 y las 8 p. m. En el periodo de caída "
          "la participación del almuerzo subió de 39,8 % a 49,3 %, mientras que la tarde y la noche bajaron. El ticket "
          "promedio pasó de $45.339 a $49.504, así que el problema es de volumen de pedidos y no de precio. La Figura "
          "{f} resume la evolución mensual."),
    ("fig", ["o2_02c_grafica_mes"], "Pedidos pagados por día abierto, por mes (2026)",
     "Marzo y abril corresponden al arranque del sistema y noviembre llega hasta el día 12. Los martes (descanso) se "
     "excluyen. Elaboración propia con datos del sistema de pedidos de Red Rooster."),

    ("h", "Paso 3. Identificamos estacionalidades y días anómalos"),
    ("p", "Para la estacionalidad calculamos un índice por día de la semana (la media de ese día dividida entre la media "
          "general) y comparamos los días de quincena y los festivos con el resto, usando la tabla dim_fecha del "
          "objetivo 1. Para las anomalías aplicamos la regla de Tukey: un día es atípico si sus pedidos quedan por "
          "debajo de Q1 − 1,5 × IQR (Figura {f})."),
    ("fig", ["o2_03a_codigo_a02"], "Estacionalidad por día de la semana y detección de días anómalos",
     codigo("o2_03a_codigo_a02")),
    ("p", "La caída no fue pareja entre los días de la semana (Figura {f}). Los lunes pasaron de 16,4 a 8,5 pedidos por "
          "día abierto (−48 %) y los sábados de 17,8 a 9,9 (−44 %), mientras que de miércoles a domingo las variaciones "
          "estuvieron entre +3 % y −11 %. La quincena casi no cambia la demanda (−2,1 % en el índice ajustado) y los "
          "festivos la reducen en 11,8 %."),
    ("fig", ["o2_03b_grafica_dia_semana"], "Pedidos por día abierto según el día de la semana, periodo base frente a caída",
     GR),
    ("p", "La regla de Tukey aplicada a los dos periodos marca un solo día atípico, el sábado 19 de septiembre, con 1 "
          "pedido, porque la propia caída ensancha la dispersión. Por eso listamos también los días casi sin pedidos, "
          "con 5 pedidos o menos, un valor que nunca se dio en el periodo base, cuyo mínimo fue 7. Encontramos 9 días "
          "así, todos en el periodo de caída, y 8 de ellos fueron lunes o sábados (Figura {f}). Dos coinciden con "
          "festivos (12 de octubre y 2 de noviembre). Parecen fallas operativas, como abrir tarde, cerrar temprano o no "
          "registrar pedidos, más que falta de clientes."),
    ("fig", ["o2_03c_grafica_serie_anomalias"], "Serie diaria de pedidos por día abierto con los días anómalos marcados",
     GR),
    ("p", "Por último revisamos el canal de domicilio. El último domicilio antes de la caída se registró el 30 de agosto "
          "y el siguiente el 26 de octubre: el servicio estuvo suspendido 56 días y desde entonces se reanudó poco a "
          "poco. En el periodo de caída hubo 15 domicilios, frente a 115 en el periodo base (Figura {f})."),
    ("fig", ["o2_03d_terminal_a02"], "Índices de estacionalidad, días anómalos y servicio de domicilio", AN),

    ("h", "Paso 4. Comprobamos la caída con pruebas inferenciales"),
    ("p", "Para saber si la caída es real o puede deberse al azar aplicamos pruebas no paramétricas, porque los pedidos "
          "por día no siguen una distribución normal (Figura {f}). Usamos la prueba U de Mann-Whitney (Mann & Whitney, "
          "1947) para comparar los pedidos por día abierto de los dos periodos, con el delta de Cliff (Cliff, 1993) como "
          "tamaño del efecto; un intervalo de confianza bootstrap del 95 % con 10.000 réplicas (Efron & Tibshirani, "
          "1993) para la diferencia de medias; la prueba chi-cuadrado de independencia con la V de Cramér (Cramér, "
          "1946) para la mezcla de canales; y la prueba de Kruskal-Wallis (Kruskal & Wallis, 1952) para el día de la "
          "semana. Todas se calcularon con SciPy (Virtanen et al., 2020) y un nivel de significancia de 0,05."),
    ("fig", ["o2_04a_codigo_a03"], "Pruebas de inferencia sobre la caída", codigo("o2_04a_codigo_a03")),
    ("p", "Los resultados confirman la caída (Figura {f}). La prueba de Mann-Whitney da U = 4.284,5 con p = 0,0010, y el "
          "intervalo bootstrap de la diferencia de medias va de 1,72 a 5,03 pedidos por día abierto, así que no incluye "
          "el cero. El tamaño del efecto es pequeño (delta de Cliff de 0,304). Como prueba de robustez repetimos la "
          "comparación sin los 9 días casi sin pedidos: la diferencia baja a 1,63 pedidos y deja de ser significativa "
          "(p = 0,0563), aunque su intervalo bootstrap, de 0,20 a 3,05, sigue sin incluir el cero. Es decir, buena parte "
          "de la caída se concentra en esos días anómalos."),
    ("fig", ["o2_04b_terminal_a03_p1", "o2_04b_terminal_a03_p2"], "Resultados de las pruebas de inferencia", AN),
    ("p", "La mezcla de canales también cambió de forma significativa (chi-cuadrado = 44,14 con 2 grados de libertad, "
          "p < 0,0001 y V de Cramér de 0,131): los domicilios bajaron de 6,6 % a 1,8 % de los pedidos y la mesa subió de "
          "38,7 % a 49,6 %. El día de la semana no muestra diferencias claras en el periodo base (Kruskal-Wallis, "
          "p = 0,076), pero sí en el de caída (p = 0,017), lo que coincide con la concentración de la baja en lunes y "
          "sábados. Finalmente, aunque la prueba sobre el ticket da p = 0,0073, el efecto es insignificante (delta de "
          "Cliff de −0,066) y el intervalo de la diferencia de medias incluye el cero, así que el precio no explica la "
          "caída."),

    ("h", "Paso 5. Descompusimos la caída en sus factores"),
    ("p", "Para identificar los factores que determinan la variación, descompusimos la diferencia de 3,35 pedidos por día "
          "abierto en tres componentes que suman exactamente el total (Figura {f}): los domicilios perdidos, los días "
          "casi sin pedidos y el cambio de la demanda en los días normales."),
    ("fig", ["o2_05a_codigo_a04"], "Descomposición de la caída en sus tres componentes", codigo("o2_05a_codigo_a04")),
    ("p", "Los días casi sin pedidos explican 1,68 pedidos por día abierto (50,0 % de la caída), la suspensión de los "
          "domicilios 0,84 (25,2 %) y la baja de la demanda en los días normales 0,83 (24,8 %) (Figura {f})."),
    ("fig", ["o2_05c_grafica_cascada"], "Descomposición de la caída de pedidos por día abierto",
     "Periodo base: 1 de mayo a 31 de agosto. Periodo de caída: 1 de septiembre a 12 de noviembre de 2026. Elaboración "
     "propia con datos del sistema de pedidos de Red Rooster."),
    ("p", "Como la definición de día anómalo es una decisión del análisis, medimos su sensibilidad (Figura {f}). Con la "
          "regla de Tukey sobre ambos periodos, que marca un solo día, la demanda normal pasaría a explicar el 69 % de la "
          "caída, y con la valla del periodo base, el 52 %. El peso de los domicilios (25 %) no cambia con ninguna "
          "definición. Por eso concluimos que los días anómalos y la suspensión de los domicilios explican entre la "
          "mitad y las tres cuartas partes de la caída, y que el resto corresponde a una baja real de la demanda."),
    ("fig", ["o2_05b_terminal_a04"], "Componentes de la caída y sensibilidad a la definición de día anómalo", AN),

    ("h", "Paso 6. Comparamos modelos de predicción de demanda"),
    ("p", "Para predecir los pedidos por día abierto pusimos a competir tres modelos con la misma validación temporal "
          "(Hyndman & Athanasopoulos, 2021): M1, el promedio de los últimos 24 días abiertos; M2, el promedio del mismo "
          "día de la semana en las últimas 4 semanas; y M3, XGBoost (Chen & Guestrin, 2016), que predice la proporción de "
          "cada día sobre el nivel reciente a partir del día de la semana, la quincena, el festivo y la semana anterior. "
          "La validación es de tipo walk-forward: en cada ventana el modelo solo se entrena con los días anteriores al "
          "origen, así que nunca ve el futuro (Figura {f}). Hicimos 8 pruebas semanales a 7 días y 2 pruebas a 30 días, "
          "y calificamos solo los días abiertos que no son anómalos."),
    ("fig", ["o2_06a_codigo_a05"], "Validación walk-forward y modelos de demanda", codigo("o2_06a_codigo_a05")),
    ("p", "El promedio simple de los últimos 24 días abiertos ganó en los dos horizontes (Tabla {t})."),
    ("tabla", "Error de los modelos de demanda en la validación temporal",
     ["Modelo", "MAE a 7 días", "R² a 7 días", "MAE a 30 días", "R² a 30 días"],
     [["M1. Promedio de los últimos 24 días abiertos", "3,94", "−0,217", "3,81", "−0,186"],
      ["M2. Promedio del mismo día de la semana (4 semanas)", "4,01", "−0,328", "4,21", "−0,557"],
      ["M3. XGBoost (proporción sobre el nivel reciente)", "4,43", "−0,559", "4,27", "−0,455"]],
     "MAE: error absoluto medio, en pedidos por día abierto. A 7 días se evaluaron 39 días en 8 ventanas; a 30 días, "
     "42 días en 2 ventanas. Los martes y los días casi sin pedidos no se califican. Elaboración propia.",
     [3960, 1350, 1350, 1350, 1350]),
    ("p", "XGBoost quedó de último a 7 días (MAE de 4,43) y a 30 días (4,27), y todos los modelos tienen un R² negativo: "
          "con siete meses de historia y un cambio de nivel reciente, la variación diaria, de cerca de ±4 pedidos, es "
          "mayor que lo que cualquier modelo logra explicar. Las variables que más usó XGBoost fueron la semana anterior "
          "(24,6 %), el día de la semana (23,5 %) y la quincena (23,4 %) (Figura {f}). Siguiendo la regla que nos fijamos "
          "en la justificación, un modelo complejo solo se usa si supera a la línea base, así que el pronóstico usa M1."),
    ("fig", ["o2_06b_terminal_a05"], "Comparación de los modelos e importancia de las variables de XGBoost", AN),
    ("p", "El pronóstico para los próximos 30 días es de 12,5 pedidos por día abierto, con un rango probable de 8,7 a 16,3: "
          "unos 324 pedidos en los 26 días abiertos entre el 14 de noviembre y el 13 de diciembre de 2026 (Figura {f}). "
          "Con el ticket promedio del periodo de caída ($49.504), equivale a ventas de unos $619.000 por día abierto, una "
          "cifra útil para planear compras de insumos y personal."),
    ("fig", ["o2_06c_grafica_pronostico"], "Pronóstico de pedidos por día abierto para los próximos 30 días",
     "La franja muestra el rango probable (pronóstico ± MAE de validación). Los martes no se muestran porque el "
     "restaurante descansa. Elaboración propia con datos del sistema de pedidos de Red Rooster."),

    ("h", "Paso 7. Buscamos oportunidades de venta cruzada"),
    ("p", "Para la venta cruzada aplicamos el algoritmo Apriori (Agrawal & Srikant, 1994) con MLxtend (Raschka, 2018) "
          "sobre las canastas de los pedidos pagados, por producto y por categoría (Figura {f}). Como solo el 30,4 % de "
          "los pedidos tiene dos o más productos distintos (918 de 3.017), los pares reales son poco frecuentes; por eso "
          "calibramos los umbrales en un soporte mínimo de 0,5 %, una confianza mínima de 15 % y un lift mayor que 1. "
          "Con los umbrales por defecto de la plataforma, pensados para datos sintéticos (soporte de 2 %), no se "
          "encontraba ninguna regla."),
    ("fig", ["o2_07a_codigo_a06"], "Reglas de asociación, hallazgos del catálogo y armado de combos",
     codigo("o2_07a_codigo_a06")),
    ("p", "Con estos umbrales encontramos 32 reglas entre productos y 22 entre categorías (Figura {f}). Las más fuertes "
          "unen platos de la carta con bebidas naturales, por ejemplo Mojarra Frita con Limonada Natural (lift de 7,62) "
          "y Chuleta Apanada con Jugo Natural de fresa (lift de 6,84)."),
    ("fig", ["o2_07b_terminal_a06_p1", "o2_07b_terminal_a06_p2"], "Reglas de asociación, márgenes y combos sugeridos", AN),
    ("p", "Al calcular los márgenes encontramos tres problemas de calidad en el catálogo. El Churrasco, el plato de la "
          "carta más vendido, tiene registrado un costo igual a su precio de lista ($40.000); la Chuleta Apanada figura "
          "con un precio de lista de $350.000, aunque se cobra a $30.000; y la sopa tiene costo cero y el 42 % de sus "
          "ventas a otro precio. Por eso usamos el precio real cobrado, estimamos los costos faltantes con la regla de "
          "la categoría y dejamos estos casos para confirmarlos con el dueño."),
    ("p", "El hallazgo principal está en la bebida: el 81,4 % de los pedidos con platos sale sin bebida, desde el 54,3 % "
          "en la carta hasta el 93,8 % en las promociones (Figura {f}), aunque las bebidas naturales son de los productos "
          "de mayor margen del menú (87,0 % la limonada y 77,0 % el jugo de fresa)."),
    ("fig", ["o2_07c_grafica_sin_bebida"], "Porcentaje de pedidos sin bebida por categoría de plato",
     "Un pedido con platos de varias categorías cuenta en cada una de ellas. Elaboración propia con datos del sistema de "
     "pedidos de Red Rooster."),
    ("p", "Con los 14 pares de plato y bebida que tienen un lift de 2 o más armamos combos con los cinco más frecuentes, a "
          "un precio 10 % menor que la suma de los precios reales (Tabla {t})."),
    ("tabla", "Combos sugeridos a partir de las reglas de asociación",
     ["Combo", "Soporte", "Lift", "Precio suelto", "Precio combo", "Margen del combo"],
     [["Churrasco + Limonada Natural", "1,49 %", "4,28", "$45.000", "$40.500", "$25.071 (61,9 %)"],
      ["Churrasco + Jugo Natural de fresa", "1,16 %", "3,76", "$45.000", "$40.500", "$24.071 (59,4 %)"],
      ["Churrasco + Coca-Cola 1,5 L", "1,09 %", "4,32", "$43.000", "$38.700", "$20.523 (53,0 %)"],
      ["Chuleta Apanada + Jugo Natural de fresa", "0,96 %", "6,84", "$40.000", "$36.000", "$25.421 (70,6 %)"],
      ["Churrasco + Coca-Cola Zero 500 ml", "0,83 %", "4,07", "$40.000", "$36.000", "$19.857 (55,2 %)"]],
     "Soporte: porcentaje de los 3.017 pedidos pagados que incluyen ambos productos. Lift: cuántas veces más se piden "
     "juntos que por casualidad. El margen es el precio del combo menos el costo de los dos productos; el costo del "
     "Churrasco se estimó con la regla de la categoría. Elaboración propia.",
     [3160, 1000, 800, 1400, 1400, 1600]),

    ("h", "Paso 8. Segmentamos a los clientes"),
    ("p", "Los clientes solo se pueden identificar en los domicilios, porque en mesa y para llevar no se registra el "
          "teléfono; por eso la segmentación se hace sobre los 121 clientes de domicilio con pedidos pagados (229 "
          "pedidos). Calculamos para cada uno la recencia, la frecuencia y el monto (RFM; Hughes, 1994), los convertimos "
          "en puntajes de 1 a 5 por quintiles y asignamos siete segmentos con reglas explícitas que se evalúan en orden "
          "(Figura {f}). Como comparación aplicamos K-Means (MacQueen, 1967) con 2 a 6 grupos sobre las variables en "
          "logaritmo y estandarizadas, evaluado con el coeficiente de silueta (Rousseeuw, 1987). La recencia se mide "
          "hasta el 14 de noviembre de 2026, el día siguiente al último domicilio: si el servicio vuelve a suspenderse, "
          "esta fecha evita que todos los clientes aparezcan como perdidos por una decisión del negocio y no por su "
          "comportamiento."),
    ("fig", ["o2_08a_codigo_a07"], "Reglas de segmentación RFM, puntajes por quintiles y K-Means",
     codigo("o2_08a_codigo_a07")),
    ("p", "La Tabla {t} resume los segmentos."),
    ("tabla", "Segmentos de clientes de domicilio según el modelo RFM",
     ["Segmento", "Clientes", "% de clientes", "% del dinero", "Acción sugerida"],
     [["Campeones", "10", "8,3 %", "22,0 %", "Reconocerlos y darles un beneficio exclusivo"],
      ["Leales", "17", "14,0 %", "22,2 %", "Mantener la relación con un programa de puntos"],
      ["Prometedores", "2", "1,7 %", "0,9 %", "Invitarlos a un tercer pedido con un combo"],
      ["Necesitan atención", "5", "4,1 %", "3,8 %", "Recordarles el menú antes de que se enfríen"],
      ["En riesgo", "16", "13,2 %", "18,7 %", "Campaña de reactivación con oferta personal"],
      ["Nuevos", "28", "23,1 %", "13,4 %", "Dar la bienvenida y lograr el segundo pedido"],
      ["Una sola vez", "43", "35,5 %", "18,9 %", "Oferta de regreso con envío gratis"]],
     "Fecha de referencia: 14 de noviembre de 2026. Total: 121 clientes y $9.251.800. Los porcentajes se redondean a un "
     "decimal. Elaboración propia.",
     [1900, 1000, 1200, 1200, 4060]),
    ("p", "Los Campeones y los Leales, el 22,3 % de los clientes, aportaron el 44,2 % del dinero de los domicilios "
          "(Figura {f}). En el otro extremo, 43 clientes (35,5 %) compraron una sola vez y 16 están en riesgo: gastaron "
          "bastante, pero no han vuelto a pedir. Ellos son el público natural de una campaña de reactivación."),
    ("fig", ["o2_08c_grafica_clientes_dinero"], "Participación de cada segmento en los clientes y en el dinero",
     "Comparación entre el porcentaje de clientes y el porcentaje del gasto total de cada segmento. Elaboración propia con "
     "datos del sistema de pedidos de Red Rooster."),
    ("p", "K-Means obtuvo su mejor silueta con 4 grupos (0,539), por encima de 0,5, lo que indica grupos razonablemente "
          "separados (Figura {f}). Sin embargo, su concordancia con los segmentos por reglas es moderada (índice de Rand "
          "ajustado de 0,421; Hubert & Arabie, 1985) y sus grupos son más difíciles de explicar al dueño. Por eso usamos "
          "los segmentos por reglas para las acciones, y la plataforma conserva K-Means como segmentación automática "
          "(objetivo 3)."),
    ("fig", ["o2_08b_terminal_a07_p1", "o2_08b_terminal_a07_p2"], "Segmentos RFM y comparación con K-Means", AN),

    ("h", "Paso 9. Automatizamos las pruebas del análisis"),
    ("p", "Igual que con el ETL, escribimos pruebas automáticas para el paquete de análisis (Figura {f}). Usan una base "
          "sintética con el mismo esquema que la real y comprueban, entre otras cosas, que las pruebas estadísticas "
          "coinciden con cálculos hechos a mano, que la descomposición de la caída suma exactamente el total con las tres "
          "definiciones de día anómalo, que el pronóstico no usa datos posteriores a cada origen, que las salidas no "
          "contienen datos personales y que la base no se modifica. Las 126 pruebas pasan."),
    ("fig", ["o2_09a_terminal_pruebas_p1", "o2_09a_terminal_pruebas_p2"], "Pruebas automáticas del paquete de análisis",
     "Captura de la ejecución real de pytest. Elaboración propia."),

    ("h", "Resultado del objetivo 2"),
    ("p", "Con este análisis cumplimos el objetivo específico 2. Caracterizamos el comportamiento de las ventas con "
          "estadística descriptiva e inferencial: la caída de 16,46 a 13,11 pedidos por día abierto (−20,3 %) es "
          "estadísticamente significativa (p = 0,0010) y no se explica por el precio. Identificamos su estacionalidad "
          "(la caída se concentra en lunes y sábados, los festivos reducen la demanda y la quincena no la cambia), sus "
          "anomalías (9 días casi sin pedidos y 56 días sin domicilios) y sus factores determinantes: los días anómalos "
          "explican el 50 % de la caída, la suspensión de los domicilios el 25 % y la demanda en los días normales el "
          "25 % restante."),
    ("p", "Además dejamos un pronóstico validado de 12,5 pedidos por día abierto, cinco combos de plato y bebida con "
          "márgenes de 53 % a 71 % y siete segmentos de clientes con su acción sugerida. Todo el análisis se reproduce con "
          "un comando y está respaldado por 126 pruebas automáticas."),
]

OBJ3 = [
    ("p", "En este objetivo integramos los modelos y las visualizaciones en la aplicación web Micronegocio, para que el "
          "dueño del restaurante consulte los resultados sin herramientas externas. Partimos de la plataforma que ya "
          "teníamos construida y probada con datos sintéticos y le hicimos los ajustes que mostró el análisis del "
          "objetivo 2. Las capturas se tomaron con Playwright con la aplicación en ejecución sobre una copia de la base "
          "real."),

    ("h", "Paso 1. Partimos de la arquitectura de la plataforma"),
    ("p", "La plataforma tiene una arquitectura hexagonal (Figura {f}): el frontend en React consume una API en FastAPI; "
          "la API llama a los casos de uso, que dependen solo de puertos; y los adaptadores conectan esos puertos con "
          "SQLite, con el cifrado Fernet, con los modelos de aprendizaje automático y con Google Gemini. Así, el dominio "
          "no depende de la base de datos ni de los servicios externos. Del lado de los datos, el ETL del objetivo 1 "
          "carga la base, el pipeline de modelos entrena XGBoost, Apriori y K-Means, y sus resultados quedan en las "
          "tablas analytics_*, que alimentan los tableros y el asesor."),
    ("fig", ["o3_01a_arquitectura"], "Arquitectura de la plataforma y flujo de datos",
     "Los nombres de los módulos y de las tablas se tomaron directamente del código fuente. Elaboración propia."),

    ("h", "Paso 2. Llevamos la calibración a la plataforma"),
    ("p", "El análisis del objetivo 2 mostró que los umbrales por defecto de Apriori, pensados para datos sintéticos, no "
          "encontraban ninguna regla en los datos reales. Por eso cambiamos los valores por defecto de la plataforma a un "
          "soporte mínimo de 0,5 %, una confianza mínima de 15 % y un lift mayor que 1, tanto en la configuración como en "
          "el archivo de ejemplo de las variables de entorno (Figura {f}). Los valores siguen siendo configurables para "
          "otros micronegocios."),
    ("fig", ["o3_02a_codigo_umbrales"], "Umbrales de Apriori y del asesor en la configuración de la plataforma",
     codigo("o3_02a_codigo_umbrales")),
    ("p", "También llevamos a la plataforma la regla del costo faltante (Figura {f}). La función costo_es_real define que "
          "un costo solo es válido si es mayor que cero y menor que el precio; si no lo es, costo_unitario lo estima con "
          "la mediana de la razón costo/precio de la categoría. Con esta regla se calculan el margen y el valor del "
          "inventario de los indicadores, sin modificar el costo guardado en el catálogo."),
    ("fig", ["o3_02b_codigo_costos"], "Regla única del costo faltante", codigo("o3_02b_codigo_costos")),

    ("h", "Paso 3. Corregimos las etiquetas de los segmentos"),
    ("p", "En la primera corrida con datos reales, K-Means le asignaba el mismo nombre a dos grupos distintos (por "
          "ejemplo, dos grupos de «Campeones»). Lo corregimos ordenando los grupos por un puntaje RFM compuesto y "
          "asignando a cada uno un nombre distinto según el número de grupos (Figura {f})."),
    ("fig", ["o3_03a_codigo_etiquetas_rfm"], "Asignación de un nombre único a cada segmento",
     codigo("o3_03a_codigo_etiquetas_rfm")),

    ("h", "Paso 4. Reentrenamos los modelos desde la aplicación"),
    ("p", "La página Datos permite ejecutar el pipeline de modelos (Figura {f}). La última corrida, hecha con los umbrales "
          "anteriores, había dejado 0 reglas de asociación."),
    ("fig", ["o3_04a_app_datos_antes"], "Página Datos antes de reentrenar los modelos", APP),
    ("p", "Al pulsar «Ejecutar pipeline» con la opción «Forzar reentrenamiento», el pipeline se completó en 3,07 "
          "segundos y registró una nueva corrida (Figura {f}). Como no había ventas nuevas, la diferencia en los "
          "resultados se debe solo a la calibración."),
    ("fig", ["o3_04b_app_datos_despues"], "Página Datos después de reentrenar los modelos con la nueva calibración", APP),
    ("p", "La Figura {f} muestra las métricas que quedaron registradas en la tabla etl_runs. El modelo XGBoost de la "
          "plataforma pronostica las unidades diarias de cada producto para planear el inventario; obtuvo un MAE de 0,52 "
          "unidades y un R² de 0,57, frente a 0,60 y 0,25 de la línea base que repite las ventas de la semana anterior. A "
          "diferencia del pronóstico del total de pedidos del objetivo 2, aquí XGBoost sí supera a su línea base, porque "
          "aprovecha las diferencias entre productos. Apriori encontró 32 reglas, las mismas del objetivo 2, y K-Means "
          "eligió 4 grupos con una silueta de 0,54 sobre los 123 clientes identificados."),
    ("fig", ["o3_04c_terminal_etl_runs"], "Métricas de la corrida registradas en la tabla etl_runs",
     "Consulta a la base de la corrida de evidencias. Elaboración propia."),
    ("p", "La Tabla {t} resume el efecto de los ajustes sobre la plataforma."),
    ("tabla", "Resultados de la plataforma antes y después de la calibración",
     ["Componente", "Antes (configuración para datos sintéticos)", "Después (calibrada con el caso real)"],
     [["Venta cruzada (Apriori)", "0 reglas con soporte mínimo de 2 %", "32 reglas con soporte mínimo de 0,5 %"],
      ["Segmentos (K-Means)", "Nombres repetidos: dos grupos de Campeones y dos de Ocasionales",
       "Un nombre por grupo: Leales (38), En riesgo (70), Campeones (7) y Ocasionales (8)"],
      ["Margen e inventario", "Costo cero o igual al precio tratado como real",
       "Costo faltante estimado con la mediana de la categoría"],
      ["Clientes", "Todos aparecían como «Cliente Red Rooster»", "Código anónimo C001 a C126, también en la búsqueda"],
      ["Asesor", "Solo validaba descuentos y datos citados", "También descarta acciones que citan cifras inexistentes"]],
     "Elaboración propia a partir de las corridas de la plataforma sobre la base real.",
     [2160, 3600, 3600]),

    ("h", "Paso 5. Presentamos los indicadores en el tablero de inicio"),
    ("p", "El tablero de inicio muestra los indicadores de los últimos 30 días (Figura {f}): $16.850.900 en ventas en 298 "
          "pedidos, un ticket promedio de $56.547 y un margen de 61,16 %, ya calculado con la regla del costo faltante, "
          "además de la serie diaria de ventas y los ingresos por categoría."),
    ("fig", ["o3_05a_app_inicio_kpis"], "Tablero de inicio con los indicadores de los últimos 30 días", APP),

    ("h", "Paso 6. Integramos los modelos en la página de analítica"),
    ("p", "La página Analítica reúne los tres modelos. En la pestaña Demanda se elige el horizonte (7 o 30 días) y el "
          "producto, y se ven el pronóstico y las métricas de validación (Figura {f})."),
    ("fig", ["o3_06a_app_analitica_demanda"], "Analítica: pronóstico de demanda", APP),
    ("p", "En la pestaña Venta cruzada aparecen las 32 reglas ordenadas por lift, con su soporte, su confianza y los "
          "umbrales con que se calcularon (Figura {f})."),
    ("fig", ["o3_06b_app_analitica_venta_cruzada"], "Analítica: reglas de venta cruzada", APP),
    ("p", "En la pestaña Segmentos se ven la distribución de los clientes y un gráfico de dispersión RFM. Al pasar el "
          "cursor sobre un punto aparece el código anónimo del cliente, por ejemplo C007, del segmento Campeones, con un "
          "gasto de $467.800 (Figura {f}); en ningún momento se muestran nombres ni teléfonos."),
    ("fig", ["o3_06c_app_analitica_segmentos"], "Analítica: segmentos de clientes y detalle de un punto del gráfico RFM",
     APP),

    ("h", "Paso 7. Mantuvimos la privacidad en la consulta de clientes"),
    ("p", "La página Clientes muestra a cada cliente por su código anónimo y permite buscarlo por ese código (Figura {f}). "
          "Así, el dueño puede ubicar a un cliente de un segmento, por ejemplo para una campaña, sin que la aplicación "
          "exponga datos personales."),
    ("fig", ["o3_07a_app_clientes_busqueda"], "Búsqueda de un cliente por su código anónimo", APP),

    ("h", "Paso 8. Conectamos el asesor generativo con reglas de control"),
    ("p", "El asesor convierte los resultados en recomendaciones operativas. A Google Gemini le envía solo cifras "
          "agregadas (indicadores, demanda por producto, reglas y resumen de segmentos), nunca datos de clientes "
          "individuales, y valida la respuesta antes de mostrarla (Figura {f}). Cada acción debe citar datos, y se "
          "descarta si propone un descuento mayor al 30 % o si cita una cifra que no existe en el contexto que recibió "
          "el modelo. Si el modelo falla o no deja ninguna acción válida, el asesor pasa a un modo simulado basado en "
          "reglas y lo advierte."),
    ("fig", ["o3_08a_codigo_guardrails"], "Reglas de control del asesor y verificación de las cifras citadas",
     codigo("o3_08a_codigo_guardrails")),
] + ([
    ("p", "La Figura {f} muestra una consulta real al asesor: le preguntamos qué combos recomienda para aumentar el ticket "
          "y qué clientes debe reactivar, y respondió con un plan de acciones que cita las cifras del contexto."),
    ("fig", [ASESOR], "Consulta real al asesor generativo", APP),
] if HAY_ASESOR else []) + [

    ("h", "Paso 9. Expusimos los resultados en una API documentada"),
    ("p", "Todos los resultados están disponibles en una API REST documentada con Swagger y protegida con JWT "
          "(Figura {f}). Por ejemplo, GET /api/v1/analytics/segments devuelve el resumen de los segmentos y cada cliente "
          "con su código anónimo."),
    ("fig", ["o3_09a_swagger_analytics"], "Documentación de la API con la consulta de segmentos",
     "Captura de la documentación interactiva de la API en ejecución. Se ocultó el comando curl, que incluye el token de "
     "acceso. Elaboración propia."),

    ("h", "Paso 10. Verificamos la plataforma con pruebas automáticas"),
    ("p", "La suite completa de la plataforma suma 499 pruebas automáticas, todas en verde (Figura {f}). Incluye las del "
          "ETL, las del paquete de análisis y las nuevas pruebas de la calibración: los umbrales de Apriori, las "
          "etiquetas únicas de los segmentos, la regla del costo faltante, la búsqueda por código y la verificación de "
          "cifras del asesor."),
    ("fig", ["o3_10a_terminal_pytest"], "Suite completa de pruebas automáticas de la plataforma",
     "Captura de la ejecución real de pytest. Elaboración propia."),

    ("h", "Resultado del objetivo 3"),
    ("p", "Con esta integración cumplimos el objetivo específico 3. La aplicación web traduce las salidas técnicas en "
          "tableros de control (los indicadores del inicio y la analítica de demanda, venta cruzada y segmentos) y en "
          "recomendaciones operativas del asesor, con reglas de control y sin exponer datos personales. Los ajustes que "
          "propuso el análisis del objetivo 2 quedaron incorporados en la plataforma y verificados por 499 pruebas "
          "automáticas."),
]

ANALISIS = [
    "La caída de ventas es sobre todo operativa. Los pedidos por día abierto bajaron 20,3 % entre el periodo base y el "
    "de caída, y la diferencia es estadísticamente significativa. Pero la mitad de esa caída se concentra en 9 días casi "
    "sin pedidos, casi todos lunes y sábados, y una cuarta parte en la suspensión de los domicilios durante 56 días; en "
    "los días normales la demanda solo bajó cerca de 5 %, y el ticket promedio no cayó. Más que bajar precios o hacer "
    "publicidad general, el restaurante debe asegurar una operación normal los lunes y sábados y sostener el servicio "
    "de domicilios.",
    "Las acciones tienen un valor estimable. Como aproximación, con unos 26 días abiertos al mes y el ticket promedio "
    "del periodo de caída ($49.504), evitar los días casi sin pedidos representaría 1,7 pedidos más por día abierto, "
    "cerca de $2,2 millones al mes, y recuperar los domicilios otros 0,8 pedidos por día, cerca de $0,8 millones al mes "
    "con su ticket histórico ($37.508). Son estimaciones gruesas, pero sirven para priorizar.",
    "Con poca historia, lo simple le gana a lo complejo. Para el total de pedidos, el promedio de los últimos 24 días "
    "abiertos superó a XGBoost en los dos horizontes, y ningún modelo logró un R² positivo. La recomendación honesta es "
    "esperar un error de unos ±3,8 pedidos por día y planear con el promedio reciente. En cambio, para las unidades por "
    "producto que pronostica la plataforma, XGBoost sí supera a su línea base (R² de 0,57 frente a 0,25). Como la "
    "competencia de modelos se repite con cada actualización de datos, la elección puede cambiar cuando haya más "
    "historia.",
    "Los datos sintéticos no reemplazan a los reales. Con los umbrales pensados para datos sintéticos, Apriori no "
    "encontró ninguna regla, y el catálogo real trajo problemas que los datos sintéticos no tenían: un costo igual al "
    "precio, un precio de lista diez veces mayor que el cobrado y costos en cero. Calibrar los umbrales y corregir el "
    "catálogo con reglas explícitas fue tan importante como elegir el algoritmo.",
    "La venta cruzada y la fidelización ofrecen oportunidades concretas. El 81,4 % de los pedidos con platos sale sin "
    "bebida, aunque las bebidas naturales tienen márgenes de 77 % a 87 %, y los clientes ya arman por su cuenta combos "
    "como Churrasco con Limonada. Además, los Campeones y los Leales, el 22,3 % de los clientes de domicilio, concentran "
    "el 44,2 % del dinero, y 16 clientes de alto gasto están en riesgo, así que una campaña de reactivación debería "
    "empezar por ellos.",
]

CONCLUSIONES = [
    None,  # la primera (ETL) se conserva
    "El análisis exploratorio y las pruebas inferenciales respondieron la pregunta del negocio: la caída de ventas de "
    "Red Rooster desde septiembre de 2026 es real y significativa, pero se debe principalmente a días de baja operación "
    "y a la suspensión temporal de los domicilios, no a una pérdida general de clientes ni al precio. Este hallazgo "
    "orienta las acciones hacia la operación.",
    "Los modelos aportan valor cuando se validan con honestidad. Para el total de pedidos, un promedio simple superó a "
    "XGBoost, y así lo reportamos; para las unidades por producto, XGBoost sí agrega valor. Las reglas de asociación y "
    "la segmentación RFM produjeron recomendaciones directas: combos de plato y bebida con márgenes de 53 % a 71 % y una "
    "campaña de reactivación priorizada por segmento.",
    "La plataforma integró los modelos en tableros de control y en un asesor generativo con reglas de control, sin "
    "exponer datos personales. La comparación entre datos sintéticos y reales mostró que los parámetros deben calibrarse "
    "con el contexto de cada negocio, una lección central para una plataforma que pretende servir a distintos "
    "micronegocios.",
    "Quedan pendientes medir el efecto de las acciones cuando el restaurante las aplique y confirmar con el dueño las "
    "causas de los días de baja actividad y de la suspensión de los domicilios, así como los costos y precios del "
    "catálogo que marcamos como sospechosos, porque los datos muestran qué pasó, pero no por qué.",
]

FASES = {
    "2. ": "2. Análisis exploratorio e inferencial. Comparación entre un periodo base (mayo a agosto) y la caída (1 de "
           "septiembre a 12 de noviembre) por mes, día de la semana, hora, canal, método de pago y ticket (Tukey, 1977), "
           "en pedidos por día abierto, sin los martes de descanso ni el último día, que está incompleto; detección de "
           "días anómalos; pruebas de Mann-Whitney, chi-cuadrado y Kruskal-Wallis con intervalos de confianza "
           "bootstrap; y descomposición de la caída en sus factores.",
    "3. ": "3. Predicción de demanda. Competencia entre tres modelos: el promedio de los últimos 24 días abiertos, el "
           "promedio del mismo día de la semana y XGBoost (Chen & Guestrin, 2016), que predice la proporción de cada día "
           "sobre el nivel reciente a partir del calendario y de la semana anterior. La validación es temporal (Hyndman "
           "& Athanasopoulos, 2021): ocho pruebas semanales a 7 días y dos a 30 días, en las que el modelo solo ve el "
           "pasado. Se mide con el error absoluto medio (MAE) y el R².",
    "4. ": "4. Venta cruzada. Reglas de asociación con el algoritmo Apriori (Agrawal & Srikant, 1994), implementado con "
           "MLxtend (Raschka, 2018), con soporte mínimo de 0,5 %, confianza mínima de 15 % y lift mayor que 1, y márgenes "
           "calculados con el precio real cobrado.",
    "6. ": "6. Integración. Calibración de la plataforma Micronegocio con los resultados del análisis y presentación de "
           "los modelos en tableros de control, en un asesor generativo con reglas de control y en una API documentada.",
}

HERRAMIENTAS = ("Python con Pandas (McKinney, 2010), SciPy (Virtanen et al., 2020), scikit-learn (Pedregosa et al., "
                "2011), XGBoost y MLxtend para el análisis, escrito como un paquete de scripts reproducibles; Matplotlib "
                "para las gráficas del análisis; SQLite para la base analítica; FastAPI y React en la plataforma "
                "Micronegocio; Google Gemini para el asesor generativo; pytest para las pruebas automáticas; y "
                "Playwright para las capturas de evidencia.")

# (texto antes de la parte en cursiva, cursiva, resto)
REFS_NUEVAS = [
    ("Cliff, N. (1993). Dominance statistics: Ordinal analyses to answer ordinal questions. ", "Psychological Bulletin, 114",
     "(3), 494–509. https://doi.org/10.1037/0033-2909.114.3.494"),
    ("Cramér, H. (1946). ", "Mathematical methods of statistics", ". Princeton University Press."),
    ("Efron, B., & Tibshirani, R. J. (1993). ", "An introduction to the bootstrap", ". Chapman & Hall."),
    ("Hubert, L., & Arabie, P. (1985). Comparing partitions. ", "Journal of Classification, 2",
     "(1), 193–218. https://doi.org/10.1007/BF01908075"),
    ("Kruskal, W. H., & Wallis, W. A. (1952). Use of ranks in one-criterion variance analysis. ",
     "Journal of the American Statistical Association, 47", "(260), 583–621. https://doi.org/10.1080/01621459.1952.10483441"),
    ("Mann, H. B., & Whitney, D. R. (1947). On a test of whether one of two random variables is stochastically larger "
     "than the other. ", "The Annals of Mathematical Statistics, 18", "(1), 50–60. https://doi.org/10.1214/aoms/1177730491"),
    ("Virtanen, P., Gommers, R., Oliphant, T. E., Haberland, M., Reddy, T., Cournapeau, D., Burovski, E., Peterson, P., "
     "Weckesser, W., Bright, J., van der Walt, S. J., Brett, M., Wilson, J., Millman, K. J., Mayorov, N., Nelson, A. R. J., "
     "Jones, E., Kern, R., Larson, E., … van Mulbregt, P. (2020). SciPy 1.0: Fundamental algorithms for scientific "
     "computing in Python. ", "Nature Methods, 17", "(3), 261–272. https://doi.org/10.1038/s41592-019-0686-2"),
]
REFS_QUITAR = ("Kimball, R.", "Krawczyk, H.")


# ---------------------------------------------------------------- XML
class Imagenes:
    def __init__(self) -> None:
        self.n = 0
        self.rels: list[str] = []
        self.archivos: list[tuple[Path, str]] = []

    def dibujo(self, fid: str, descr: str, mantener: bool) -> str:
        self.n += 1
        rid, nombre = f"rIdO23_{self.n}", f"obj23_{self.n:02d}.png"
        ruta = AQUI / f"{fid}.png"
        self.archivos.append((ruta, nombre))
        self.rels.append(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                         f'relationships/image" Target="media/{nombre}"/>')
        w, h = obj1.tam_png(ruta)
        cx, cy = ANCHO_EMU, round(ANCHO_EMU * h / w)
        if cy > ALTO_MAX:
            cx, cy = round(ALTO_MAX * w / h), ALTO_MAX
        did = 5000 + self.n
        d = escape(descr, {'"': "&quot;"})
        return (
            f'<w:p><w:pPr>{"<w:keepNext/>" if mantener else ""}<w:spacing w:line="240" w:lineRule="auto"/>'
            '<w:ind w:firstLine="0"/><w:jc w:val="center"/></w:pPr>'
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


def nota(texto: str) -> str:
    return ('<w:p><w:pPr><w:spacing w:after="240" w:line="240" w:lineRule="auto"/><w:ind w:firstLine="0"/></w:pPr>'
            f'{run("Nota.", "<w:i/><w:sz w:val=\"20\"/>")}{run(" " + texto, "<w:sz w:val=\"20\"/>")}</w:p>')


def rotulo(tipo: str, num: int, titulo: str) -> str:
    return (f'<w:p><w:pPr><w:keepNext/><w:ind w:firstLine="0"/></w:pPr>{run(f"{tipo} {num}", "<w:b/>")}</w:p>'
            f'<w:p><w:pPr><w:keepNext/><w:ind w:firstLine="0"/></w:pPr>{run(titulo, "<w:i/>")}</w:p>')


def figura(num: int, ids: list[str], titulo: str, texto_nota: str, img: Imagenes) -> str:
    # En figuras de varias imágenes solo la última se ata a la Nota (evita páginas en blanco).
    return (rotulo("Figura", num, titulo)
            + "".join(img.dibujo(i, titulo, mantener=(k == len(ids) - 1)) for k, i in enumerate(ids))
            + nota(texto_nota))


def tabla(num: int, titulo: str, enc: list[str], filas: list[list[str]], texto_nota: str, anchos: list[int]) -> str:
    assert sum(anchos) == 9360 and all(len(f) == len(enc) for f in filas), titulo
    borde = '<w:tcBorders><w:bottom w:val="single" w:sz="8" w:space="0" w:color="000000"/></w:tcBorders>'

    def celda(texto: str, ancho: int, cab: bool) -> str:
        rpr = "<w:b/><w:sz w:val=\"20\"/>" if cab else "<w:sz w:val=\"20\"/>"
        return (f'<w:tc><w:tcPr><w:tcW w:w="{ancho}" w:type="dxa"/>{borde if cab else ""}</w:tcPr>'
                '<w:p><w:pPr><w:pStyle w:val="Sinespaciado"/><w:spacing w:line="240" w:lineRule="auto"/></w:pPr>'
                f'{run(texto, rpr)}</w:p></w:tc>')

    xml = ('<w:tbl><w:tblPr><w:tblW w:w="9360" w:type="dxa"/><w:tblBorders>'
           '<w:top w:val="single" w:sz="8" w:space="0" w:color="000000"/>'
           '<w:bottom w:val="single" w:sz="8" w:space="0" w:color="000000"/></w:tblBorders>'
           '<w:tblLayout w:type="fixed"/><w:tblCellMar><w:top w:w="40" w:type="dxa"/><w:left w:w="80" w:type="dxa"/>'
           '<w:bottom w:w="40" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar>'
           '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1" w:lastColumn="0" w:noHBand="0" '
           'w:noVBand="1"/></w:tblPr><w:tblGrid>' + "".join(f'<w:gridCol w:w="{a}"/>' for a in anchos) + "</w:tblGrid>")
    xml += '<w:tr><w:trPr><w:tblHeader/></w:trPr>' + "".join(celda(t, a, True) for t, a in zip(enc, anchos)) + "</w:tr>"
    for f in filas:
        xml += '<w:tr><w:trPr><w:cantSplit/></w:trPr>' + "".join(celda(t, a, False) for t, a in zip(f, anchos)) + "</w:tr>"
    return rotulo("Tabla", num, titulo) + xml + "</w:tbl>" + nota(texto_nota)


def construir(contenido, img: Imagenes, fig0: int, tab0: int) -> tuple[str, int, int]:
    """Convierte la lista de contenido en XML. Devuelve (xml, última figura, última tabla)."""
    nf, nt = fig0, tab0
    partes: list[str] = []
    pend_f: list[int] = []
    pend_t: list[int] = []
    for el in contenido:
        if el[0] == "h":
            partes.append(titulo3(el[1]))
        elif el[0] == "p":
            if "{f}" in el[1]:
                pend_f.append(len(partes))
            if "{t}" in el[1]:
                pend_t.append(len(partes))
            partes.append(el[1])
        elif el[0] == "fig":
            nf += 1
            for i in pend_f:
                partes[i] = partes[i].replace("{f}", str(nf))
            pend_f = []
            partes.append(figura(nf, el[1], el[2], el[3], img))
        else:
            nt += 1
            for i in pend_t:
                partes[i] = partes[i].replace("{t}", str(nt))
            pend_t = []
            partes.append(tabla(nt, *el[1:]))
    if pend_f or pend_t:
        raise SystemExit("Hay párrafos que citan una figura o tabla que no existe")
    return "".join(p if p.startswith("<w:") else parrafo(p) for p in partes), nf, nt


def referencia(antes: str, cursiva: str, despues: str) -> str:
    return ('<w:p><w:pPr><w:pStyle w:val="Bibliografa"/><w:ind w:left="709" w:hanging="709"/></w:pPr>'
            + run(antes) + run(cursiva, "<w:i/>") + run(despues) + "</w:p>")


def clave_orden(b: str) -> str:
    t = unicodedata.normalize("NFD", obj1.texto_de(b).replace("&amp;", "&"))
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def reemplazar_celda(tbl: str, viejo: str, nuevo: str) -> str:
    assert f">{viejo}<" in tbl, viejo
    return tbl.replace(f">{viejo}<", f">{nuevo}<", 1)


# ---------------------------------------------------------------- armado
def principal() -> None:
    if DESTINO.exists():
        raise SystemExit(f"Ya existe {DESTINO.name}; muévalo o bórrelo antes de regenerar.")
    faltan = [i for el in OBJ2 + OBJ3 if el[0] == "fig" for i in el[1] if not (AQUI / f"{i}.png").exists()]
    if faltan:
        raise SystemExit(f"Faltan evidencias: {faltan}")
    trabajo = Path(tempfile.mkdtemp(prefix="obj23_docx_"))
    with zipfile.ZipFile(ORIGEN) as z:
        z.extractall(trabajo)
    doc_path = trabajo / "word" / "document.xml"
    xml = doc_path.read_text(encoding="utf-8")
    ini, fin = xml.index("<w:body>") + len("<w:body>"), xml.index("</w:body>")
    bs = obj1.bloques(xml[ini:fin])
    if "".join(bs) != xml[ini:fin]:
        raise SystemExit("El cuerpo tiene elementos fuera de párrafos/tablas; no se puede reconstruir sin perderlos")

    es_t1 = lambda b: 'w:val="Ttulo1"' in b  # noqa: E731

    def h1(prefijo: str) -> int:
        return next(i for i, b in enumerate(bs) if es_t1(b) and texto_de(b).startswith(prefijo))

    i_o2, i_o3, i_ar = h1("Desarrollo del objetivo 2"), h1("Desarrollo del objetivo 3"), h1("Análisis de resultados")
    i_con, i_ref = h1("Conclusiones"), h1("Referencias")
    antes = bs[:i_o2]

    # Figuras y tablas existentes antes del objetivo 2 (para continuar la numeración).
    figs = [int(m) for b in antes for m in re.findall(r"^Figura (\d+)$", texto_de(b))]
    tabs = [int(m) for b in antes for m in re.findall(r"^Tabla (\d+)$", texto_de(b))]
    assert figs == list(range(1, len(figs) + 1)) and tabs == list(range(1, len(tabs) + 1)), (figs, tabs)

    asesor_ok = "Terminado" if HAY_ASESOR else "En curso"
    for i, b in enumerate(antes):
        t = texto_de(b)
        if t.startswith("El segundo es un caso real"):
            antes[i] = obj1.reemplazar_texto(
                b, "El segundo es un caso real",
                "El segundo es un caso real: Red Rooster, un restaurante de pollo BBQ ubicado en Suba Fontanar (Bogotá). "
                "El restaurante usa un sistema web propio de pedidos y caja desde el 23 de marzo de 2026. Entre esa fecha "
                "y el 13 de noviembre de 2026 registró 3.042 pedidos, de los cuales 3.017 fueron pagados, con un catálogo "
                "de 44 productos y 121 clientes de domicilio identificables.")
        elif t.startswith("En septiembre de 2026 el restaurante notó"):
            antes[i] = obj1.reemplazar_texto(
                b, "En septiembre de 2026",
                "En septiembre de 2026 el restaurante notó que sus ventas habían bajado. Los datos lo confirman: el "
                "promedio pasó de 16,5 pedidos pagados por día abierto entre mayo y agosto a 13,1 entre el 1 de "
                "septiembre y el 12 de noviembre, una caída del 20 %. Los ingresos pasaron de $20,8 millones en agosto a "
                "$15,8 millones en septiembre (−24 %).")
        elif t.startswith("La fuente son los archivos JSON") and "octubre" in t:
            antes[i] = obj1.reemplazar_texto(
                b, "La fuente son",
                "La fuente son los archivos JSON del sistema de pedidos y caja de Red Rooster, copiados desde su "
                "servidor: BD/pedidos.json, con los pedidos, y BD/productos.json, con el catálogo. La Tabla 1 resume las "
                "tablas que resultan después del ETL, con corte al 13 de noviembre de 2026. Los análisis de los "
                "objetivos 2 y 3 usan el mismo corte.")
        elif t.startswith("Python con Pandas"):
            antes[i] = obj1.reemplazar_texto(b, "Python con Pandas", HERRAMIENTAS)
        elif t.startswith("La Tabla 2 muestra las actividades"):
            antes[i] = obj1.reemplazar_texto(
                b, "La Tabla 2", "El proyecto se desarrolla en las 8 semanas del diplomado. La Tabla 2 muestra las "
                                 "actividades y su estado al 15 de noviembre de 2026."
                if t.startswith("El proyecto") else "La Tabla 2 muestra las actividades y su estado al 15 de noviembre "
                                                    "de 2026.")
        elif "estado al 23 de octubre" in t:
            antes[i] = obj1.reemplazar_texto(b, "estado al 23 de octubre",
                                             t.replace("23 de octubre de 2026", "15 de noviembre de 2026"))
        elif t.startswith("Nota. Las semanas 2 a 5"):
            antes[i] = obj1.reemplazar_texto(
                b, "Las semanas 2 a 5", "")  # se rehace con formato de Nota
            semanas = "2 a 7" if HAY_ASESOR else "2 a 6"
            antes[i] = nota(f"Las semanas {semanas} se adelantaron y quedaron terminadas el 15 de noviembre de 2026.")
        elif b.startswith("<w:tbl>") and ">Asesor generativo<" in b:
            b = reemplazar_celda(b, "En curso", "Terminado")          # semana 6: integración
            b = reemplazar_celda(b, "Pendiente", asesor_ok)           # semana 7: asesor generativo
            b = reemplazar_celda(b, "Pendiente", "En curso")          # semana 8: cierre
            antes[i] = b
        elif "icon la clave" in t:
            # La «i» sobrante quedó en un run propio: <w:r w:rsidR="..."><w:t>i</w:t></w:r>
            sobrante = re.findall(r'<w:r w:rsidR="[0-9A-F]+"><w:t>i</w:t></w:r>', b)
            assert t.count("icon la clave") == 1 and len(sobrante) == 1
            antes[i] = b.replace(sobrante[0], "")
            assert "con la clave" in texto_de(antes[i])
        else:
            for pref, nuevo in FASES.items():
                if t.startswith(pref) and len(t) > 40:
                    antes[i] = obj1.reemplazar_texto(b, pref, nuevo)
    # Comprobaciones de que todo lo esperado se reemplazó.
    textos = [texto_de(b) for b in antes]
    for esperado in ("13 de noviembre de 2026 registró 3.042", "13,1 entre el 1 de septiembre", "SciPy (Virtanen",
                     "estado al 15 de noviembre", "quedaron terminadas el 15 de noviembre", "con la clave privada",
                     "2. Análisis exploratorio e inferencial", "lift mayor que 1, y márgenes", "6. Integración. Calibración"):
        assert any(esperado in t for t in textos), esperado
    assert not any("icon la clave" in t for t in textos)

    img = Imagenes()
    xml_o2, nf, nt = construir(OBJ2, img, len(figs), len(tabs))
    xml_o3, nf, nt = construir(OBJ3, img, nf, nt)
    enc_o2 = obj1.reemplazar_texto(bs[i_o2], "Desarrollo del objetivo 2",
                                   "Desarrollo del objetivo 2: caracterización del comportamiento de ventas, demanda, "
                                   "venta cruzada y segmentación")
    enc_o3 = obj1.reemplazar_texto(bs[i_o3], "Desarrollo del objetivo 3",
                                   "Desarrollo del objetivo 3: integración en la aplicación web")

    # Análisis de resultados y conclusiones: se conservan los estilos del primer párrafo de cada sección.
    plantilla_ar = bs[i_ar + 1]
    ar = "".join(obj1.reemplazar_texto(plantilla_ar, texto_de(plantilla_ar)[:20], t) for t in ANALISIS)
    viejas_con = bs[i_con + 1:i_ref]
    assert len(viejas_con) == len(CONCLUSIONES), len(viejas_con)
    con = "".join(v if n is None else obj1.reemplazar_texto(v, texto_de(v)[:20], n)
                  for v, n in zip(viejas_con, CONCLUSIONES))

    # Referencias: se quitan las que ya no se citan, se agregan las nuevas y se ordenan alfabéticamente.
    refs = [b for b in bs[i_ref + 1:-1] if 'w:val="Bibliografa"' in b]
    resto = [b for b in bs[i_ref + 1:-1] if 'w:val="Bibliografa"' not in b]
    assert all(not texto_de(b).strip() for b in resto), "Hay contenido no bibliográfico tras las referencias"
    quitadas = [b for b in refs if texto_de(b).startswith(REFS_QUITAR)]
    assert len(quitadas) == 2, len(quitadas)
    refs = [b for b in refs if b not in quitadas] + [referencia(*r) for r in REFS_NUEVAS]
    refs.sort(key=clave_orden)

    cuerpo = ("".join(antes) + enc_o2 + xml_o2 + enc_o3 + xml_o3 + bs[i_ar] + ar + bs[i_con] + con + bs[i_ref]
              + "".join(refs) + bs[-1])
    xml = xml[:ini] + cuerpo + xml[fin:]
    doc_path.write_text(xml, encoding="utf-8")

    media = trabajo / "word" / "media"
    media.mkdir(exist_ok=True)
    for ruta, nombre in img.archivos:
        shutil.copyfile(ruta, media / nombre)
    rels = trabajo / "word" / "_rels" / "document.xml.rels"
    r = rels.read_text(encoding="utf-8")
    assert "rIdO23_" not in r
    rels.write_text(r.replace("</Relationships>", "".join(img.rels) + "</Relationships>"), encoding="utf-8")
    assert 'Extension="png"' in (trabajo / "[Content_Types].xml").read_text(encoding="utf-8")

    with zipfile.ZipFile(DESTINO, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(trabajo.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(trabajo).as_posix())
    shutil.rmtree(trabajo)
    print(f"Figuras: {len(figs) + 1} a {nf}; tablas: {len(tabs) + 1} a {nt}; imágenes nuevas: {img.n}")
    print(f"Asesor incluido: {'sí' if HAY_ASESOR else 'NO (falta la captura con Gemini)'}")
    print(f"Escrito: {DESTINO}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    principal()
