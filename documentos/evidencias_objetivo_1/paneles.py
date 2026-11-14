"""Generador de paneles HTML autocontenidos (código, terminal y diagrama) para las evidencias del ETL.

Cada página tiene un único elemento `.panel` de 1100 px de ancho; `capturar.mjs` fotografía solo ese elemento.
"""
from __future__ import annotations

import html
from pathlib import Path

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import PythonLexer

ANCHO = 1100
_FORMATO = HtmlFormatter(style="default", nowrap=True)
_CSS_PYGMENTS = _FORMATO.get_style_defs(".codigo")

_CSS = f"""
*{{box-sizing:border-box}}
body{{margin:0;padding:14px;background:#fff;font-family:"Segoe UI",Arial,sans-serif}}
.panel{{width:{ANCHO}px;border:1px solid #b9c0ca;border-radius:8px;overflow:hidden;font-size:15px}}
.cab{{display:flex;justify-content:space-between;gap:16px;padding:10px 16px;background:#e9edf2;color:#1f2933;
  font:600 16px "Segoe UI",Arial,sans-serif;border-bottom:1px solid #b9c0ca}}
.cab .der{{font-weight:400;color:#4a5563}}
.codigo{{background:#fafbfc;padding:10px 0}}
.codigo table{{border-collapse:collapse;width:100%}}
.codigo td{{vertical-align:top;font:15px/1.5 Consolas,"Cascadia Mono","Courier New",monospace}}
.codigo td.n{{width:58px;text-align:right;padding:0 12px 0 0;color:#7b8594;border-right:1px solid #d9dee5;user-select:none}}
.codigo td.c{{padding:0 14px 0 14px;white-space:pre-wrap;overflow-wrap:anywhere;color:#1f2933}}
.codigo tr.dest td{{background:#fff3c4}}
.codigo tr.dest td.n{{color:#6b5300;font-weight:700}}
.codigo tr.sep td{{color:#7b8594;text-align:center;background:#eef1f5;font-style:italic}}
{_CSS_PYGMENTS}
.term{{background:#1b1f27;color:#d9dee7;padding:12px 18px 16px}}
.term pre{{margin:0;font:15px/1.5 Consolas,"Cascadia Mono","Courier New",monospace;white-space:pre-wrap;overflow-wrap:anywhere}}
.term .pr{{color:#7ee787}}
.term .cm{{color:#f0f3f6;font-weight:700}}
.term .nota{{color:#8b98a9}}
.term .hl{{background:#33405a;display:inline-block;width:100%}}
.cab.osc{{background:#2b313c;color:#e6eaf0;border-bottom:1px solid #12151b}}
.cab.osc .der{{color:#9aa7b8}}
svg text{{font-family:"Segoe UI",Arial,sans-serif}}
"""


def _pagina(titulo: str, cuerpo: str) -> str:
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>{html.escape(titulo)}</title>'
            f"<style>{_CSS}</style></head><body>{cuerpo}</body></html>")


def _lineas_resaltadas(codigo: str) -> list[str]:
    return highlight(codigo, PythonLexer(), _FORMATO).split("\n")


def panel_codigo(archivo_rel: str, texto_archivo: list[str], segmentos: list[tuple[int, int]],
                 destacar: tuple[str, ...] = (), derecha: str = "") -> str:
    """Panel de código con números de línea reales. `segmentos` son (desde, hasta) 1-based e inclusivos."""
    filas = []
    for k, (desde, hasta) in enumerate(segmentos):
        if k:
            filas.append('<tr class="sep"><td class="n">⋯</td><td class="c">⋯</td></tr>')
        trozo = texto_archivo[desde - 1:hasta]
        for numero, bruto, resaltado in zip(range(desde, hasta + 1), trozo, _lineas_resaltadas("\n".join(trozo))):
            clase = ' class="dest"' if any(t in bruto for t in destacar) else ""
            filas.append(f'<tr{clase}><td class="n">{numero}</td><td class="c">{resaltado or " "}</td></tr>')
    rango = " · ".join(f"{d}–{h}" for d, h in segmentos)
    cab = (f'<div class="cab"><span>{html.escape(archivo_rel)}</span>'
           f'<span class="der">líneas {rango}{(" · " + html.escape(derecha)) if derecha else ""}</span></div>')
    return _pagina(archivo_rel, f'<div class="panel">{cab}<div class="codigo"><table>{"".join(filas)}</table></div></div>')


