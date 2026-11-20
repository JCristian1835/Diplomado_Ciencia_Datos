"""Paso 1 - Perfil de ventas (análisis exploratorio descriptivo).

Ejecutar desde backend/:  venv\\Scripts\\python -m analisis.a01_perfil_ventas
"""
from matplotlib.patches import Patch

from analisis.comun import (COLOR_BASE, COLOR_CAIDA, COLOR_NEUTRO, DIAS, ETIQUETA_PERIODO, MESES,
                            Reporte, cargar, dias_comparables, fecha_corta, formato_es,
                            n, nueva_figura, pct, pesos, subtitulo, tabla, titulo)

# Franjas por hora de creación del pedido (hora local de Bogotá).
FRANJAS = [("Almuerzo (antes de 15 h)", 0, 15), ("Tarde (15 h a 17:59)", 15, 18),
           ("Noche (desde las 18 h)", 18, 24)]


def describir(serie):
    """Estadísticos descriptivos de una serie (desviación muestral)."""
    return {"dias": int(serie.count()), "media": serie.mean(), "mediana": serie.median(),
            "desviacion": serie.std(ddof=1), "q1": serie.quantile(0.25),
            "q3": serie.quantile(0.75), "minimo": serie.min(), "maximo": serie.max()}


def resumen_general(d, rep):
    v = d.ventas
    comparables = dias_comparables(d.diario)
    rep.datos["resumen"] = {
        "pedidos_pagados": len(v), "pedidos_no_pagados": d.cancelados,
        "ingresos": v["total_amount"].sum(), "primer_dia": v["fecha"].min(),
        "ultimo_dia": v["fecha"].max(), "dias_abiertos_comparables": len(comparables),
        "pedidos_13_nov_excluidos": int((v["periodo"] == "incompleto").sum()),
        "pedidos_en_martes": int((~v["abierto"]).sum())}
    s = rep.datos["resumen"]
    subtitulo("Resumen general")
    print(f"Periodo de datos: {fecha_corta(s['primer_dia'])} a {fecha_corta(s['ultimo_dia'])}")
    print(f"Pedidos pagados: {n(s['pedidos_pagados'])}  (no pagados, excluidos: {n(s['pedidos_no_pagados'])})")
    print(f"Ingresos de pedidos pagados: {pesos(s['ingresos'])}")
    print(f"Excluidos de las comparaciones: {s['pedidos_13_nov_excluidos']} pedidos del 13-nov (día incompleto)")
    print(f"Pedidos registrados en martes (día de descanso): {s['pedidos_en_martes']}")


def por_mes(d, rep):
    v = d.ventas[d.ventas["periodo"] != "incompleto"]
    filas, salida = [], []
    for mes, g in v.groupby(v["fecha"].dt.month):
        dias_abiertos = int(d.diario[(d.diario["fecha"].dt.month == mes) & d.diario["abierto"]
                                     & (d.diario["periodo"] != "incompleto")].shape[0])
        pedidos_abiertos = int(g["abierto"].sum())
        periodo = ETIQUETA_PERIODO[g["periodo"].iloc[0]]
        fila = {"mes": MESES[mes], "periodo": periodo, "pedidos": len(g),
                "ingresos": g["total_amount"].sum(), "ticket": g["total_amount"].mean(),
                "dias_abiertos": dias_abiertos, "pedidos_por_dia_abierto": pedidos_abiertos / dias_abiertos}
        salida.append(fila)
        filas.append([fila["mes"], periodo, n(fila["pedidos"]), pesos(fila["ingresos"]),
                      pesos(fila["ticket"]), fila["dias_abiertos"], n(fila["pedidos_por_dia_abierto"], 1)])
    rep.datos["por_mes"] = salida
    subtitulo("Pedidos, ingresos y ticket por mes (noviembre: 1 al 12)")
    tabla(["Mes", "Periodo", "Pedidos", "Ingresos", "Ticket prom.", "Días abiertos", "Pedidos/día ab."], filas)
    return salida


