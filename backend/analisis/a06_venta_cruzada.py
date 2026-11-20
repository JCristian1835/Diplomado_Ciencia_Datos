"""Paso 6 - Venta cruzada: canastas, reglas Apriori, bebidas que faltan, márgenes y combos.

Se usan todos los pedidos pagados (la canasta no depende del periodo).
Las reglas se calculan con la misma función que usa la plataforma (app.ml.basket_apriori).

Ejecutar desde backend/:  venv\\Scripts\\python -m analisis.a06_venta_cruzada
"""
import pandas as pd

from analisis.comun import (COLOR_BASE, COLOR_CAIDA, COLOR_NEUTRO, Reporte, cargar, formato_es, n,
                            nueva_figura, pct, pesos, subtitulo, tabla, titulo)
from app.domain.costos import costo_es_real
from app.ml.basket_apriori import minar_reglas

SOPORTE_MINIMO = 0.005
CONFIANZA_MINIMA = 0.15
LIFT_MINIMO = 1.0       # se aceptan reglas con lift estrictamente mayor
LIFT_COMBO = 2.0
DESCUENTO_COMBO = 0.10
TOP_REGLAS = 10
TOP_COMBOS = 5
TOLERANCIA_PRECIO = 0.20
FRACCION_PRECIOS_MIXTOS = 0.30
# Categorías de bebida según products.category: es la única cuyos productos son todos bebidas
# (gaseosas, jugos, cervezas y agua). Las demás categorías son platos.
CATEGORIAS_BEBIDA = {"bebidas"}


def canastas(items, rep):
    por_pedido = items.groupby("sale_id")["product_id"].nunique()
    dos_o_mas = (por_pedido >= 2).mean()
    rep.datos["canastas"] = {"pedidos": len(por_pedido), "con_2_o_mas_productos": int((por_pedido >= 2).sum()),
                             "pct_con_2_o_mas": dos_o_mas, "productos_promedio": por_pedido.mean(),
                             "maximo_productos": int(por_pedido.max())}
    subtitulo("Tamaño de la canasta (productos distintos por pedido pagado)")
    grupos = por_pedido.clip(upper=4).value_counts().sort_index()
    tabla(["Productos distintos", "Pedidos", "% de pedidos"],
          [["4 o más" if k == 4 else k, n(v), pct(v / len(por_pedido))] for k, v in grupos.items()])
    print(f"\nPedidos con 2 o más productos distintos: {n(int((por_pedido >= 2).sum()))} de {n(len(por_pedido))} "
          f"({pct(dos_o_mas)}); promedio {n(por_pedido.mean(), 2)} productos por pedido.")


def matriz(items, columna):
    """Matriz binaria pedido x (producto o categoría)."""
    m = items[["sale_id", columna]].drop_duplicates().assign(v=True)
    return m.set_index(["sale_id", columna])["v"].unstack(fill_value=False).astype(bool)


def reglas_de(items, columna, nombre, rep, clave):
    reglas = minar_reglas(matriz(items, columna), SOPORTE_MINIMO, CONFIANZA_MINIMA, LIFT_MINIMO, max_reglas=100_000)
    top = reglas.head(TOP_REGLAS)
    rep.datos[clave] = {"n_reglas": len(reglas), "soporte_minimo": SOPORTE_MINIMO, "confianza_minima": CONFIANZA_MINIMA,
                        "lift_minimo": LIFT_MINIMO, "lift_maximo": reglas["lift"].max() if len(reglas) else None,
                        "top": top.to_dict("records")}
    subtitulo(f"Reglas Apriori por {nombre}: soporte >= {n(SOPORTE_MINIMO, 3)}, confianza >= {n(CONFIANZA_MINIMA, 2)}, lift > {n(LIFT_MINIMO)}")
    print(f"Número de reglas: {len(reglas)}")
    tabla(["Si compra", "Entonces compra", "Soporte", "Confianza", "Lift"],
          [[a, c, n(s, 4), n(cf, 3), n(lf, 2)] for a, c, s, cf, lf in
           zip(top["antecedent"], top["consequent"], top["support"], top["confidence"], top["lift"])])
    return reglas


