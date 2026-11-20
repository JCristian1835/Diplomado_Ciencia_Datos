"""Paso 2 - Estacionalidad (día de la semana, quincena, festivo) y días anómalos.

Ejecutar desde backend/:  venv\\Scripts\\python -m analisis.a02_estacionalidad_anomalias
"""
import matplotlib.dates as mdates
import numpy as np
from matplotlib.ticker import FuncFormatter

from analisis.comun import (COLOR_BASE, COLOR_CAIDA, COLOR_NEUTRO, COLOR_TEXTO, DIAS, MESES,
                            UMBRAL_CASI_SIN_PEDIDOS, Reporte, cargar, dias_comparables,
                            fecha_corta, formato_es, n, nueva_figura, pct, subtitulo, tabla,
                            titulo, valla_tukey)

ORDEN_DIAS = [0, 2, 3, 4, 5, 6]  # lunes, miércoles ... domingo (el martes no abre)


def con_indice(c):
    """Agrega `indice`: pedidos del día / media de su mismo día de la semana y periodo.

    Así se compara cada día contra lo esperable para su día de la semana y su nivel de
    ventas, y el efecto de quincena o festivo no se confunde con la caída ni con el día.
    """
    c = c.copy()
    c["indice"] = c["pedidos"] / c.groupby(["periodo", "dia_semana"])["pedidos"].transform("mean")
    return c


def efecto_dia_semana(c, rep):
    media_general = c["pedidos"].mean()
    filas, salida = [], []
    for dia in ORDEN_DIAS:
        g = c[c["dia_semana"] == dia]
        base, caida = (g[g["periodo"] == p]["pedidos"].mean() for p in ("base", "caida"))
        fila = {"dia": DIAS[dia], "dias": len(g), "media": g["pedidos"].mean(),
                "indice_vs_media_general": g["pedidos"].mean() / media_general,
                "media_base": base, "media_caida": caida, "variacion": caida / base - 1}
        salida.append(fila)
        filas.append([fila["dia"], fila["dias"], n(fila["media"], 1), n(fila["indice_vs_media_general"], 2),
                      n(base, 1), n(caida, 1), n(fila["variacion"] * 100, 1) + " %"])
    rep.datos["efecto_dia_semana"] = {"media_general": media_general, "dias": salida}
    subtitulo("Efecto del día de la semana (pedidos por día abierto, base + caída)")
    tabla(["Día", "Días", "Media", "Índice", "Media base", "Media caída", "Variación"], filas)
    print("Índice = media del día / media general (1,00 = igual al promedio).")


def efecto_calendario(c, rep, columna, nombre):
    """Compara los días marcados (quincena o festivo) con los demás, usando el índice ajustado."""
    filas, salida = [], {}
    for marcado, etiqueta in ((1, f"Con {nombre}"), (0, f"Sin {nombre}")):
        g = c[c[columna] == marcado]
        salida[etiqueta] = {"dias": len(g), "media_pedidos": g["pedidos"].mean(), "indice": g["indice"].mean()}
        filas.append([etiqueta, len(g), n(g["pedidos"].mean(), 1), n(g["indice"].mean(), 2)])
    diferencia = salida[f"Con {nombre}"]["indice"] / salida[f"Sin {nombre}"]["indice"] - 1
    salida["diferencia_indice"] = diferencia
    rep.datos[f"efecto_{nombre}"] = salida
    subtitulo(f"Efecto de {nombre} (días abiertos, base + caída)")
    tabla(["Grupo", "Días", "Media pedidos", "Índice ajustado"], filas)
    print(f"Diferencia del índice ajustado: {n(diferencia * 100, 1)} %")


