"""
Suite de pruebas automatizadas (pytest) para validar:
- Devigging multiplicativo de Pinnacle
- Limpieza de texto y Fuzzy Matching en español
- Esquema obligatorio de 15 columnas en español
- Extractores en vivo
"""
from configuracion import COLUMNAS_ESQUEMA, calcular_overround_pct
from extractores.pinnacle import devig_multiplicativo
from extractores.polymarket import parsear_campo_json, extraer_polymarket
from normalizador.emparejador import limpiar_texto, similitud_equipos, emparejar_con_referencia


def test_devig_multiplicativo():
    p1, p2, c1_justa, c2_justa = devig_multiplicativo(1.909, 1.909)
    assert abs(p1 - 0.5) < 1e-4
    assert abs(p2 - 0.5) < 1e-4
    assert abs(c1_justa - 2.0) < 1e-2
    assert abs(c2_justa - 2.0) < 1e-2


def test_parseo_json_embebido_polymarket():
    cadena = '["0.62", "0.38"]'
    resultado = parsear_campo_json(cadena)
    assert resultado == ["0.62", "0.38"]


def test_fuzzy_matching_equipos():
    sim = similitud_equipos("Real Madrid CF", "Real Madrid")
    assert sim >= 90.0

    sim_2 = similitud_equipos("Atlético de Madrid", "Atletico Madrid")
    assert sim_2 >= 85.0


def test_emparejamiento_con_referencia_invertida():
    mercado_obj = {
        "Evento": "Barcelona vs Real Madrid",
        "Lado_1": "FC Barcelona",
        "Lado_2": "Real Madrid CF",
    }
    referencias = [
        {
            "Evento": "Real Madrid vs Barcelona",
            "Lado_1": "Real Madrid",
            "Lado_2": "Barcelona",
            "Cuota_Taker_1": 2.10,
            "Cuota_Taker_2": 1.85,
        }
    ]
    ref, invertido, puntaje = emparejar_con_referencia(mercado_obj, referencias)
    assert ref is not None
    assert invertido is True
    assert puntaje >= 85.0


def test_extractor_polymarket_esquema():
    datos = extraer_polymarket(limite=10)
    assert isinstance(datos, list)
    if datos:
        primera = datos[0]
        for col in COLUMNAS_ESQUEMA:
            assert col in primera
        assert primera["Cuota_Taker_1"] > 1.0
        assert primera["Cuota_Taker_2"] > 1.0
