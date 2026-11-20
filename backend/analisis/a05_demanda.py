"""Paso 5 - Pronóstico de demanda: competencia de tres modelos con validación walk-forward.

Modelos (todos pronostican pedidos pagados por día abierto y solo ven el pasado):
  M1  promedio de los últimos 24 días abiertos.
  M2  promedio del mismo día de la semana en sus últimas 4 apariciones.
  M3  XGBoost que predice la proporción (pedidos del día / nivel reciente) con día de la semana,
      quincena, festivo, la misma semana anterior (relativa al nivel) y los días hacia adelante;
      el pronóstico es proporción x nivel, donde el nivel es el promedio de los últimos 24 días
      abiertos en el momento de pronosticar.

Validación walk-forward: en cada ventana de prueba los modelos se arman solo con datos anteriores
a la ventana. Horizonte 7 días: 8 ventanas semanales; horizonte 30 días: 2 ventanas.
Las métricas se calculan sobre días abiertos que no son casi vacíos (más de 5 pedidos), porque
esos días no son predecibles con calendario ni con historia.

Ejecutar desde backend/:  venv\\Scripts\\python -m analisis.a05_demanda
"""
import holidays
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter
from sklearn.metrics import r2_score
from xgboost import XGBRegressor

from analisis.comun import (COLOR_BASE, COLOR_CAIDA, COLOR_NEUTRO, DIAS, FIN_CAIDA, MESES, SEMILLA,
                            UMBRAL_CASI_SIN_PEDIDOS, Reporte, cargar, fecha_corta, formato_es, n,
                            nueva_figura, pct, subtitulo, tabla, titulo)

NIVEL_DIAS = 24            # ventana del nivel reciente (4 semanas de 6 días abiertos)
SEMANAS_MISMO_DIA = 4
VENTANAS = {7: 8, 30: 2}   # horizonte en días -> número de ventanas de prueba
DIAS_PRONOSTICO = 30
INICIO_PRONOSTICO = FIN_CAIDA + pd.Timedelta(days=2)   # 14-nov: el 13-nov está incompleto
MODELOS = {"M1": "M1 Promedio 24 días", "M2": "M2 Mismo día (4 sem.)", "M3": "M3 XGBoost"}
VARIABLES = ["dia_semana", "es_quincena", "es_festivo", "semana_anterior", "dias_adelante"]
NOMBRE_VARIABLE = {"dia_semana": "Día de la semana", "es_quincena": "Quincena", "es_festivo": "Festivo",
                   "semana_anterior": "Semana anterior", "dias_adelante": "Días hacia adelante"}


class Historia:
    """Calendario completo (pasado y futuro) con pedidos, nivel reciente y banderas de calendario."""

    def __init__(self, diario):
        fechas = pd.date_range(diario["fecha"].min(), INICIO_PRONOSTICO + pd.Timedelta(days=DIAS_PRONOSTICO),
                               freq="D")
        festivos = holidays.Colombia(years=sorted(set(fechas.year)))
        self.fechas = fechas
        self.dia_semana = fechas.day_of_week.to_numpy()
        self.es_festivo = np.array([f.date() in festivos for f in fechas])
        # Quincena = día 15 y último día del mes (misma regla que dim_fecha).
        self.es_quincena = ((fechas.day == 15) | ((fechas + pd.Timedelta(days=1)).month != fechas.month))
        self.abierto = self.dia_semana != 1
        conocido = diario[diario["abierto"] & (diario["fecha"] <= FIN_CAIDA)].set_index("fecha")["pedidos"]
        self.y = conocido.reindex(fechas).to_numpy(dtype=float)
        nivel = conocido.rolling(NIVEL_DIAS).mean().reindex(fechas).ffill()
        self.nivel = nivel.to_numpy()
        hist = diario.sort_values("fecha")
        self.coincide_dim_fecha = bool(
            (hist["es_festivo"].astype(bool).to_numpy() == self.es_festivo[:len(hist)]).all()
            and (hist["es_quincena"].astype(bool).to_numpy() == self.es_quincena[:len(hist)]).all())

    def pos(self, fecha):
        return int(self.fechas.get_loc(pd.Timestamp(fecha)))


def pares(h, origenes, saltos, hasta):
    """Filas (origen, objetivo) con sus variables. `hasta` limita el objetivo a lo ya conocido."""
    o = np.repeat(origenes, len(saltos))
    g = np.tile(saltos, len(origenes))
    t = o + g
    ok = (t <= hasta) & (t < len(h.fechas)) & h.abierto[np.minimum(t, len(h.fechas) - 1)] & ~np.isnan(h.nivel[o])
    o, g, t = o[ok], g[ok], t[ok]
    s = t - 7 * np.ceil(g / 7).astype(int)   # mismo día de la semana, último ya observado en el origen
    X = pd.DataFrame({"dia_semana": h.dia_semana[t], "es_quincena": h.es_quincena[t].astype(int),
                      "es_festivo": h.es_festivo[t].astype(int), "semana_anterior": h.y[s] / h.nivel[o],
                      "dias_adelante": g})
    return X, h.y[t] / h.nivel[o], o, t


