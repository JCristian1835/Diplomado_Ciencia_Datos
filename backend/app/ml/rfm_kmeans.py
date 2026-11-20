"""Segmentación RFM con K-Means (k de 2 a 6 por coeficiente de silueta)."""
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from app.domain.errors import ValidacionError


# Etiquetas de mejor a peor puntaje RFM según el número de clusters (cada cluster recibe una distinta).
_ETIQUETAS_POR_K = {
    2: ["Campeones", "Ocasionales"],
    3: ["Campeones", "Ocasionales", "En riesgo"],
    4: ["Campeones", "Leales", "Ocasionales", "En riesgo"],
    5: ["Campeones", "Leales", "Prometedores", "En riesgo", "Perdidos"],
    6: ["Campeones", "Leales", "Prometedores", "Ocasionales", "En riesgo", "Perdidos"],
}


def _etiquetar(rfm: pd.DataFrame) -> dict[int, str]:
    """Etiqueta única por cluster: se ordenan por puntaje RFM (recencia baja, frecuencia y monto altos)."""
    cols = ["recency", "frequency", "monetary"]
    medias = rfm.groupby("cluster")[cols].mean()
    z = (medias - rfm[cols].mean()) / rfm[cols].std(ddof=0).replace(0, 1)
    orden = (z["frequency"] + z["monetary"] - z["recency"]).sort_values(ascending=False).index
    nombres = _ETIQUETAS_POR_K[len(orden)]
    etiquetas = dict(zip(orden, nombres))
    # "En riesgo"/"Perdidos" exigen recencia peor que la mediana; si no, el cluster es de clientes recientes.
    for c, nombre in etiquetas.items():
        if (nombre in ("En riesgo", "Perdidos") and medias.loc[c, "recency"] <= rfm["recency"].median()
                and "Nuevos" not in etiquetas.values()):
            etiquetas[c] = "Nuevos"
    return etiquetas


def segmentar(rfm: pd.DataFrame, k_min: int = 2, k_max: int = 6, semilla: int = 42) -> tuple[pd.DataFrame, dict]:
    """Devuelve el RFM con `cluster` y `segment_label`, y métricas (k, silueta, silueta por k)."""
    if len(rfm) < k_max + 2:
        raise ValidacionError("No hay suficientes clientes identificados para segmentar")
    X = np.column_stack([np.log1p(rfm["recency"]), np.log1p(rfm["frequency"]), np.log1p(rfm["monetary"])])
    Xs = StandardScaler().fit_transform(X)
    mejor, mejor_s, siluetas = None, -2.0, {}
    for k in range(k_min, k_max + 1):
        km = KMeans(n_clusters=k, n_init=10, random_state=semilla).fit(Xs)
        if len(set(km.labels_)) < 2:
            continue
        s = float(silhouette_score(Xs, km.labels_))
        siluetas[k] = round(s, 4)
        if s > mejor_s:
            mejor, mejor_s = km, s
    out = rfm.copy()
    out["cluster"] = mejor.labels_.astype(int)
    out["segment_label"] = out["cluster"].map(_etiquetar(out))
    metricas = {"k": int(mejor.n_clusters), "silhouette": float(mejor_s), "silhouette_por_k": siluetas,
                "n_clientes": int(len(out))}
    return out, metricas