def panel_terminal(bloques: list[tuple], titulo: str = "Terminal", ubicacion: str = "",
                   resaltar: tuple[str, ...] = ()) -> str:
    """Panel de terminal. Cada bloque es (comando, salida[, prompt]): el comando ejecutado y su salida real."""
    nl = chr(10)
    partes = []
    for bloque in bloques:
        comando, salida = bloque[0], bloque[1]
        prompt = bloque[2] if len(bloque) > 2 else "PS backend> "
        cmd = nl.join((f'<span class="pr">{html.escape(prompt)}</span>' if i == 0 else "")
                      + f'<span class="cm">{html.escape(c)}</span>' for i, c in enumerate(comando.split(nl)))
        lineas = []
        for linea in salida.rstrip(nl).split(nl):
            esc = html.escape(linea) or " "
            lineas.append(f'<span class="hl">{esc}</span>' if any(t in linea for t in resaltar) else esc)
        partes.append(cmd + nl + nl.join(lineas))
    cab = (f'<div class="cab osc"><span>{html.escape(titulo)}</span>'
           f'<span class="der">{html.escape(ubicacion)}</span></div>')
    return _pagina(titulo, f'<div class="panel">{cab}<div class="term"><pre>' + (nl + nl).join(partes) + "</pre></div></div>")


def tabla_texto(encabezados: list[str], filas: list[list], alinear: str | None = None) -> str:
    """Tabla monoespaciada; `alinear` es una cadena de 'l'/'r' por columna (por defecto izquierda)."""
    filas = [[str(c) for c in f] for f in filas]
    alinear = alinear or "l" * len(encabezados)
    anchos = [max(len(str(h)), *(len(f[i]) for f in filas)) if filas else len(str(h))
              for i, h in enumerate(encabezados)]

    def fmt(fila):
        return "  ".join(c.rjust(anchos[i]) if alinear[i] == "r" else c.ljust(anchos[i])
                         for i, c in enumerate(fila)).rstrip()

    return "\n".join([fmt([str(h) for h in encabezados]), "  ".join("-" * a for a in anchos), *(fmt(f) for f in filas)])


# ---------------------------------------------------------------- diagrama

def _caja(x, y, w, h, relleno, borde, titulo, lineas, color_titulo="#1f2933", tam=15):
    s = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{relleno}" stroke="{borde}" stroke-width="1.6"/>',
         f'<text x="{x + 14}" y="{y + 26}" font-size="17" font-weight="700" fill="{color_titulo}">{html.escape(titulo)}</text>']
    for i, linea in enumerate(lineas):
        s.append(f'<text x="{x + 14}" y="{y + 54 + i * 24}" font-size="{tam}" fill="#2f3a48">{html.escape(linea)}</text>')
    return "".join(s)


def _flecha(puntos: str) -> str:
    return f'<polyline points="{puntos}" fill="none" stroke="#4a5563" stroke-width="2" marker-end="url(#pta)"/>'