def por_dia_semana(d, rep):
    v = dias_comparables(d.diario)
    pv = d.ventas[d.ventas["fecha"].isin(v["fecha"])]
    filas, salida = [], []
    for dia in [0, 2, 3, 4, 5, 6]:
        g = pv[pv["dia_semana"] == dia]
        dias = v[v["dia_semana"] == dia]
        por_periodo = {p: dias[dias["periodo"] == p]["pedidos"].mean() for p in ("base", "caida")}
        fila = {"dia": DIAS[dia], "pedidos": len(g), "ingresos": g["total_amount"].sum(),
                "ticket": g["total_amount"].mean(), "pedidos_por_dia_base": por_periodo["base"],
                "pedidos_por_dia_caida": por_periodo["caida"]}
        salida.append(fila)
        filas.append([fila["dia"], n(fila["pedidos"]), pesos(fila["ingresos"]), pesos(fila["ticket"]),
                      n(por_periodo["base"], 1), n(por_periodo["caida"], 1)])
    rep.datos["por_dia_semana"] = salida
    subtitulo("Por día de la semana (periodos base + caída; el martes no abre)")
    tabla(["Día", "Pedidos", "Ingresos", "Ticket prom.", "Ped./día base", "Ped./día caída"], filas)


def por_franja(d, rep):
    v = d.ventas[d.ventas["periodo"].isin(["base", "caida"])]
    subtitulo("Pedidos por hora (base + caída) - sirve para validar las franjas")
    horas = v.groupby("hora").size()
    tabla(["Hora", "Pedidos", "% del total"], [[f"{h:02d}:00", n(c), pct(c / len(v))] for h, c in horas.items()])
    hora_pico = int(horas.idxmax())
    print(f"Hora pico: {hora_pico:02d}:00. Hay un segundo repunte entre las 19 y las 20 h; "
          "las franjas fijadas (almuerzo, tarde, noche) separan bien esos dos picos, por eso no se ajustan.")
    filas, salida = [], []
    for nombre, desde, hasta in FRANJAS:
        g = v[(v["hora"] >= desde) & (v["hora"] < hasta)]
        base, caida = (g["periodo"] == "base").sum(), (g["periodo"] == "caida").sum()
        tot_base, tot_caida = (v["periodo"] == "base").sum(), (v["periodo"] == "caida").sum()
        fila = {"franja": nombre, "pedidos": len(g), "pct": len(g) / len(v),
                "pct_base": base / tot_base, "pct_caida": caida / tot_caida,
                "ticket": g["total_amount"].mean()}
        salida.append(fila)
        filas.append([nombre, n(len(g)), pct(fila["pct"]), pct(fila["pct_base"]),
                      pct(fila["pct_caida"]), pesos(fila["ticket"])])
    rep.datos["por_franja"] = {"franjas": salida, "hora_pico": hora_pico,
                               "pedidos_por_hora": {int(h): int(c) for h, c in horas.items()}}
    subtitulo("Por franja horaria")
    tabla(["Franja", "Pedidos", "% total", "% base", "% caída", "Ticket prom."], filas)


def por_categoria(d, rep, columna, clave, nombre_tabla):
    """Pedidos, % por periodo, ingresos y ticket según una columna categórica (canal, método de pago)."""
    v = d.ventas[d.ventas["periodo"].isin(["base", "caida"])]
    tot_base, tot_caida = (v["periodo"] == "base").sum(), (v["periodo"] == "caida").sum()
    filas, salida = [], []
    for valor, g in sorted(v.groupby(columna), key=lambda t: -len(t[1])):
        base, caida = (g["periodo"] == "base").sum(), (g["periodo"] == "caida").sum()
        fila = {"categoria": valor, "pedidos": len(g), "pct": len(g) / len(v), "pedidos_base": base,
                "pedidos_caida": caida, "pct_base": base / tot_base, "pct_caida": caida / tot_caida,
                "ingresos": g["total_amount"].sum(), "ticket": g["total_amount"].mean()}
        salida.append(fila)
        filas.append([valor, n(len(g)), n(base), pct(fila["pct_base"]), n(caida), pct(fila["pct_caida"]),
                      pesos(fila["ingresos"]), pesos(fila["ticket"])])
    rep.datos[clave] = salida
    subtitulo(nombre_tabla)
    tabla(["Categoría", "Pedidos", "Base", "% base", "Caída", "% caída", "Ingresos", "Ticket prom."], filas)


