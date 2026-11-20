"""Paso 7 - Segmentación de clientes con RFM (recencia, frecuencia, monto) y comparación con K-Means.

Solo hay cliente identificado en los pedidos de domicilio (y unos pocos 'sin_dato'); la salida
muestra únicamente agregados y códigos anónimos C###.

Ejecutar desde backend/:  venv\\Scripts\\python -m analisis.a07_segmentacion
"""
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from analisis.comun import (COLOR_BASE, COLOR_CAIDA, COLOR_NEUTRO, SEMILLA, Reporte, cargar, fecha_corta,
                            formato_es, n, nueva_figura, pct, pesos, subtitulo, tabla, titulo)

# Reglas de segmento (se evalúan en este orden; la primera que se cumple gana).
# R = puntaje de recencia 1-5 (5 = compró hace poco), F = número real de pedidos.
SEGMENTOS = [
    ("Campeones", lambda r, f: f >= 4 and r >= 4, "Reconocerlos y darles un beneficio exclusivo"),
    ("Leales", lambda r, f: f >= 3 and r >= 3, "Mantener la relación con un programa de puntos"),
    ("Prometedores", lambda r, f: f >= 2 and r >= 4, "Invitarlos a un tercer pedido con un combo"),
    ("Necesitan atención", lambda r, f: f >= 2 and r == 3, "Recordarles el menú antes de que se enfríen"),
    ("En riesgo", lambda r, f: f >= 2 and r <= 2, "Campaña de reactivación con oferta personal"),
    ("Nuevos", lambda r, f: f == 1 and r >= 4, "Dar la bienvenida y lograr el segundo pedido"),
    ("Una sola vez", lambda r, f: f == 1 and r <= 3, "Oferta de regreso con envío gratis"),
]


def calcular_rfm(ventas, referencia):
    """RFM por cliente de domicilio: días desde el último pedido, número de pedidos y dinero gastado."""
    g = ventas.groupby(ventas["customer_id"].astype(int))
    return pd.DataFrame({"recencia": (referencia - g["fecha"].max()).dt.days, "frecuencia": g["id"].count(),
                         "monetario": g["total_amount"].sum()})


def puntaje(serie, invertir=False):
    """Puntaje 1-5 por quintiles: 1 + número de cortes (20, 40, 60, 80 %) que el valor supera.

    Con empates (muchos clientes con 1 pedido) los quintiles se agrupan en menos niveles.
    Si `invertir`, el menor valor recibe el puntaje mayor (recencia).
    """
    cortes = serie.quantile([0.2, 0.4, 0.6, 0.8]).to_numpy()
    p = 1 + (serie.to_numpy()[:, None] > cortes).sum(axis=1)
    return pd.Series(6 - p if invertir else p, index=serie.index)


def asignar_segmentos(rfm):
    rfm = rfm.copy()
    rfm["R"] = puntaje(rfm["recencia"], invertir=True)
    rfm["F"] = puntaje(rfm["frecuencia"])
    rfm["M"] = puntaje(rfm["monetario"])
    rfm["segmento"] = [next(nombre for nombre, regla, _ in SEGMENTOS if regla(r, f))
                       for r, f in zip(rfm["R"], rfm["frecuencia"])]
    return rfm


def poblaciones(ventas, clientes, rep):
    ident = ventas[ventas["customer_id"].notna()]
    domicilio = ident[ident["canal"] == "domicilio"]
    en_domicilio = set(domicilio["customer_id"])
    no_domicilio = set(ident["customer_id"]) - en_domicilio
    ultimo = ventas.loc[ventas["canal"] == "domicilio", "fecha"].max()
    referencia = ultimo + pd.Timedelta(days=1)
    rep.datos["poblaciones"] = {
        "clientes_registrados": len(clientes), "clientes_identificados_con_pedidos": ident["customer_id"].nunique(),
        "clientes_de_domicilio": len(en_domicilio), "identificados_no_domicilio": len(no_domicilio),
        "registrados_sin_pedidos": len(clientes) - ident["customer_id"].nunique(),
        "pedidos_de_domicilio_con_cliente": len(domicilio), "ultimo_domicilio": ultimo, "fecha_referencia": referencia}
    subtitulo("Poblaciones")
    print(f"Clientes registrados: {n(len(clientes))}; con al menos un pedido pagado identificado: "
          f"{n(ident['customer_id'].nunique())}")
    print(f"(i) Clientes de domicilio: {n(len(en_domicilio))} ({n(len(domicilio))} pedidos). Son los que se segmentan.")
    print(f"(ii) Identificados que no son de domicilio: {len(no_domicilio)} (solo pedidos 'sin_dato'); "
          "son muy pocos para segmentarlos. En mesa y llevar nadie se identifica.")
    print(f"Fecha de referencia: {fecha_corta(referencia)} (día siguiente al último domicilio, {fecha_corta(ultimo)}). "
          "Se usa esa fecha y no 'hoy' porque, si el servicio se suspende, medir hasta hoy marcaría a todos como perdidos.")
    if ultimo == ventas["fecha"].max():
        print("En estos datos el servicio se reanudó, así que la referencia coincide con el corte de los datos.")
    return domicilio, referencia


