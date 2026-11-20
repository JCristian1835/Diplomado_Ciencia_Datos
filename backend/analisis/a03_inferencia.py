"""Paso 3 - Pruebas inferenciales: ¿la caída es real o puede ser azar?

Se usan pruebas no paramétricas porque los pedidos por día no son normales (hay días casi
sin pedidos y la dispersión cambia entre periodos). Nivel de significancia: 0,05.

Ejecutar desde backend/:  venv\\Scripts\\python -m analisis.a03_inferencia
"""
import numpy as np
import pandas as pd
from scipy import stats

from analisis.comun import (SEMILLA, UMBRAL_CASI_SIN_PEDIDOS, Reporte, cargar, dias_comparables,
                            fmt_p, n, texto_p, pct, pesos, subtitulo, tabla, titulo)

ALFA = 0.05
REPLICAS = 10_000


def magnitud(delta):
    """Interpretación habitual del delta de Cliff (Romano et al., 2006)."""
    delta = abs(delta)
    if delta < 0.147:
        return "insignificante"
    if delta < 0.33:
        return "pequeño"
    if delta < 0.474:
        return "mediano"
    return "grande"


def concluir(p, diferente, igual):
    return (f"{diferente} (p < 0,05)." if p < ALFA else f"{igual} (p >= 0,05).")


def mann_whitney(a, b):
    """U de Mann-Whitney bilateral y delta de Cliff (positivo si `a` tiende a ser mayor que `b`)."""
    r = stats.mannwhitneyu(a, b, alternative="two-sided")
    delta = 2 * r.statistic / (len(a) * len(b)) - 1
    return {"U": r.statistic, "p": r.pvalue, "delta_cliff": delta, "magnitud": magnitud(delta)}


def bootstrap_diferencia_medias(a, b, rng):
    """IC 95 % percentil de mean(a) - mean(b), remuestreando cada grupo con reemplazo."""
    diferencias = np.array([rng.choice(a, a.size).mean() - rng.choice(b, b.size).mean() for _ in range(REPLICAS)])
    return np.percentile(diferencias, [2.5, 97.5])


def mostrar_mann_whitney(titulo_prueba, nombre_a, nombre_b, a, b, r, conclusion, formato):
    subtitulo(titulo_prueba)
    print(f"{nombre_a}: n = {len(a)}, media = {formato(a.mean())}, mediana = {formato(np.median(a))}")
    print(f"{nombre_b}: n = {len(b)}, media = {formato(b.mean())}, mediana = {formato(np.median(b))}")
    print(f"Estadístico U = {n(r['U'], 1)}   {texto_p(r['p'])}")
    print(f"Tamaño del efecto (delta de Cliff) = {n(r['delta_cliff'], 3)} -> {r['magnitud']}")
    print(f"Conclusión: {conclusion}")


def prueba_pedidos_por_dia(c, rep, rng):
    base = c[c["periodo"] == "base"]["pedidos"].to_numpy()
    caida = c[c["periodo"] == "caida"]["pedidos"].to_numpy()
    r = mann_whitney(base, caida)
    conclusion = concluir(r["p"], "La caída de pedidos por día abierto es estadísticamente significativa",
                          "No se puede descartar que la diferencia sea azar")
    mostrar_mann_whitney("Mann-Whitney: pedidos por día abierto, base vs caída", "Base", "Caída", base, caida,
                         r, conclusion, lambda v: n(v, 2))
    ic = bootstrap_diferencia_medias(base, caida, rng)
    diferencia = base.mean() - caida.mean()
    print(f"Diferencia de medias (base - caída) = {n(diferencia, 2)} pedidos por día abierto")
    print(f"IC 95 % bootstrap ({n(REPLICAS)} réplicas, semilla {SEMILLA}): [{n(ic[0], 2)} ; {n(ic[1], 2)}]")
    print("El intervalo " + ("no incluye el 0: la caída es real." if ic[0] > 0 else "incluye el 0: la caída no es concluyente."))

    normales = c[c["pedidos"] > UMBRAL_CASI_SIN_PEDIDOS]
    base_n = normales[normales["periodo"] == "base"]["pedidos"].to_numpy()
    caida_n = normales[normales["periodo"] == "caida"]["pedidos"].to_numpy()
    r_n = mann_whitney(base_n, caida_n)
    conclusion_n = concluir(r_n["p"], "Aun sin los días casi sin pedidos sigue habiendo diferencia significativa",
                            "Sin los días casi sin pedidos la diferencia deja de ser significativa")
    mostrar_mann_whitney(f"Robustez: sin los días casi sin pedidos (<= {UMBRAL_CASI_SIN_PEDIDOS})", "Base", "Caída",
                         base_n, caida_n, r_n, conclusion_n, lambda v: n(v, 2))
    ic_n = bootstrap_diferencia_medias(base_n, caida_n, rng)
    print(f"Diferencia de medias = {n(base_n.mean() - caida_n.mean(), 2)}   IC 95 % bootstrap: [{n(ic_n[0], 2)} ; {n(ic_n[1], 2)}]")
    rep.datos["pedidos_por_dia_abierto"] = {
        "base_n": len(base), "caida_n": len(caida), "media_base": base.mean(), "media_caida": caida.mean(),
        "mann_whitney": r, "diferencia_medias": diferencia, "ic95_bootstrap": ic.tolist(),
        "replicas": REPLICAS, "semilla": SEMILLA, "conclusion": conclusion,
        "sin_dias_casi_vacios": {"base_n": len(base_n), "caida_n": len(caida_n), "media_base": base_n.mean(),
                                 "media_caida": caida_n.mean(), "mann_whitney": r_n,
                                 "diferencia_medias": base_n.mean() - caida_n.mean(), "ic95_bootstrap": ic_n.tolist(),
                                 "conclusion": conclusion_n}}