def entrenar_xgboost(h, origen, max_dias):
    """XGBoost con todos los pares (origen, objetivo) cuyo objetivo ya era conocido en `origen`."""
    X, y, _, _ = pares(h, np.arange(origen), np.arange(1, max_dias + 1), hasta=origen)
    modelo = XGBRegressor(n_estimators=200, max_depth=3, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                          random_state=SEMILLA, n_jobs=1, tree_method="hist")
    return modelo.fit(X[VARIABLES], y)


def pronostico_m1(h, origen, objetivos):
    return np.full(len(objetivos), h.nivel[origen])


def pronostico_m2(h, origen, objetivos, g):
    s = objetivos - 7 * np.ceil(g / 7).astype(int)
    anteriores = np.stack([np.where(s - 7 * j >= 0, h.y[np.maximum(s - 7 * j, 0)], np.nan)
                           for j in range(SEMANAS_MISMO_DIA)])
    return np.nanmean(anteriores, axis=0)


def pronosticar(h, origen, saltos, modelo_xgb):
    """Los tres pronósticos para los días abiertos a `saltos` días del origen."""
    X, _, _, t = pares(h, np.array([origen]), saltos, hasta=len(h.fechas))
    g = X["dias_adelante"].to_numpy()
    salida = pd.DataFrame({"fecha": h.fechas[t], "dia": [DIAS[d] for d in X["dia_semana"]], "dias_adelante": g,
                           "M1": pronostico_m1(h, origen, t), "M2": pronostico_m2(h, origen, t, g),
                           "M3": modelo_xgb.predict(X[VARIABLES]) * h.nivel[origen]})
    salida["real"] = h.y[t]
    return salida


def validar(h):
    """Walk-forward: devuelve una fila por día abierto de prueba con el pronóstico de cada modelo."""
    fin = h.pos(FIN_CAIDA)
    filas = []
    for horizonte, ventanas in VENTANAS.items():
        for k in range(ventanas):
            origen = fin - horizonte * (k + 1)
            xgb = entrenar_xgboost(h, origen, horizonte)
            p = pronosticar(h, origen, np.arange(1, horizonte + 1), xgb)
            p["horizonte"], p["ventana"] = horizonte, k + 1
            p["origen"] = h.fechas[origen]
            filas.append(p)
    pruebas = pd.concat(filas, ignore_index=True)
    pruebas["evaluable"] = pruebas["real"] > UMBRAL_CASI_SIN_PEDIDOS
    return pruebas


def metricas(pruebas):
    """MAE y R² por horizonte y modelo, sobre días abiertos no anómalos."""
    salida = {}
    for horizonte, g in pruebas[pruebas["evaluable"]].groupby("horizonte"):
        salida[int(horizonte)] = {
            m: {"mae": float(np.abs(g["real"] - g[m]).mean()), "r2": float(r2_score(g["real"], g[m])),
                "dias_evaluados": len(g)} for m in MODELOS}
        salida[int(horizonte)]["ganador"] = min(MODELOS, key=lambda m: salida[int(horizonte)][m]["mae"])
    return salida


def mostrar_metricas(pruebas, met):
    subtitulo("Ventanas de prueba (MAE en pedidos por día abierto, días no anómalos)")
    filas = []
    for (horizonte, ventana), g in pruebas.groupby(["horizonte", "ventana"]):
        e = g[g["evaluable"]]
        filas.append([f"{horizonte} d", ventana, f"{fecha_corta(g['fecha'].min())} a {fecha_corta(g['fecha'].max())}",
                      len(e)] + [n(np.abs(e["real"] - e[m]).mean(), 2) for m in MODELOS])
    tabla(["Horiz.", "Ventana", "Fechas", "Días"] + list(MODELOS), filas)
    subtitulo("Comparación de modelos (todas las ventanas juntas)")
    filas = []
    for horizonte, r in met.items():
        for m, nombre in MODELOS.items():
            filas.append([f"{horizonte} días", nombre, r[m]["dias_evaluados"], n(r[m]["mae"], 2), n(r[m]["r2"], 3),
                          "<- mejor" if r["ganador"] == m else ""])
    tabla(["Horizonte", "Modelo", "Días", "MAE", "R²", ""], filas)
    print("R² negativo = el modelo explica menos variación que simplemente usar el promedio de los días de prueba.")


def elegir_modelo(met):
    """Regla: el ganador a 30 días; XGBoost si gana a 7 días."""
    if met[7]["ganador"] == "M3":
        return "M3", "XGBoost gana a 7 días"
    return met[30]["ganador"], f"{MODELOS[met[30]['ganador']]} gana a 30 días y XGBoost no gana a 7 días"


def importancia(modelo):
    pesos = dict(zip(VARIABLES, modelo.feature_importances_))
    subtitulo("Importancia de variables de XGBoost (ganancia normalizada, modelo final)")
    tabla(["Variable", "Importancia"], [[NOMBRE_VARIABLE[v], pct(p)] for v, p in sorted(pesos.items(), key=lambda t: -t[1])])
    return {v: float(p) for v, p in pesos.items()}