def anomalias(c, rep):
    q1, q3, iqr, valla = valla_tukey(c["pedidos"])
    marcados = c[c["pedidos"] <= valla]
    altos = c[c["pedidos"] >= q3 + 1.5 * iqr]
    _, _, _, valla_base = valla_tukey(c[c["periodo"] == "base"]["pedidos"])
    marcados_base = c[c["pedidos"] <= valla_base]
    rep.datos["tukey"] = {
        "q1": q1, "q3": q3, "iqr": iqr, "valla_inferior": valla, "dias_anomalos": marcados["fecha"].tolist(),
        "dias_atipicos_al_alza": altos["fecha"].tolist(), "valla_inferior_solo_base": valla_base,
        "dias_anomalos_solo_base": marcados_base["fecha"].tolist()}
    subtitulo("Días anómalos: regla de Tukey sobre pedidos por día abierto (base + caída)")
    print(f"Q1 = {n(q1, 1)}   Q3 = {n(q3, 1)}   IQR = {n(iqr, 1)}   valla inferior = Q1 - 1,5 x IQR = {n(valla, 2)}")
    print(f"Días por debajo de la valla: {len(marcados)} -> "
          + (", ".join(f"{fecha_corta(f)} (pedidos: {n(p)})" for f, p in zip(marcados["fecha"], marcados["pedidos"])) or "ninguno"))
    print(f"Días atípicos al alza (Q3 + 1,5 x IQR = {n(q3 + 1.5 * iqr, 1)}): {len(altos)}")
    print(f"Si la valla se calcula solo con el periodo base ({n(valla_base, 2)}): {len(marcados_base)} días.")
    print("La regla marca pocos días porque la caída ensancha la dispersión; por eso también se listan "
          f"los días casi sin pedidos (<= {UMBRAL_CASI_SIN_PEDIDOS}).")
    return marcados


def casi_sin_pedidos(c, rep):
    bajos = c[c["pedidos"] <= UMBRAL_CASI_SIN_PEDIDOS].sort_values("fecha")
    minimo_base = c[c["periodo"] == "base"]["pedidos"].min()
    rep.datos["casi_sin_pedidos"] = {
        "umbral": UMBRAL_CASI_SIN_PEDIDOS, "minimo_periodo_base": minimo_base, "dias": len(bajos),
        "detalle": [{"fecha": f, "dia": DIAS[d], "pedidos": p, "festivo": bool(fe), "quincena": bool(q)}
                    for f, d, p, fe, q in zip(bajos["fecha"], bajos["dia_semana"], bajos["pedidos"],
                                              bajos["es_festivo"], bajos["es_quincena"])]}
    subtitulo(f"Días abiertos casi sin pedidos (<= {UMBRAL_CASI_SIN_PEDIDOS}); mínimo del periodo base: {n(minimo_base)}")
    tabla(["Fecha", "Día", "Pedidos", "Festivo", "Quincena"],
          [[fecha_corta(f), DIAS[d], n(p), "sí" if fe else "no", "sí" if q else "no"]
           for f, d, p, fe, q in zip(bajos["fecha"], bajos["dia_semana"], bajos["pedidos"],
                                     bajos["es_festivo"], bajos["es_quincena"])])
    print(f"\n{len(bajos)} de {int((c['periodo'] == 'caida').sum())} días abiertos de la caída; "
          f"{pct((bajos['dia_semana'].isin([0, 5])).mean(), 0)} cayeron en lunes o sábado.")
    return bajos


def domicilios(d, rep):
    fechas = np.sort(d.ventas.loc[d.ventas["canal"] == "domicilio", "fecha"].unique())
    saltos = np.diff(fechas).astype("timedelta64[D]").astype(int)
    i = int(saltos.argmax())
    interrupcion = {"ultimo_antes": fechas[i], "primero_despues": fechas[i + 1], "dias_sin_domicilio": int(saltos[i]) - 1}
    rep.datos["domicilios"] = {"ultimo_domicilio": fechas[-1], "primer_domicilio": fechas[0],
                               "interrupcion_mas_larga": interrupcion,
                               "domicilios_por_mes": d.ventas[d.ventas["canal"] == "domicilio"]
                               .groupby(d.ventas["fecha"].dt.month).size().rename(MESES).to_dict()}
    subtitulo("Servicio de domicilio")
    print(f"Último domicilio registrado: {fecha_corta(fechas[-1])}")
    print(f"Interrupción más larga: último domicilio {fecha_corta(fechas[i])}, siguiente {fecha_corta(fechas[i + 1])} "
          f"({interrupcion['dias_sin_domicilio']} días sin domicilios).")


