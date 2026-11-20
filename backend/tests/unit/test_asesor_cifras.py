"""Guardrail de cifras: las acciones solo pueden citar numeros presentes en el contexto analitico. Datos sinteticos."""
import json

import pytest

from app.adapters.outbound.llm.mock_advisor import MockAdvisor
from app.application.asesor import PlanRechazado, ServicioAsesor, aplicar_guardrails
from app.domain.plan_accion import Accion, PlanBase

CTX = {
    "fecha_hoy": "2026-12-01",
    "kpis_30d": {"total_ventas": 1234567.0, "n_ventas": 300, "ticket_promedio": 4115.22, "margen_pct": 53.9,
                 "margen": 665432.1},
    "demanda_7d": [{"producto": "Cafe", "stock": 10, "total_predicho": 40.0}],
    "reglas_venta_cruzada": [{"antecedent": "Cafe", "consequent": "Pan", "support": 0.1234, "confidence": 0.55,
                              "lift": 2.0}],
    "festivos_proximos_co": [{"fecha": "2026-12-25", "nombre": "Navidad", "en_dias": 24}],
}


def accion(*datos, **kw):
    base = dict(accion="Reponer cafe", justificacion="La demanda supera el stock", impacto_estimado="Evita quiebres",
                riesgo="bajo", datos_citados=list(datos))
    base.update(kw)
    return Accion(**base)


def plan(*acciones, advertencias=()):
    return PlanBase(resumen="Resumen del plan", acciones=list(acciones), advertencias=list(advertencias))


def _pasa(*datos, contexto=CTX):
    return len(aplicar_guardrails(plan(accion(*datos)), contexto).acciones) == 1


def _rechazada(*datos, contexto=CTX):
    with pytest.raises(PlanRechazado) as e:
        aplicar_guardrails(plan(accion(*datos)), contexto)
    return str(e.value)


# ---- Cifras reales: pasan
@pytest.mark.parametrize("dato", [
    "Ventas de $1.234.567 en el mes",                 # es-CO con puntos de miles
    "Ventas de $1,234,567 en el mes",                 # en-US con comas de miles
    "Margen de 53,9% sobre ventas",                   # coma decimal es-CO
    "Margen de 53.9% sobre ventas",                   # punto decimal
    "Ticket promedio de $4.115",                      # redondeo a entero (4115.22)
    "Ticket promedio de $4.115,22",                   # es-CO completo
    "Ventas por 1,2 millones",                        # 1,2 millones ~ 1.234.567
    "Ventas por 1,23 millones",
    "Margen de 665 mil pesos",                        # "mil" ~ 665.432
    "Soporte de 12,3% en la regla Cafe + Pan",        # proporcion 0.1234 expresada en %
    "Confianza del 55%",                              # proporcion 0.55 expresada en %
    "Lift de 2",                                      # 2.0
    "Cafe: demanda 40 u. vs stock 10 u.",             # valores del contexto
    "Navidad 2026-12-25 (en 24 dias)",                # fecha del contexto y dias que faltan
    "300 ventas en 30 dias",                          # ventana de 30 d
    "Demanda a 7 d, festivos a 60 d, historico 365 d",   # ventanas permitidas
    "El cafe tiene la mayor demanda",                 # sin cifras
])
def test_cifra_real_en_cualquier_formato_pasa(dato):
    assert _pasa(dato)


def test_redondeo_de_miles_y_decimales_respeta_su_tolerancia():
    assert _pasa("Margen de 665.432 pesos")           # 665432.1 redondeado a entero
    assert _pasa("Margen de 665.432,1 pesos")         # exacto
    assert _pasa("Ticket de 4115,2")                  # 4115.22 con un decimal (tolerancia 0.05)


# ---- Cifras inventadas: se descartan
@pytest.mark.parametrize("dato", [
    "Ventas de $9.999.999 en el mes",
    "Margen de 77,7% sobre ventas",
    "301 ventas en el mes",                           # 300 real: fuera de tolerancia
    "Ticket promedio de $5.000",
    "Ventas por 2 millones",                          # 1,23 millones real: 2 millones queda fuera de tolerancia
    "Cafe: demanda 41 u.",
    "Navidad 2026-12-26",
    "Demanda a 14 d",                                 # 14 no es una ventana del contexto
    "Soporte de 20% en la regla Cafe + Pan",          # proporcion real 12,34%
])
def test_cifra_inventada_se_descarta_y_se_nombra_en_la_advertencia(dato):
    msg = _rechazada(dato)
    assert "cifras que no están en los datos analíticos" in msg


def test_la_advertencia_lista_la_cifra_inventada():
    r = aplicar_guardrails(plan(accion("Ventas de $1.234.567"),
                                accion("Meta de 4321 ventas", accion="Abrir otro local")), CTX)
    assert len(r.acciones) == 1 and r.acciones[0].datos_citados == ["Ventas de $1.234.567"]
    assert len(r.advertencias) == 1 and "(4321)" in r.advertencias[0] and "Abrir otro local" in r.advertencias[0]


def test_una_cifra_real_y_otra_inventada_en_el_mismo_dato_se_descarta():
    assert "999" in _rechazada("Ventas de $1.234.567 y 999 clientes nuevos")


def test_una_cifra_inventada_en_cualquiera_de_los_datos_citados_descarta_la_accion():
    assert "888" in _rechazada("Ventas de $1.234.567", "Cafe: stock 10 u.", "Bajaron 888 unidades")