def mostrar_segmentos(rfm, codigos, rep):
    total_dinero = rfm["monetario"].sum()
    filas, salida = [], []
    for nombre, _, accion in SEGMENTOS:
        g = rfm[rfm["segmento"] == nombre]
        fila = {"segmento": nombre, "clientes": len(g), "pct_clientes": len(g) / len(rfm), "dinero": g["monetario"].sum(),
                "pct_dinero": g["monetario"].sum() / total_dinero, "recencia_media": g["recencia"].mean(),
                "frecuencia_media": g["frecuencia"].mean(), "ticket_cliente": g["monetario"].mean(),
                "puntaje_r": g["R"].mean(), "puntaje_f": g["F"].mean(), "puntaje_m": g["M"].mean(), "accion": accion}
        salida.append(fila)
        filas.append([nombre, fila["clientes"], pct(fila["pct_clientes"]), pesos(fila["dinero"]), pct(fila["pct_dinero"]),
                      n(fila["recencia_media"]) if len(g) else "-", n(fila["frecuencia_media"], 1) if len(g) else "-", accion])
    top = rfm.sort_values("monetario", ascending=False).head(5)
    rep.datos["segmentos"] = {"tabla": salida, "dinero_total": total_dinero,
                              "top_clientes": [{"codigo": codigos[i], "pedidos": int(r.frecuencia), "dinero": r.monetario,
                                                "segmento": r.segmento} for i, r in top.iterrows()]}
    subtitulo("Segmentos RFM de los clientes de domicilio")
    print("Reglas (R = puntaje de recencia 1-5, F = pedidos; se evalúan en orden):")
    print("  Campeones: F >= 4 y R >= 4 | Leales: F >= 3 y R >= 3 | Prometedores: F >= 2 y R >= 4 | Necesitan atención: F >= 2 y R = 3")
    print("  En riesgo: F >= 2 y R <= 2 | Nuevos: F = 1 y R >= 4 | Una sola vez: F = 1 y R <= 3\n")
    tabla(["Segmento", "Clientes", "% clientes", "Dinero", "% dinero", "Recencia", "Pedidos", "Acción sugerida"], filas,
          izquierda=(0, 7))
    print(f"\nTotal: {n(len(rfm))} clientes y {pesos(total_dinero)}. Recencia en días medios; pedidos medios por cliente.")
    subtitulo("Puntajes medios por segmento (quintiles 1-5)")
    tabla(["Segmento", "R", "F", "M"], [[f["segmento"], n(f["puntaje_r"], 1), n(f["puntaje_f"], 1), n(f["puntaje_m"], 1)]
                                         for f in salida if f["clientes"]])
    subtitulo("Cinco clientes con mayor gasto (código anónimo)")
    tabla(["Código", "Pedidos", "Dinero", "Segmento"],
          [[codigos[i], int(r.frecuencia), pesos(r.monetario), r.segmento] for i, r in top.iterrows()], izquierda=(0, 3))
    return salida