def grafica_dia_semana(c, rep):
    fig, ax = nueva_figura()
    x = np.arange(len(ORDEN_DIAS))
    medias = {p: [c[(c["periodo"] == p) & (c["dia_semana"] == dia)]["pedidos"].mean() for dia in ORDEN_DIAS]
              for p in ("base", "caida")}
    for desplazamiento, p, color, nombre in ((-0.2, "base", COLOR_BASE, "Base (may-ago)"),
                                             (0.2, "caida", COLOR_CAIDA, "Caída (sep-12 nov)")):
        barras = ax.bar(x + desplazamiento, medias[p], width=0.38, color=color, label=nombre)
        for barra, valor in zip(barras, medias[p]):
            ax.text(barra.get_x() + barra.get_width() / 2, valor + 0.3, n(valor, 1), ha="center", fontsize=10)
    ax.set_xticks(x, [DIAS[dia].capitalize() for dia in ORDEN_DIAS])
    ax.set_title("Pedidos por día abierto según el día de la semana: base vs caída")
    ax.set_ylabel("Pedidos por día abierto (media)")
    ax.set_ylim(0, max(max(v) for v in medias.values()) * 1.15)
    ax.grid(axis="x", visible=False)
    formato_es(ax.yaxis)
    ax.legend(frameon=False, loc="upper right")
    fig.text(0.01, 0.01, "El martes es el día de descanso y no se muestra.", fontsize=9, color=COLOR_NEUTRO)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    rep.guardar_figura(fig, "pedidos_dia_semana_base_vs_caida")


def grafica_serie(d, bajos, tukey, rep):
    serie = d.diario[d.diario["abierto"] & (d.diario["periodo"] != "incompleto")]
    fig, ax = nueva_figura()
    ax.axvspan(serie["fecha"].min(), d.diario[d.diario["periodo"] == "arranque"]["fecha"].max(),
               color=COLOR_NEUTRO, alpha=0.12, label="Arranque (no se compara)")
    ax.plot(serie["fecha"], serie["pedidos"], color=COLOR_NEUTRO, linewidth=1, marker="o", markersize=3,
            label="Pedidos del día abierto")
    ax.plot(serie["fecha"], serie["pedidos"].rolling(7, min_periods=7).mean(), color=COLOR_BASE, linewidth=2.4,
            label="Media móvil de 7 días abiertos")
    ax.scatter(bajos["fecha"], bajos["pedidos"], s=70, facecolor="none", edgecolor=COLOR_CAIDA, linewidth=2,
               zorder=5, label=f"Casi sin pedidos (<= {UMBRAL_CASI_SIN_PEDIDOS})")
    ax.scatter(tukey["fecha"], tukey["pedidos"], s=26, color=COLOR_CAIDA, zorder=6, label="Anómalo por regla de Tukey")
    ax.axvline(d.diario[d.diario["periodo"] == "caida"]["fecha"].min(), color=COLOR_TEXTO, linestyle="--", linewidth=1)
    ax.text(d.diario[d.diario["periodo"] == "caida"]["fecha"].min(), ax.get_ylim()[1] * 0.97, " inicio de la caída (1-sep)",
            fontsize=9, va="top")
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: MESES[mdates.num2date(v).month][:3].capitalize()))
    ax.set_title("Pedidos pagados por día abierto, con días anómalos marcados")
    ax.set_ylabel("Pedidos pagados")
    ax.grid(axis="x", visible=False)
    formato_es(ax.yaxis)
    fig.legend(*ax.get_legend_handles_labels(), frameon=False, loc="lower center", ncol=3)
    fig.tight_layout(rect=(0, 0.1, 1, 1))
    rep.guardar_figura(fig, "serie_diaria_anomalias")


def main():
    d = cargar()
    c = con_indice(dias_comparables(d.diario))
    with Reporte("a02_estacionalidad_anomalias") as rep:
        titulo("PASO 2 - ESTACIONALIDAD Y DÍAS ANÓMALOS")
        efecto_dia_semana(c, rep)
        efecto_calendario(c, rep, "es_quincena", "quincena")
        efecto_calendario(c, rep, "es_festivo", "festivo")
        tukey = anomalias(c, rep)
        bajos = casi_sin_pedidos(c, rep)
        domicilios(d, rep)
        grafica_dia_semana(c, rep)
        grafica_serie(d, bajos, tukey, rep)


if __name__ == "__main__":
    main()
