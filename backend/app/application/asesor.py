"""Asesor estratégico: contexto analítico + guardrails (red teaming) + reintento sobre el contrato PlanAccion."""
import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import holidays
from pydantic import ValidationError

from app.application.analitica import ServicioAnalitica
from app.application.kpis import ServicioKpis
from app.domain.errors import ErrorDominio, ValidacionError
from app.domain.plan_accion import PlanAccion, PlanBase
from app.domain.ports import AdvisorPort

MAX_DESCUENTO_PCT = 30.0
_PALABRAS_DESCUENTO = re.compile(r"descuent|rebaj|promoci|\bdto\b|oferta|liquidaci", re.I)
_PORCENTAJE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_NUMERO = re.compile(r"(\d+(?:[.,]\d+)*)(?:\s*(millones|mill[oó]n|mil)\b)?", re.I)
# Ventanas de tiempo del contexto (7 d de demanda, 30 d de KPIs, 60 d de festivos, 365 d de estacionalidad).
_VENTANAS = (7, 30, 60, 365)


class PlanRechazado(ErrorDominio):
    """Todas las acciones del plan violaron algún guardrail."""


def _descuento_en_texto(texto: str) -> float:
    """Mayor porcentaje de descuento mencionado en el texto (0 si ninguno)."""
    mayor = 0.0
    for frase in re.split(r"[.;\n]", texto):
        if _PALABRAS_DESCUENTO.search(frase):
            for p in _PORCENTAJE.findall(frase):
                mayor = max(mayor, float(p.replace(",", ".")))
    return mayor


def _valores_numero(token: str) -> list[tuple[float, int]]:
    """Interpretaciones (valor, decimales) de un número en formato es-CO ($1.234.567, 53,9) o en-US."""
    if "." in token and "," in token:
        dec = max(token.rfind("."), token.rfind(","))
        return [(float(token[:dec].replace(".", "").replace(",", "") + "." + token[dec + 1:]), len(token) - dec - 1)]
    sep = "." if "." in token else "," if "," in token else None
    if sep is None:
        return [(float(token), 0)]
    partes = token.split(sep)
    if len(partes) > 2:
        return [(float("".join(partes)), 0)]
    opciones = [(float(partes[0] + "." + partes[1]), len(partes[1]))]
    if len(partes[1]) == 3:  # 1.234 puede ser mil doscientos treinta y cuatro
        opciones.append((float("".join(partes)), 0))
    return opciones


def _numeros_de(valor: Any, acumulado: set[float]) -> None:
    """Recoge todas las cifras del contexto (números, largos de listas y números dentro de textos)."""
    if isinstance(valor, bool) or valor is None:
        return
    if isinstance(valor, (int, float)):
        acumulado.add(abs(float(valor)))
    elif isinstance(valor, str):
        for m in _NUMERO.finditer(valor):
            acumulado.update(v for v, _ in _valores_numero(m.group(1)))
    elif isinstance(valor, dict):
        for k, v in valor.items():
            _numeros_de(k, acumulado)
            _numeros_de(v, acumulado)
    elif isinstance(valor, (list, tuple)):
        acumulado.add(float(len(valor)))
        for v in valor:
            _numeros_de(v, acumulado)


def _cifras_inexistentes(dato: str, existentes: set[float]) -> list[str]:
    """Cifras citadas que no aparecen en el contexto (tolera redondeos y proporciones expresadas en %)."""
    faltan = []
    for m in _NUMERO.finditer(dato):
        escala = {"mil": 1e3}.get((m.group(2) or "").lower(), 1e6 if m.group(2) else 1.0)
        for valor, dec in _valores_numero(m.group(1)):
            citado, tol = valor * escala, 0.5 * 10 ** -dec * escala
            if any(abs(citado - x) <= tol or (x <= 1 and abs(citado - x * 100) <= tol) for x in existentes):
                break
        else:
            faltan.append(m.group(1))
    return faltan


def aplicar_guardrails(plan: PlanBase, contexto: dict[str, Any] | None = None) -> PlanBase:
    """Descarta acciones con descuento > 30%, sin datos citados o que citen cifras ausentes del contexto.

    Falla si no queda ninguna. Sin `contexto` no se verifican las cifras.
    """
    validas, advertencias = [], list(plan.advertencias)
    existentes: set[float] = set(map(float, _VENTANAS))
    if contexto is not None:
        _numeros_de(contexto, existentes)
    for a in plan.acciones:
        citados = [d for d in a.datos_citados if d and d.strip()]
        if not citados:
            advertencias.append(f"Acción descartada por no citar datos analíticos: «{a.accion[:80]}»")
            continue
        inventadas = [c for d in citados if contexto is not None for c in _cifras_inexistentes(d, existentes)]
        if inventadas:
            advertencias.append(f"Acción descartada por citar cifras que no están en los datos analíticos "
                                f"({', '.join(inventadas)}): «{a.accion[:80]}»")
            continue
        descuento = max(a.descuento_pct or 0.0, _descuento_en_texto(f"{a.accion}. {a.justificacion}"))
        if descuento > MAX_DESCUENTO_PCT:
            advertencias.append(f"Acción descartada: propone un descuento de {descuento:g}%, "
                                f"superior al máximo permitido de {MAX_DESCUENTO_PCT:g}%: «{a.accion[:80]}»")
            continue
        validas.append(a.model_copy(update={"datos_citados": citados}))
    if not validas:
        raise PlanRechazado("; ".join(advertencias) or "Plan sin acciones válidas")
    return PlanBase(resumen=plan.resumen, acciones=validas, advertencias=advertencias)


