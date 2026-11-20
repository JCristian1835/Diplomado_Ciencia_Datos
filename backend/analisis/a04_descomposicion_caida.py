"""Paso 4 - ¿De dónde viene la caída? Descomposición de la diferencia de pedidos por día abierto.

Diferencia total = media base - media caída (pedidos por día abierto) = (a) + (b) + (c):
  (a) domicilios perdidos: menos pedidos de domicilio por día abierto.
  (b) días casi sin pedidos: pedidos que no se vendieron en esos días respecto a un día normal
      de su mismo periodo (solo pedidos que no son de domicilio, para no contar dos veces).
  (c) demanda en días normales: cambio del nivel de pedidos que no son de domicilio en los días
      normales (los que no son casi vacíos).
La suma es exacta: los tres porcentajes suman 100 % de la diferencia.

Ejecutar desde backend/:  venv\\Scripts\\python -m analisis.a04_descomposicion_caida
"""
from analisis.comun import (COLOR_BASE, COLOR_CAIDA, COLOR_NEUTRO, UMBRAL_CASI_SIN_PEDIDOS, Reporte, cargar,
                            dias_comparables, formato_es, n, nueva_figura, pct, subtitulo, tabla, titulo,
                            valla_tukey)


def resumen_periodo(g, anomalo):
    """Medias por día abierto de un periodo, separando domicilios, días normales y días anómalos."""
    otros = g["pedidos"] - g["domicilios"]
    normales = otros[~anomalo]
    anomalos = otros[anomalo]
    perdida = len(anomalos) / len(g) * (normales.mean() - anomalos.mean()) if len(anomalos) else 0.0
    return {"dias": len(g), "dias_anomalos": int(anomalo.sum()), "pedidos_por_dia": g["pedidos"].mean(),
            "domicilios_por_dia": g["domicilios"].mean(), "nivel_dias_normales": normales.mean(),
            "perdida_dias_anomalos": perdida}


def descomponer(c, mascara_anomala):
    """Devuelve la descomposición (a, b, c) de la caída para una definición de día anómalo."""
    base = resumen_periodo(c[c["periodo"] == "base"], mascara_anomala[c["periodo"] == "base"])
    caida = resumen_periodo(c[c["periodo"] == "caida"], mascara_anomala[c["periodo"] == "caida"])
    total = base["pedidos_por_dia"] - caida["pedidos_por_dia"]
    partes = {"domicilios": base["domicilios_por_dia"] - caida["domicilios_por_dia"],
              "dias_casi_sin_pedidos": caida["perdida_dias_anomalos"] - base["perdida_dias_anomalos"],
              "demanda_dias_normales": base["nivel_dias_normales"] - caida["nivel_dias_normales"]}
    return {"base": base, "caida": caida, "caida_total": total, "partes": partes,
            "porcentajes": {k: v / total for k, v in partes.items()},
            "cuadre": abs(sum(partes.values()) - total) < 1e-9}


def mostrar_principal(r):
    subtitulo(f"Descomposición de la caída (día casi sin pedidos = {UMBRAL_CASI_SIN_PEDIDOS} pedidos o menos)")
    print(f"Pedidos por día abierto: base {n(r['base']['pedidos_por_dia'], 2)} -> caída {n(r['caida']['pedidos_por_dia'], 2)}"
          f"  (diferencia {n(r['caida_total'], 2)})")
    print(f"Días casi sin pedidos: base {r['base']['dias_anomalos']} de {r['base']['dias']}, "
          f"caída {r['caida']['dias_anomalos']} de {r['caida']['dias']}")
    nombres = {"domicilios": "(a) Domicilios perdidos", "dias_casi_sin_pedidos": "(b) Días casi sin pedidos",
               "demanda_dias_normales": "(c) Demanda en días normales"}
    filas = [[nombres[k], n(v, 2), pct(r["porcentajes"][k])] for k, v in r["partes"].items()]
    filas.append(["Total de la caída", n(r["caida_total"], 2), pct(sum(r["porcentajes"].values()))])
    print()
    tabla(["Componente", "Pedidos/día ab.", "% de la caída"], filas)
    print(f"\nLa suma de los tres componentes cuadra con la caída total: {'sí' if r['cuadre'] else 'NO'}")