def panel_diagrama(origenes: list[str], disparadores: list[str], extraer: list[str], transformar: list[str],
                   cargar: list[str], tablas: list[str], motor: str) -> str:
    alto = 590
    s = ['<defs><marker id="pta" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto">'
         '<path d="M0,0 L10,5 L0,10 z" fill="#4a5563"/></marker></defs>']
    # disparadores
    s.append('<text x="20" y="26" font-size="15" font-weight="700" fill="#4a5563">Quién invoca importar() (los tres usan la misma función)</text>')
    for i, d in enumerate(disparadores):
        x = 20 + i * 352
        s.append(f'<rect x="{x}" y="36" width="336" height="34" rx="6" fill="#eef1f5" stroke="#9aa5b4" stroke-width="1.3"/>'
                 f'<text x="{x + 12}" y="58" font-size="15" fill="#2f3a48">{html.escape(d)}</text>')
    # orígenes
    for i, o in enumerate(origenes):
        x = 20 + i * 540
        s.append(f'<rect x="{x}" y="92" width="520" height="40" rx="6" fill="#fff8e1" stroke="#c9a227" stroke-width="1.6"/>'
                 f'<text x="{x + 14}" y="118" font-size="16" font-weight="600" fill="#3b2f00">{html.escape(o)}</text>')
    s.append(_flecha("180,132 180,176"))
    s.append(_flecha("820,132 820,154 300,154 300,176"))
    # etapas
    for x, titulo, lineas, relleno, borde in ((20, "1 · EXTRAER", extraer, "#e8f1fb", "#4f86c6"),
                                              (390, "2 · TRANSFORMAR", transformar, "#e9f6ec", "#4f9a63"),
                                              (760, "3 · CARGAR", cargar, "#f3ecfa", "#8a63b8")):
        s.append(_caja(x, 176, 320, 200, relleno, borde, titulo, lineas))
    s.append(_flecha("340,276 386,276"))
    s.append(_flecha("710,276 756,276"))
    s.append(_flecha("920,376 920,416"))
    # base de datos
    s.append(f'<rect x="20" y="416" width="1060" height="{alto - 416 - 14}" rx="8" fill="#f4f6f8" stroke="#4a5563" stroke-width="1.6"/>')
    s.append(f'<text x="34" y="442" font-size="17" font-weight="700" fill="#1f2933">{html.escape(motor)}</text>')
    for i, t in enumerate(tablas):
        fila, col = divmod(i, 4)
        x, y = 34 + col * 262, 458 + fila * 54
        s.append(f'<rect x="{x}" y="{y}" width="250" height="40" rx="6" fill="#fff" stroke="#9aa5b4" stroke-width="1.3"/>'
                 f'<text x="{x + 12}" y="{y + 26}" font-size="16" font-family="Consolas,monospace" fill="#1f2933">{html.escape(t)}</text>')
    cab = ('<div class="cab"><span>Arquitectura del ETL Red Rooster</span>'
           '<span class="der">JSON → transformación → SQLite</span></div>')
    return _pagina("Arquitectura ETL", f'<div class="panel">{cab}<svg width="{ANCHO - 2}" height="{alto}" '
                                       f'viewBox="0 0 {ANCHO - 2} {alto}" role="img" aria-label="Diagrama del flujo ETL">'
                                       f'<rect width="100%" height="100%" fill="#fff"/>{"".join(s)}</svg></div>')