def pronostico_final(h, modelo_xgb, elegido, mae):
    origen = h.pos(FIN_CAIDA)
    primer = h.pos(INICIO_PRONOSTICO) - origen
    p = pronosticar(h, origen, np.arange(primer, primer + DIAS_PRONOSTICO), modelo_xgb)
    p["pronostico"] = p[elegido]
    p["minimo"], p["maximo"] = (p["pronostico"] - mae).clip(lower=0), p["pronostico"] + mae
    subtitulo(f"Pronóstico {fecha_corta(INICIO_PRONOSTICO)} a {fecha_corta(p['fecha'].max())} ({MODELOS[elegido]}, banda +/- MAE {n(mae, 2)})")
    tabla(["Fecha", "Día", "Pronóstico", "Rango"],
          [[fecha_corta(f), d, n(x, 1), f"{n(lo, 1)} a {n(hi, 1)}"]
           for f, d, x, lo, hi in zip(p["fecha"], p["dia"], p["pronostico"], p["minimo"], p["maximo"])])
    print(f"\nPromedio pronosticado: {n(p['pronostico'].mean(), 1)} pedidos por día abierto; "
          f"total en {len(p)} días abiertos: {n(p['pronostico'].sum(), 0)} pedidos. El martes no abre y no se muestra.")
    return p


def grafica_pronostico(h, p, elegido, mae, rep):
    reciente = pd.Series(h.y, index=h.fechas).dropna()
    reciente = reciente[reciente.index >= FIN_CAIDA - pd.Timedelta(days=70)]
    fig, ax = nueva_figura()
    ax.plot(reciente.index, reciente.values, color=COLOR_NEUTRO, marker="o", markersize=3.5, linewidth=1.2,
            label="Pedidos reales (días abiertos)")
    ax.fill_between(p["fecha"], p["minimo"], p["maximo"], color=COLOR_BASE, alpha=0.18,
                    label=f"Banda +/- MAE ({n(mae, 1)} pedidos)")
    ax.plot(p["fecha"], p["pronostico"], color=COLOR_BASE, marker="o", markersize=4, linewidth=2,
            label=f"Pronóstico ({MODELOS[elegido][3:]})")
    ax.axvline(INICIO_PRONOSTICO, color=COLOR_CAIDA, linestyle="--", linewidth=1)
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0, interval=2))
    ax.xaxis.set_major_formatter(FuncFormatter(
        lambda v, _: f"{mdates.num2date(v).day} {MESES[mdates.num2date(v).month][:3]}"))
    ax.set_title(f"Pronóstico de pedidos por día abierto, {DIAS_PRONOSTICO} días desde el {fecha_corta(INICIO_PRONOSTICO)}")
    ax.set_ylabel("Pedidos pagados")
    ax.set_ylim(bottom=0)
    ax.grid(axis="x", visible=False)
    formato_es(ax.yaxis)
    fig.legend(*ax.get_legend_handles_labels(), frameon=False, loc="lower center", ncol=3)
    fig.text(0.01, 0.01, "El martes no abre y no se muestra. La banda usa el MAE de la validación walk-forward a 30 días.",
             fontsize=9, color=COLOR_NEUTRO)
    fig.tight_layout(rect=(0, 0.1, 1, 1))
    rep.guardar_figura(fig, "pronostico_30_dias")


def main():
    d = cargar()
    h = Historia(d.diario)
    with Reporte("a05_demanda") as rep:
        titulo("PASO 5 - PRONÓSTICO DE DEMANDA (walk-forward)")
        print(f"Calendario (quincena y festivo) coincide con dim_fecha en todo el histórico: {'sí' if h.coincide_dim_fecha else 'NO'}")
        pruebas = validar(h)
        met = metricas(pruebas)
        mostrar_metricas(pruebas, met)
        elegido, motivo = elegir_modelo(met)
        print(f"\nModelo usado para el pronóstico: {MODELOS[elegido]} ({motivo}).")
        modelo = entrenar_xgboost(h, h.pos(FIN_CAIDA), DIAS_PRONOSTICO + 1)
        rep.datos["importancia_xgboost"] = importancia(modelo)
        mae = met[30][elegido]["mae"]
        p = pronostico_final(h, modelo, elegido, mae)
        grafica_pronostico(h, p, elegido, mae, rep)
        rep.datos.update({
            "metricas": met, "modelo_elegido": elegido, "motivo": motivo, "mae_banda": mae,
            "detalle_pruebas": pruebas[["horizonte", "ventana", "origen", "fecha", "real", "evaluable", *MODELOS]]
            .to_dict("records"),
            "pronostico": p[["fecha", "dia", "pronostico", "minimo", "maximo"]].to_dict("records"),
            "pronostico_promedio_por_dia_abierto": p["pronostico"].mean(), "pronostico_total_pedidos": p["pronostico"].sum(),
            "calendario_coincide_dim_fecha": h.coincide_dim_fecha, "semilla": SEMILLA})


if __name__ == "__main__":
    main()