def descriptivos_periodos(d, rep):
    c = dias_comparables(d.diario)
    desc = {p: describir(c[c["periodo"] == p]["pedidos"]) for p in ("base", "caida")}
    rep.datos["descriptivos_pedidos_por_dia_abierto"] = desc
    subtitulo("Pedidos por día abierto: estadísticos descriptivos")
    nombres = [("Días abiertos", "dias", 0), ("Media", "media", 2), ("Mediana", "mediana", 1),
               ("Desv. estándar", "desviacion", 2), ("Cuartil 1", "q1", 1), ("Cuartil 3", "q3", 1),
               ("Mínimo", "minimo", 0), ("Máximo", "maximo", 0)]
    tabla(["Estadístico", "Base (may-ago)", "Caída (sep-12 nov)"],
          [[t, n(desc["base"][k], dec), n(desc["caida"][k], dec)] for t, k, dec in nombres])
    caida_media = desc["caida"]["media"] / desc["base"]["media"] - 1
    rep.datos["variacion_media"] = caida_media
    print(f"\nVariación de la media: {n(caida_media * 100, 1)} % "
          f"({n(desc['base']['media'], 2)} -> {n(desc['caida']['media'], 2)} pedidos por día abierto)")


def grafica_pedidos_mes(rep, meses):
    fig, ax = nueva_figura()
    colores = {"Arranque": COLOR_NEUTRO, "Base": COLOR_BASE, "Caída": COLOR_CAIDA}
    barras = ax.bar([m["mes"].capitalize() for m in meses], [m["pedidos_por_dia_abierto"] for m in meses],
                    color=[colores[m["periodo"]] for m in meses], width=0.62)
    for barra, m in zip(barras, meses):
        ax.text(barra.get_x() + barra.get_width() / 2, barra.get_height() + 0.3,
                n(m["pedidos_por_dia_abierto"], 1), ha="center", fontsize=11)
    ax.set_title("Pedidos pagados por día abierto, por mes (noviembre: 1 al 12)")
    ax.set_ylabel("Pedidos por día abierto")
    ax.set_ylim(0, max(m["pedidos_por_dia_abierto"] for m in meses) * 1.15)
    ax.grid(axis="x", visible=False)
    formato_es(ax.yaxis)
    ax.legend(handles=[Patch(color=c, label=e) for e, c in colores.items()], frameon=False, loc="upper right")
    fig.text(0.01, 0.01, "Día abierto = día que no es martes. Fuente: pedidos pagados de Red Rooster.",
             fontsize=9, color=COLOR_NEUTRO)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    rep.guardar_figura(fig, "pedidos_por_dia_abierto_mes")


def main():
    d = cargar()
    with Reporte("a01_perfil_ventas") as rep:
        titulo("PASO 1 - PERFIL DE VENTAS (EDA descriptivo)")
        resumen_general(d, rep)
        meses = por_mes(d, rep)
        por_dia_semana(d, rep)
        por_franja(d, rep)
        por_categoria(d, rep, "canal", "por_canal", "Por canal (base + caída)")
        por_categoria(d, rep, "payment_method", "por_metodo_pago", "Por método de pago (base + caída)")
        descriptivos_periodos(d, rep)
        grafica_pedidos_mes(rep, meses)


if __name__ == "__main__":
    main()