def guardar(ruta: Path, contenido: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8")


# ---------------------------------------------------------------- diagrama entidad-relación

_ER_ANCHO, _ER_ALTO = 1800, 1200
_ER_CAJA, _ER_MARGEN = 316, 20
_ER_FILA, _ER_CAB, _ER_PIE = 28, 40, 8


def _er_texto(x, y, texto, tam=15, peso=400, color="#1f2933", ancla="start", halo=False, familia=None):
    extra = ' stroke="#fff" stroke-width="5" paint-order="stroke" stroke-linejoin="round"' if halo else ""
    fam = f' font-family="{familia}"' if familia else ""
    return (f'<text x="{x}" y="{y}" font-size="{tam}" font-weight="{peso}" fill="{color}" text-anchor="{ancla}"{fam}{extra}>'
            f'{html.escape(str(texto))}</text>')


def panel_er(titulo: str, subtitulo: str, tablas: list[dict], fks: list[tuple], logicas: list[tuple],
             grupos: dict[str, dict], posiciones: dict[str, tuple[int, int]]) -> str:
    """ER de lienzo fijo 1800x1200. `tablas`: {nombre, grupo, filas, columnas:[(nombre, tipo, es_pk, es_fk)]};
    `fks`/`logicas`: (tabla_origen, col_origen, tabla_destino, col_destino[, rótulo])."""
    gap_x = (_ER_ANCHO - 2 * _ER_MARGEN - 5 * _ER_CAJA) / 4
    alto = {t["nombre"]: _ER_CAB + len(t["columnas"]) * _ER_FILA + _ER_PIE for t in tablas}
    filas_max = [max(alto[n] for n, (_, f) in posiciones.items() if f == r) for r in range(3)]
    gap_y = (_ER_ALTO - 100 - 40 - sum(filas_max)) / 2
    y_fila = [100, 100 + filas_max[0] + gap_y, 100 + filas_max[0] + filas_max[1] + 2 * gap_y]
    pos = {n: (_ER_MARGEN + c * (_ER_CAJA + gap_x), y_fila[f]) for n, (c, f) in posiciones.items()}
    por_nombre = {t["nombre"]: t for t in tablas}

    def y_col(tabla, col):
        idx = [c[0] for c in por_nombre[tabla]["columnas"]].index(col)
        return pos[tabla][1] + _ER_CAB + idx * _ER_FILA + _ER_FILA / 2

    s = [_er_texto(20, 44, titulo, 32, 700), _er_texto(20, 74, subtitulo, 16, 400, "#4a5563")]
    # relaciones (debajo de las cajas): una línea por FK con cardinalidad N (origen) a 1 (destino)
    for rel in fks + logicas:
        o, co, d, cd = rel[:4]
        punteada = rel in logicas
        trazo = f'stroke="#44505f" stroke-width="2.2"{" stroke-dasharray=" + chr(34) + "8 6" + chr(34) if punteada else ""}'
        (xo, yo), (xd, yd) = pos[o], pos[d]
        (co_c, co_f), (cd_c, cd_f) = posiciones[o], posiciones[d]
        if co_f == cd_f and abs(co_c - cd_c) == 1:
            sentido = -1 if co_c > cd_c else 1
            x1 = xo if sentido < 0 else xo + _ER_CAJA
            x2 = xd + _ER_CAJA if sentido < 0 else xd
            y1, y2, mid = y_col(o, co), y_col(d, cd), (x1 + x2) / 2
            s.append(f'<polyline points="{x1},{y1} {mid},{y1} {mid},{y2} {x2},{y2}" fill="none" {trazo}/>')
            s.append(_er_texto(x1 + sentido * 13, y1 - 5, "N", 15, 700, "#44505f", "middle", True))
            s.append(_er_texto(x2 - sentido * 13, y2 - 5, "1", 15, 700, "#44505f", "middle", True))
        elif co_c == cd_c and abs(co_f - cd_f) == 1:
            arriba, abajo = (d, o) if co_f > cd_f else (o, d)
            x = pos[arriba][0] + 56
            y1, y2 = pos[arriba][1] + alto[arriba], pos[abajo][1]
            s.append(f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" {trazo}/>')
            y_n, y_1 = (y2 - 8, y1 + 20) if arriba == d else (y1 + 20, y2 - 8)
            s.append(_er_texto(x + 12, y_n, "N", 15, 700, "#44505f", "start", True))
            s.append(_er_texto(x + 12, y_1, "1", 15, 700, "#44505f", "start", True))
            rotulo = rel[4] if len(rel) > 4 else None
            ymed = (y1 + y2) / 2
            if rotulo:
                s.append(_er_texto(x + 16, ymed - 6, rotulo, 15, 600, "#44505f", "start", True))
                s.append(_er_texto(x + 16, ymed + 16, f"{o}.{co} → {d}.{cd}", 15, 400, "#44505f", "start", True))
            else:
                s.append(_er_texto(x + 16, ymed + 5, f"{co} → {cd}", 15, 400, "#44505f", "start", True))
        else:
            raise ValueError(f"Disposición no soportada para {o}->{d}")
    # tablas
    for t in tablas:
        n, g = t["nombre"], grupos[t["grupo"]]
        x, y = pos[n]
        h = alto[n]
        s.append(f'<rect x="{x}" y="{y}" width="{_ER_CAJA}" height="{h}" rx="7" fill="{g["fondo"]}" stroke="{g["color"]}" stroke-width="2"/>')
        s.append(f'<path d="M{x},{y + _ER_CAB} V{y + 7} Q{x},{y} {x + 7},{y} H{x + _ER_CAJA - 7} Q{x + _ER_CAJA},{y} {x + _ER_CAJA},{y + 7} V{y + _ER_CAB} Z" fill="{g["color"]}"/>')
        s.append(_er_texto(x + 10, y + 26, n, 18 if len(n) <= 22 else 16, 700, "#fff"))
        s.append(_er_texto(x + _ER_CAJA - 10, y + 26, t["filas"], 14, 400, "#fff", "end"))
        for i, (nombre, tipo, pk, fk) in enumerate(t["columnas"]):
            yy = y + _ER_CAB + i * _ER_FILA
            if pk:
                s.append(f'<rect x="{x + 6}" y="{yy + 5.5}" width="27" height="17" rx="3" fill="{g["color"]}"/>')
                s.append(_er_texto(x + 19.5, yy + 18.5, "PK", 13, 700, "#fff", "middle"))
            if fk:
                s.append(f'<rect x="{x + 37}" y="{yy + 5.5}" width="27" height="17" rx="3" fill="#fff" stroke="{g["color"]}" stroke-width="1.5"/>')
                s.append(_er_texto(x + 50.5, yy + 18.5, "FK", 13, 700, g["color"], "middle"))
            s.append(_er_texto(x + 70, yy + 19.5, nombre, 15, 600 if pk else 400))
            s.append(_er_texto(x + _ER_CAJA - 10, yy + 19.5, tipo, 14, 400, "#5b6676", "end"))
    # leyenda
    lx, ly = _ER_MARGEN + 4 * (_ER_CAJA + gap_x), y_fila[2]
    s.append(f'<rect x="{lx}" y="{ly}" width="{_ER_CAJA}" height="{filas_max[2]}" rx="7" fill="#fff" stroke="#9aa5b4" stroke-width="1.5"/>')
    s.append(_er_texto(lx + 12, ly + 26, "Leyenda", 17, 700))
    for i, g in enumerate(grupos.values()):
        yy = ly + 38 + i * 22
        s.append(f'<rect x="{lx + 12}" y="{yy}" width="16" height="16" rx="3" fill="{g["color"]}"/>')
        s.append(_er_texto(lx + 36, yy + 13, g["etiqueta"], 14))
    yy = ly + 38 + len(grupos) * 22 + 10
    s.append(f'<rect x="{lx + 12}" y="{yy}" width="27" height="17" rx="3" fill="#5b6676"/>')
    s.append(_er_texto(lx + 25.5, yy + 13, "PK", 13, 700, "#fff", "middle"))
    s.append(_er_texto(lx + 48, yy + 13, "clave primaria", 14))
    s.append(f'<rect x="{lx + 168}" y="{yy}" width="27" height="17" rx="3" fill="#fff" stroke="#5b6676" stroke-width="1.5"/>')
    s.append(_er_texto(lx + 181.5, yy + 13, "FK", 13, 700, "#5b6676", "middle"))
    s.append(_er_texto(lx + 204, yy + 13, "clave foránea", 14))
    yy += 28
    s.append(f'<line x1="{lx + 12}" y1="{yy + 6}" x2="{lx + 52}" y2="{yy + 6}" stroke="#44505f" stroke-width="2.2"/>')
    s.append(_er_texto(lx + 60, yy + 11, "FK: N (origen) a 1 (destino)", 14))
    yy += 24
    s.append(f'<line x1="{lx + 12}" y1="{yy + 6}" x2="{lx + 52}" y2="{yy + 6}" stroke="#44505f" stroke-width="2.2" stroke-dasharray="8 6"/>')
    s.append(_er_texto(lx + 60, yy + 11, "relación lógica (sin FK)", 14))
    cuerpo = (f'<div class="panel" style="width:{_ER_ANCHO}px;height:{_ER_ALTO}px;border:none;border-radius:0">'
              f'<svg width="{_ER_ANCHO}" height="{_ER_ALTO}" viewBox="0 0 {_ER_ANCHO} {_ER_ALTO}" role="img" '
              f'aria-label="{html.escape(titulo)}"><rect width="100%" height="100%" fill="#fff"/>{"".join(s)}</svg></div>')
    return _pagina(titulo, cuerpo)