def sensibilidad(c, rep):
    """Repite la descomposición con otras definiciones de día anómalo."""
    _, _, _, valla_global = valla_tukey(c["pedidos"])
    _, _, _, valla_base = valla_tukey(c[c["periodo"] == "base"]["pedidos"])
    definiciones = {f"<= {UMBRAL_CASI_SIN_PEDIDOS} pedidos (principal)": c["pedidos"] <= UMBRAL_CASI_SIN_PEDIDOS,
                    f"Tukey base + caída (valla {n(valla_global, 1)})": c["pedidos"] <= valla_global,
                    f"Tukey solo base (valla {n(valla_base, 1)})": c["pedidos"] <= valla_base}
    filas, salida = [], {}
    for nombre, mascara in definiciones.items():
        r = descomponer(c, mascara)
        salida[nombre] = {"dias_anomalos": int(mascara.sum()), **r["porcentajes"]}
        p = r["porcentajes"]
        filas.append([nombre, int(mascara.sum()), pct(p["domicilios"]), pct(p["dias_casi_sin_pedidos"]),
                      pct(p["demanda_dias_normales"])])
    subtitulo("Sensibilidad a la definición de día anómalo")
    tabla(["Definición", "Días", "(a) Domicilios", "(b) Días vacíos", "(c) Demanda"], filas)
    rep.datos["sensibilidad"] = salida


def grafica_cascada(r, rep):
    base, caida, partes = r["base"]["pedidos_por_dia"], r["caida"]["pedidos_por_dia"], r["partes"]
    etiquetas = ["Base\n(may-ago)", "Domicilios\nperdidos", "Días casi\nsin pedidos", "Demanda en\ndías normales",
                 "Caída\n(sep-12 nov)"]
    fig, ax = nueva_figura()
    acumulado = base
    ax.bar(0, base, color=COLOR_BASE, width=0.6)
    ax.text(0, base + 0.3, n(base, 2), ha="center", fontsize=11)
    for i, clave in enumerate(["domicilios", "dias_casi_sin_pedidos", "demanda_dias_normales"], start=1):
        valor = partes[clave]
        ax.bar(i, -valor, bottom=acumulado, color=COLOR_NEUTRO, width=0.6)
        ax.text(i, acumulado + 0.3, f"-{n(valor, 2)}\n({pct(r['porcentajes'][clave], 0)})", ha="center", fontsize=11)
        ax.plot([i - 0.7, i - 0.3], [acumulado, acumulado], color=COLOR_NEUTRO, linewidth=1)
        acumulado -= valor
    ax.plot([3.3, 3.7], [acumulado, acumulado], color=COLOR_NEUTRO, linewidth=1)
    ax.bar(4, caida, color=COLOR_CAIDA, width=0.6)
    ax.text(4, caida + 0.3, n(caida, 2), ha="center", fontsize=11)
    ax.set_xticks(range(5), etiquetas)
    ax.set_ylabel("Pedidos por día abierto")
    ax.set_ylim(0, base * 1.2)
    ax.set_title("Descomposición de la caída de pedidos por día abierto")
    ax.grid(axis="x", visible=False)
    formato_es(ax.yaxis)
    fig.text(0.01, 0.01, f"Día casi sin pedidos = {UMBRAL_CASI_SIN_PEDIDOS} pedidos o menos. "
             "Los tres componentes suman el 100 % de la caída.", fontsize=9, color=COLOR_NEUTRO)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    rep.guardar_figura(fig, "cascada_caida")


def main():
    c = dias_comparables(cargar().diario)
    with Reporte("a04_descomposicion_caida") as rep:
        titulo("PASO 4 - DESCOMPOSICIÓN DE LA CAÍDA")
        r = descomponer(c, c["pedidos"] <= UMBRAL_CASI_SIN_PEDIDOS)
        rep.datos["descomposicion"] = r
        mostrar_principal(r)
        sensibilidad(c, rep)
        grafica_cascada(r, rep)


if __name__ == "__main__":
    main()