def kmeans(rfm, rep):
    X = StandardScaler().fit_transform(np.log1p(rfm[["recencia", "frecuencia", "monetario"]]))
    siluetas, modelos = {}, {}
    for k in range(2, 7):
        modelos[k] = KMeans(n_clusters=k, n_init=10, random_state=SEMILLA).fit(X)
        siluetas[k] = float(silhouette_score(X, modelos[k].labels_))
    mejor = max(siluetas, key=siluetas.get)
    etiquetas = modelos[mejor].labels_
    subtitulo("K-Means (variables en log y estandarizadas, semilla 42)")
    tabla(["k", "Silueta", ""], [[k, n(s, 3), "<- mejor" if k == mejor else ""] for k, s in siluetas.items()])
    perfil = rfm.assign(grupo=etiquetas).groupby("grupo").agg(
        clientes=("recencia", "size"), recencia=("recencia", "median"), frecuencia=("frecuencia", "median"),
        monetario=("monetario", "median"), dinero=("monetario", "sum")).sort_values("dinero", ascending=False)
    print(f"\nPerfil de los {mejor} grupos (medianas):")
    tabla(["Grupo", "Clientes", "% clientes", "Recencia", "Pedidos", "Gasto", "% dinero"],
          [[f"Grupo {i + 1}", int(r.clientes), pct(r.clientes / len(rfm)), n(r.recencia), n(r.frecuencia),
            pesos(r.monetario), pct(r.dinero / rfm["monetario"].sum())] for i, (_, r) in enumerate(perfil.iterrows())])
    ari = adjusted_rand_score(rfm["segmento"], etiquetas)
    print(f"\nConcordancia con los segmentos por reglas (índice de Rand ajustado): {n(ari, 3)} (1 = idénticos, 0 = azar).")
    rep.datos["kmeans"] = {"silueta_por_k": siluetas, "mejor_k": mejor, "silueta_mejor": siluetas[mejor],
                           "rand_ajustado_vs_reglas": ari, "semilla": SEMILLA,
                           "grupos": [{"clientes": int(r.clientes), "pct_clientes": r.clientes / len(rfm),
                                       "recencia_mediana": r.recencia, "frecuencia_mediana": r.frecuencia,
                                       "gasto_mediano": r.monetario, "pct_dinero": r.dinero / rfm["monetario"].sum()}
                                      for _, r in perfil.iterrows()]}


def grafica_segmentos(segmentos, rep):
    segmentos = [s for s in segmentos if s["clientes"]][::-1]
    fig, ax = nueva_figura()
    y = np.arange(len(segmentos))
    for desplazamiento, clave, color, etiqueta in ((0.2, "pct_clientes", COLOR_BASE, "% de clientes"),
                                                   (-0.2, "pct_dinero", COLOR_CAIDA, "% del dinero")):
        valores = [s[clave] * 100 for s in segmentos]
        barras = ax.barh(y + desplazamiento, valores, height=0.38, color=color, label=etiqueta)
        for barra, v in zip(barras, valores):
            ax.text(v + 0.6, barra.get_y() + barra.get_height() / 2, n(v, 1) + " %", va="center", fontsize=10)
    ax.set_yticks(y, [s["segmento"] for s in segmentos])
    ax.set_xlabel("Porcentaje del total")
    ax.set_title("Clientes de domicilio: % de clientes vs % del dinero por segmento")
    ax.grid(axis="y", visible=False)
    formato_es(ax.xaxis)
    ax.set_xlim(0, max(s["pct_clientes"] for s in segmentos) * 100 * 1.15)
    ax.legend(frameon=False, loc="upper right")
    fig.text(0.01, 0.01, "Segmentos RFM por reglas; el dinero es lo gastado en pedidos de domicilio pagados.",
             fontsize=9, color=COLOR_NEUTRO)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    rep.guardar_figura(fig, "clientes_vs_dinero")


def main():
    d = cargar()
    codigos = d.clientes.set_index("id")["codigo_anonimo"].to_dict()
    with Reporte("a07_segmentacion") as rep:
        titulo("PASO 7 - SEGMENTACIÓN DE CLIENTES (RFM)")
        domicilio, referencia = poblaciones(d.ventas, d.clientes, rep)
        rfm = asignar_segmentos(calcular_rfm(domicilio, referencia))
        rep.datos["rfm_resumen"] = rfm[["recencia", "frecuencia", "monetario"]].describe().to_dict()
        segmentos = mostrar_segmentos(rfm, codigos, rep)
        kmeans(rfm, rep)
        grafica_segmentos(segmentos, rep)


if __name__ == "__main__":
    main()
