"""Ejecuta los siete pasos del análisis del Objetivo 2 en orden.

Desde backend/:  venv\\Scripts\\python -m analisis.correr_todo
"""
from analisis import (a01_perfil_ventas, a02_estacionalidad_anomalias, a03_inferencia, a04_descomposicion_caida,
                      a05_demanda, a06_venta_cruzada, a07_segmentacion)

PASOS = [a01_perfil_ventas, a02_estacionalidad_anomalias, a03_inferencia, a04_descomposicion_caida,
         a05_demanda, a06_venta_cruzada, a07_segmentacion]


def main():
    for paso in PASOS:
        paso.main()


if __name__ == "__main__":
    main()