def proximos_festivos(hoy: date | None = None, dias: int = 60) -> list[dict[str, Any]]:
    hoy = hoy or date.today()
    fest = holidays.Colombia(years=[hoy.year, hoy.year + 1])
    return [{"fecha": str(d), "nombre": n, "en_dias": (d - hoy).days}
            for d, n in sorted(fest.items()) if 0 <= (d - hoy).days <= dias]


def estacionalidad(serie_diaria: list[dict[str, Any]], hoy: date | None = None) -> dict[str, Any]:
    """Factores (promedio / promedio global) por mes y por día de la semana a partir de la serie diaria."""
    hoy = hoy or date.today()
    if not serie_diaria:
        return {}
    por_mes, por_dow = defaultdict(list), defaultdict(list)
    for p in serie_diaria:
        d = date.fromisoformat(str(p["fecha"])[:10])
        por_mes[d.month].append(p["total"])
        por_dow[d.weekday()].append(p["total"])
    todos = [p["total"] for p in serie_diaria]
    glob = sum(todos) / len(todos) or 1.0
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    f_mes = {mes: round(sum(v) / len(v) / glob, 2) for mes, v in sorted(por_mes.items())}
    f_dow = {dias[k]: round(sum(v) / len(v) / glob, 2) for k, v in sorted(por_dow.items())}
    return {"factor_por_mes": f_mes, "factor_por_dia_semana": f_dow, "mes_actual": hoy.month,
            "factor_mes_actual": f_mes.get(hoy.month), "mes_pico": max(f_mes, key=f_mes.get),
            "dia_pico": max(f_dow, key=f_dow.get)}


def _limpiar_json(texto: str) -> str:
    t = texto.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    return t


class ServicioAsesor:
    def __init__(self, advisor: AdvisorPort, respaldo: AdvisorPort, analitica: ServicioAnalitica,
                 kpis: ServicioKpis):
        self.advisor, self.respaldo, self.analitica, self.kpis = advisor, respaldo, analitica, kpis

    def construir_contexto(self, hoy: date | None = None) -> dict[str, Any]:
        hoy = hoy or date.today()
        metricas = self.analitica.metricas()
        k30 = self.kpis.resumen(30, 5)
        k365 = self.kpis.resumen(365, 1)
        ctx: dict[str, Any] = {
            "fecha_hoy": str(hoy),
            "hay_datos_analiticos": bool(metricas["disponible"]),
            "kpis_30d": {k: k30[k] for k in ("total_ventas", "n_ventas", "ticket_promedio", "margen", "margen_pct",
                                              "rotacion", "valor_inventario", "productos_bajo_stock")},
            "top_productos_30d": k30["top_productos"],
            "ventas_por_categoria_30d": k30["ventas_por_categoria"],
            "festivos_proximos_co": proximos_festivos(hoy),
            "estacionalidad": estacionalidad(k365["serie_diaria"], hoy),
            "metricas_modelos": {k: metricas[k] for k in ("mae", "r2", "silhouette", "k", "n_reglas")},
        }
        if metricas["disponible"]:
            dem = self.analitica.demanda(7)
            ctx["demanda_7d"] = [{"producto": d["name"], "stock": d["stock"], "total_predicho": d["total_predicho"]}
                                 for d in dem[:15]]
            ctx["reglas_venta_cruzada"] = [{k: r[k] for k in ("antecedent", "consequent", "support", "confidence", "lift")}
                                           for r in self.analitica.reglas(8)]
            ctx["segmentos"] = self.analitica.segmentos()["resumen"]
        else:
            ctx.update(demanda_7d=[], reglas_venta_cruzada=[], segmentos=[])
        return ctx

    def _plan_desde(self, advisor: AdvisorPort, pregunta: str, ctx: dict) -> PlanBase:
        """Genera y valida el plan; reintenta UNA vez si el JSON no cumple el contrato."""
        error = None
        for _ in range(2):
            texto = advisor.generar(pregunta, ctx, error)
            try:
                return PlanBase.model_validate_json(_limpiar_json(texto))
            except (ValidationError, ValueError) as e:
                error = str(e)[:600]
        raise ValidacionError(f"El asesor no devolvió un JSON válido tras un reintento: {error}")

    def preguntar(self, pregunta: str) -> PlanAccion:
        pregunta = pregunta.strip()
        if not pregunta:
            raise ValidacionError("La pregunta no puede estar vacía")
        ctx = self.construir_contexto()
        modo, extra = self.advisor.modo, []
        try:
            plan = aplicar_guardrails(self._plan_desde(self.advisor, pregunta, ctx), ctx)
        except Exception as e:  # JSON inválido, guardrails o falla del proveedor -> respaldo determinístico
            extra.append(f"El asesor principal no produjo un plan válido ({str(e)[:200]}); "
                         f"se usó el asesor simulado.")
            plan = aplicar_guardrails(self._plan_desde(self.respaldo, pregunta, ctx), ctx)
            modo = self.respaldo.modo
        return PlanAccion(resumen=plan.resumen, acciones=plan.acciones,
                          advertencias=plan.advertencias + extra, modo=modo)