def chi_cuadrado(ventas, canales, titulo_prueba, clave, rep):
    v = ventas[ventas["periodo"].isin(["base", "caida"]) & ventas["canal"].isin(canales)]
    cruce = pd.crosstab(v["canal"], v["periodo"]).loc[canales, ["base", "caida"]]
    res = stats.chi2_contingency(cruce)
    v_cramer = np.sqrt(res.statistic / (cruce.to_numpy().sum() * (min(cruce.shape) - 1)))
    esperado_min = res.expected_freq.min()
    conclusion = concluir(res.pvalue, "El canal y el periodo no son independientes: la mezcla de canales cambió",
                          "No hay evidencia de que la mezcla de canales cambiara")
    subtitulo(titulo_prueba)
    tabla(["Canal", "Base", "% base", "Caída", "% caída"],
          [[canal, n(cruce.loc[canal, "base"]), pct(cruce.loc[canal, "base"] / cruce["base"].sum()),
            n(cruce.loc[canal, "caida"]), pct(cruce.loc[canal, "caida"] / cruce["caida"].sum())] for canal in canales])
    print(f"Chi-cuadrado = {n(res.statistic, 2)}   g.l. = {res.dof}   {texto_p(res.pvalue)}")
    print(f"V de Cramér = {n(v_cramer, 3)}   (frecuencia esperada mínima = {n(esperado_min, 1)}; válida si >= 5)")
    print(f"Conclusión: {conclusion}")
    rep.datos[clave] = {"canales": canales, "tabla": cruce.to_dict(), "chi2": res.statistic, "gl": int(res.dof),
                        "p": res.pvalue, "v_cramer": v_cramer, "esperada_minima": esperado_min,
                        "conclusion": conclusion}


def kruskal_dia_semana(c, rep):
    subtitulo("Kruskal-Wallis: ¿cambian los pedidos según el día de la semana?")
    filas, salida = [], {}
    for nombre, g in (("Base + caída", c), ("Solo base", c[c["periodo"] == "base"]),
                      ("Solo caída", c[c["periodo"] == "caida"])):
        grupos = [x["pedidos"].to_numpy() for _, x in g.groupby("dia_semana")]
        r = stats.kruskal(*grupos)
        epsilon = r.statistic / (len(g) - 1)
        veredicto = "hay diferencias" if r.pvalue < ALFA else "sin diferencias claras"
        salida[nombre] = {"H": r.statistic, "gl": len(grupos) - 1, "p": r.pvalue, "epsilon2": epsilon,
                          "conclusion": veredicto}
        filas.append([nombre, n(r.statistic, 2), len(grupos) - 1, fmt_p(r.pvalue), n(epsilon, 3), veredicto])
    tabla(["Muestra", "H", "g.l.", "valor p", "epsilon²", "Conclusión (alfa 0,05)"], filas)
    rep.datos["kruskal_dia_semana"] = salida
    print("epsilon² mide cuánta de la variación de los pedidos explica el día de la semana (0 a 1).")


def prueba_ticket(ventas, rep, rng):
    v = ventas[ventas["periodo"].isin(["base", "caida"])]
    base = v[v["periodo"] == "base"]["total_amount"].to_numpy(dtype=float)
    caida = v[v["periodo"] == "caida"]["total_amount"].to_numpy(dtype=float)
    r = mann_whitney(caida, base)
    conclusion = concluir(r["p"], "El ticket de la caída es significativamente distinto al del periodo base",
                          "No hay diferencia significativa en el ticket")
    mostrar_mann_whitney("Mann-Whitney: ticket por pedido, caída vs base (delta > 0: caída mayor)", "Caída", "Base",
                         caida, base, r, conclusion, pesos)
    ic = bootstrap_diferencia_medias(caida, base, rng)
    print(f"Diferencia de medias (caída - base) = {pesos(caida.mean() - base.mean())}   "
          f"IC 95 % bootstrap: [{pesos(ic[0])} ; {pesos(ic[1])}]")
    if (np.median(caida) - np.median(base)) * (caida.mean() - base.mean()) < 0:
        print("Lectura: la mediana y la media se mueven en sentidos opuestos (pocos pedidos muy grandes jalan la media); "
              "por eso el efecto es insignificante y el IC de la media puede incluir el 0.")
    rep.datos["ticket"] = {"pedidos_base": len(base), "pedidos_caida": len(caida), "media_base": base.mean(),
                           "media_caida": caida.mean(), "mediana_base": np.median(base),
                           "mediana_caida": np.median(caida), "mann_whitney_caida_vs_base": r,
                           "diferencia_medias": caida.mean() - base.mean(), "ic95_bootstrap": ic.tolist(),
                           "conclusion": conclusion}


def main():
    d = cargar()
    c = dias_comparables(d.diario)
    rng = np.random.default_rng(SEMILLA)
    with Reporte("a03_inferencia") as rep:
        titulo("PASO 3 - INFERENCIA ESTADÍSTICA (alfa = 0,05)")
        prueba_pedidos_por_dia(c, rep, rng)
        chi_cuadrado(d.ventas, ["mesa", "llevar", "domicilio"], "Chi-cuadrado: canal x periodo", "chi2_canal_periodo", rep)
        chi_cuadrado(d.ventas, ["mesa", "llevar"], "Chi-cuadrado sin domicilio: mesa vs llevar x periodo",
                     "chi2_mesa_llevar_periodo", rep)
        print("Se excluyen los pedidos 'sin_dato' (menos de 5 en total): su frecuencia esperada sería insuficiente.")
        kruskal_dia_semana(c, rep)
        prueba_ticket(d.ventas, rep, rng)


if __name__ == "__main__":
    main()