def test_las_cifras_de_justificacion_no_se_verifican_solo_datos_citados():
    # contrato: el guardrail audita `datos_citados`; el texto libre de la justificacion no se valida
    r = aplicar_guardrails(plan(accion("Ventas de $1.234.567", justificacion="Podria vender 5000 unidades")), CTX)
    assert len(r.acciones) == 1


def test_mezcla_conserva_las_buenas_en_orden_y_las_malas_dejan_advertencia():
    buena1, mala, buena2 = accion("300 ventas en 30 dias"), accion("Margen de 11,1%"), accion("Stock de 10 u.")
    r = aplicar_guardrails(plan(buena1, mala, buena2, advertencias=["previa"]), CTX)
    assert [a.datos_citados[0] for a in r.acciones] == ["300 ventas en 30 dias", "Stock de 10 u."]
    assert r.advertencias[0] == "previa" and len(r.advertencias) == 2 and "11,1" in r.advertencias[1]


def test_todas_con_cifras_inventadas_lanza_plan_rechazado():
    with pytest.raises(PlanRechazado) as e:
        aplicar_guardrails(plan(accion("Meta 4321"), accion("Meta 8765")), CTX)
    assert "4321" in str(e.value) and "8765" in str(e.value)


# ---- contexto = None: comportamiento previo (no se verifican cifras)
def test_sin_contexto_no_se_verifican_cifras():
    r = aplicar_guardrails(plan(accion("Cifra inventada 99999999")))
    assert len(r.acciones) == 1 and not r.advertencias
    assert len(aplicar_guardrails(plan(accion("Cifra 99999999")), None).acciones) == 1


def test_sin_contexto_siguen_aplicando_los_otros_guardrails():
    with pytest.raises(PlanRechazado):
        aplicar_guardrails(plan(accion("dato", descuento_pct=60)), None)
    with pytest.raises(PlanRechazado):
        aplicar_guardrails(plan(accion()), None)                    # sin datos citados


def test_con_contexto_siguen_aplicando_descuento_y_datos_vacios():
    r = aplicar_guardrails(plan(accion("300 ventas"), accion("300 ventas", descuento_pct=40), accion()), CTX)
    assert len(r.acciones) == 1 and len(r.advertencias) == 2


def test_contexto_vacio_solo_admite_las_ventanas():
    assert _pasa("Ventana de 30 dias", contexto={})
    assert "(5)" in _rechazada("5 ventas", contexto={})


def test_las_claves_y_las_longitudes_de_listas_del_contexto_cuentan_como_cifras():
    ctx = {"top": [{"n": 1}, {"n": 2}, {"n": 3}], "texto": "Hay 12 clientes en riesgo"}
    assert _pasa("Los 3 primeros productos", contexto=ctx)      # largo de la lista
    assert _pasa("12 clientes en riesgo", contexto=ctx)         # numero dentro de un texto del contexto


# ---- ServicioAsesor.preguntar pasa el contexto y cae al simulado
class _Analitica:
    def metricas(self):
        return {"disponible": False, "mae": None, "r2": None, "silhouette": None, "k": None, "n_reglas": None}


class _Kpis:
    def resumen(self, dias=30, top=5, ahora=None):
        return {"total_ventas": 1000.0, "n_ventas": 5, "ticket_promedio": 200.0, "margen": 400.0,
                "margen_pct": 40.0, "rotacion": 1.0, "valor_inventario": 100.0, "productos_bajo_stock": 1,
                "top_productos": [], "ventas_por_categoria": [], "serie_diaria": []}


class _Falso:
    modo = "gemini"

    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)

    def generar(self, pregunta, contexto, error_previo=None):
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return json.dumps({"resumen": "Resumen del plan", "acciones": [a.model_dump() for a in r],
                           "advertencias": []})


def _svc(asesor):
    return ServicioAsesor(asesor, MockAdvisor(), _Analitica(), _Kpis())


def test_preguntar_acepta_cifras_del_contexto_real_del_servicio():
    r = _svc(_Falso([accion("5 ventas por $1.000 en 30 dias")])).preguntar("hola")
    assert r.modo == "gemini" and len(r.acciones) == 1


def test_preguntar_con_cifra_inventada_cae_al_simulado_con_advertencia():
    r = _svc(_Falso([accion("4321 ventas por $1.000")])).preguntar("hola")  # n_ventas real = 5
    assert r.modo == "simulado"
    assert any("cifras" in w and "4321" in w for w in r.advertencias)
    assert any("se usó el asesor simulado" in w for w in r.advertencias)
    assert r.acciones and all(a.datos_citados for a in r.acciones)


def test_preguntar_conserva_las_buenas_y_avisa_de_las_descartadas():
    r = _svc(_Falso([accion("5 ventas"), accion("Margen de 97%")])).preguntar("hola")
    assert r.modo == "gemini" and len(r.acciones) == 1
    assert len(r.advertencias) == 1 and "97" in r.advertencias[0]


def test_preguntar_error_del_proveedor_usa_el_simulado_y_este_pasa_el_guardrail():
    r = _svc(_Falso(RuntimeError("503 caido"))).preguntar("hola")
    assert r.modo == "simulado" and any("503" in w for w in r.advertencias)
    assert r.acciones