def sin_bebida(items, rep):
    """% de pedidos sin bebida entre los pedidos que incluyen cada categoría de plato."""
    es_bebida = items["category"].isin(CATEGORIAS_BEBIDA)
    con_bebida = set(items.loc[es_bebida, "sale_id"])
    platos = items[~es_bebida]
    subtitulo("Pedidos sin bebida por categoría de plato")
    print("Categorías de bebida (products.category): " + ", ".join(sorted(CATEGORIAS_BEBIDA)) + " -> "
          + ", ".join(sorted(items.loc[es_bebida, "name"].unique())))
    filas = []
    for categoria, g in platos.groupby("category"):
        pedidos = set(g["sale_id"])
        sin = len(pedidos - con_bebida)
        filas.append({"categoria": categoria, "pedidos": len(pedidos), "sin_bebida": sin, "pct_sin_bebida": sin / len(pedidos)})
    filas.sort(key=lambda f: -f["pct_sin_bebida"])
    todos = set(platos["sale_id"])
    total = {"pedidos_con_plato": len(todos), "sin_bebida": len(todos - con_bebida),
             "pct_sin_bebida": len(todos - con_bebida) / len(todos)}
    rep.datos["sin_bebida"] = {"categorias_bebida": sorted(CATEGORIAS_BEBIDA), "por_categoria": filas, "total": total}
    tabla(["Categoría de plato", "Pedidos con la categoría", "Sin bebida", "% sin bebida"],
          [[f["categoria"], n(f["pedidos"]), n(f["sin_bebida"]), pct(f["pct_sin_bebida"])] for f in filas]
          + [["Todos los platos", n(total["pedidos_con_plato"]), n(total["sin_bebida"]), pct(total["pct_sin_bebida"])]])
    print("Un pedido con platos de varias categorías cuenta en cada una de ellas.")
    return filas, total


def margenes(items, productos, rep):
    """Margen por producto con el precio real de venta (mediana de lo cobrado) y el costo efectivo."""
    unidades = items.groupby("product_id")["quantity"].sum()
    m = productos.assign(unidades=productos["id"].map(unidades).fillna(0))
    m["margen"] = m["precio_real"] - m["costo"]
    m["margen_pct"] = m["margen"] / m["precio_real"]
    m = m.sort_values(["category", "margen_pct"], ascending=[True, False])
    rep.datos["margenes"] = [{"producto": r["name"], "categoria": r["category"], "precio_real": r["precio_real"],
                              "costo": r["costo"], "costo_estimado": bool(r["costo_estimado"]), "margen": r["margen"],
                              "margen_pct": r["margen_pct"], "unidades_vendidas": r["unidades"]} for _, r in m.iterrows()]
    subtitulo("Margen por producto (precio real = mediana cobrada; * = costo faltante estimado con la mediana de la categoría)")
    tabla(["Producto", "Categoría", "Precio real", "Costo", "Margen", "Margen %", "Unidades"],
          [[r["name"], r["category"], pesos(r["precio_real"]), pesos(r["costo"]) + ("*" if r["costo_estimado"] else ""),
            pesos(r["margen"]), pct(r["margen_pct"]), n(r["unidades"])] for _, r in m.iterrows()])
    return m.set_index("name")


def hallazgos_catalogo(items, productos, rep):
    """Productos con precio de lista o costo que no cuadran con lo vendido (para corregir el catálogo)."""
    desviado = (items["unit_price"] / items["product_id"].map(productos.set_index("id")["precio_real"]) - 1).abs() > TOLERANCIA_PRECIO
    mixtos = desviado.groupby(items["product_id"]).mean()
    filas = []
    for _, r in productos.iterrows():
        motivos = []
        if r["unit_cost"] > 0 and not costo_es_real(r["unit_price"], r["unit_cost"]):
            motivos.append("costo registrado >= precio de lista")
        if abs(r["precio_real"] / r["unit_price"] - 1) > TOLERANCIA_PRECIO:
            motivos.append("precio de lista distinto al cobrado")
        if mixtos.get(r["id"], 0) > FRACCION_PRECIOS_MIXTOS:
            motivos.append(f"{pct(mixtos[r['id']], 0)} de las ventas con otro precio")
        if motivos:
            filas.append({"producto": r["name"], "hallazgo": "; ".join(motivos), "precio_lista": r["unit_price"],
                          "precio_real": r["precio_real"], "costo_registrado": r["unit_cost"], "costo_usado": r["costo"]})
    rep.datos["hallazgos_catalogo"] = filas
    subtitulo("Hallazgos de calidad del catálogo (se usa el precio real y un costo estimado)")
    tabla(["Producto", "Hallazgo", "Precio lista", "Precio real", "Costo registrado", "Costo usado"],
          [[f["producto"], f["hallazgo"], pesos(f["precio_lista"]), pesos(f["precio_real"]),
            pesos(f["costo_registrado"]), pesos(f["costo_usado"])] for f in filas], izquierda=(0, 1))
    print(f"Criterios: costo >= precio de lista; precio de lista a más de {pct(TOLERANCIA_PRECIO, 0)} del cobrado; "
          f"más de {pct(FRACCION_PRECIOS_MIXTOS, 0)} de las ventas a un precio que se aparta más de {pct(TOLERANCIA_PRECIO, 0)} del real.")


def armar_combo(a, b, s, lf, margen, categorias):
    plato, bebida = (a, b) if categorias[b] in CATEGORIAS_BEBIDA else (b, a)
    suma = margen.loc[a, "precio_real"] + margen.loc[b, "precio_real"]
    precio = suma * (1 - DESCUENTO_COMBO)
    costo = margen.loc[a, "costo"] + margen.loc[b, "costo"]
    return {"plato": plato, "bebida": bebida, "soporte": s, "lift": lf, "suma_precios": suma, "precio_combo": precio,
            "costo": costo, "margen": precio - costo, "margen_pct": (precio - costo) / precio,
            "margen_sin_descuento": suma - costo}


def combos(reglas, margen, categorias, rep):
    """Pares plato + bebida con lift >= 2, los más frecuentes, con precio de combo = 90 % de la suma de precios reales."""
    pares = {}
    for a, c, s, lf in zip(reglas["antecedent"], reglas["consequent"], reglas["support"], reglas["lift"]):
        if a in categorias and c in categorias and (categorias[a] in CATEGORIAS_BEBIDA) != (categorias[c] in CATEGORIAS_BEBIDA):
            pares[tuple(sorted((a, c)))] = (s, lf)
    candidatos = sorted(((p, s, lf) for p, (s, lf) in pares.items() if lf >= LIFT_COMBO), key=lambda t: -t[1])
    sugeridos = [armar_combo(a, b, s, lf, margen, categorias) for (a, b), s, lf in candidatos[:TOP_COMBOS]]
    rep.datos["combos"] = {"descuento": DESCUENTO_COMBO, "lift_minimo": LIFT_COMBO, "pares_candidatos": len(candidatos),
                           "sugeridos": sugeridos}
    subtitulo(f"Combos sugeridos: plato + bebida, lift >= {n(LIFT_COMBO)}, los {TOP_COMBOS} más frecuentes (precio = {pct(1 - DESCUENTO_COMBO, 0)} de la suma de precios reales)")
    print(f"Pares plato + bebida con lift >= {n(LIFT_COMBO)}: {len(candidatos)}")
    tabla(["Plato", "Bebida", "Soporte", "Lift", "Suma precios", "Precio combo", "Costo", "Margen", "Margen %"],
          [[f["plato"], f["bebida"], n(f["soporte"], 4), n(f["lift"], 2), pesos(f["suma_precios"]),
            pesos(f["precio_combo"]), pesos(f["costo"]), pesos(f["margen"]), pct(f["margen_pct"])] for f in sugeridos])


def grafica_sin_bebida(filas, total, rep):
    filas = sorted(filas, key=lambda f: f["pct_sin_bebida"])
    fig, ax = nueva_figura()
    barras = ax.barh([f["categoria"] for f in filas], [f["pct_sin_bebida"] * 100 for f in filas], color=COLOR_BASE, height=0.6)
    for barra, f in zip(barras, filas):
        ax.text(barra.get_width() + 0.8, barra.get_y() + barra.get_height() / 2,
                f"{n(f['pct_sin_bebida'] * 100, 1)} %  (n = {n(f['pedidos'])})", va="center", fontsize=10,
                bbox={"facecolor": "white", "edgecolor": "none", "pad": 1.5}, zorder=5)
    ax.axvline(total["pct_sin_bebida"] * 100, color=COLOR_CAIDA, linestyle="--", linewidth=1.2,
               label=f"Todos los platos: {n(total['pct_sin_bebida'] * 100, 1)} %")
    ax.set_xlim(0, 112)
    ax.set_xticks(range(0, 101, 20))
    ax.set_xlabel("Pedidos sin bebida (%)")
    ax.set_title("Pedidos sin bebida según la categoría de plato")
    ax.grid(axis="y", visible=False)
    formato_es(ax.xaxis)
    ax.legend(frameon=False, loc="lower right")
    fig.text(0.01, 0.01, "Un pedido con platos de varias categorías cuenta en cada una. n = pedidos con la categoría.",
             fontsize=9, color=COLOR_NEUTRO)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    rep.guardar_figura(fig, "pedidos_sin_bebida")


def main():
    d = cargar()
    items = d.items.merge(d.productos[["id", "name", "category"]], left_on="product_id", right_on="id")
    with Reporte("a06_venta_cruzada") as rep:
        titulo("PASO 6 - VENTA CRUZADA")
        canastas(items, rep)
        reglas_producto = reglas_de(items, "name", "producto", rep, "apriori_producto")
        reglas_de(items, "category", "categoría", rep, "apriori_categoria")
        filas, total = sin_bebida(items, rep)
        margen = margenes(items, d.productos, rep)
        hallazgos_catalogo(d.items, d.productos, rep)
        combos(reglas_producto, margen, d.productos.set_index("name")["category"].to_dict(), rep)
        grafica_sin_bebida(filas, total, rep)


if __name__ == "__main__":
    main()
