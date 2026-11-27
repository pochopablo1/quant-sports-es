"""Tests offline de la matemática de los 4 dry-runs (no usan red)."""
import pytest

from comun.registro import Registro
from comun.seguimiento import Seguidor
from comun.utiles import vwap
from c14_usdt_ars.logica import cruces as cruces_c14
from c15_mep_bonos.logica import ciclo, costo_ciclo, costo_pata, cruces as cruces_c15
from c15_mep_bonos.iol import _puntas
from c8_hypercore_evm.logica import brecha_core_a_evm, brecha_evm_a_core, excluir_top, niveles_l2
from c1_rescate.logica import neto_directo, neto_liquity, precio_marginal
import reporte


def test_vwap_recorre_niveles():
    # 100 USD en un libro con 50 USD a 1.0 y el resto a 2.0
    p, q = vwap([(1.0, 50), (2.0, 100)], 100)
    assert q == pytest.approx(50 + 25)
    assert p == pytest.approx(100 / 75)
    assert vwap([(1.0, 10)], 100) is None


# ─── C14 ───
CFG_EX = {"a": {"taker": 0.001, "api_trading": True}, "b": {"taker": 0.001, "api_trading": True},
          "app": {"taker": 0.01, "api_trading": False}}


def test_c14_detecta_cruce_y_descuenta_comisiones():
    libros = {"a": {"asks": [(1500, 1000)], "bids": [(1499, 1000)]},
              "b": {"asks": [(1480, 1000)], "bids": [(1479, 1000)]}}
    ops = cruces_c14(libros, CFG_EX, [50.0], 0.001, 0.01, 0.5)
    assert len(ops) == 1
    o = ops[0]
    assert o["direccion"] == "b->a" and o["con_api"]
    costo = 1480 * 50 * 1.001
    cobro = 1499 * 50 * 0.999 * 0.999
    assert o["neto_pct"] == pytest.approx((cobro - costo - 0.005 * 1489.5) / costo)


def test_c14_sin_cruce_si_la_brecha_no_paga_comisiones():
    libros = {"a": {"asks": [(1500, 1000)], "bids": [(1499, 1000)]},
              "b": {"asks": [(1498, 1000)], "bids": [(1497, 1000)]}}
    assert cruces_c14(libros, CFG_EX, [50.0], 0.001, 0.01, 0.5) == []


def test_c14_marca_exchange_sin_api():
    libros = {"a": {"asks": [(1500, 1000)], "bids": [(1499, 1000)]},
              "app": {"por_monto": {50.0: (1400, 1390)}}}
    ops = cruces_c14(libros, CFG_EX, [50.0], 0.0, 0.0, 0.0)
    assert ops and not ops[0]["con_api"]


# ─── C15 ───
def test_c15_ciclo_sin_costos_es_cociente_de_meps():
    px = {"X": {"bid": 0, "bid_q": 0, "ask": 1000, "ask_q": 1e6}, "XD": {"bid": 1.0, "bid_q": 1e6, "ask": 0, "ask_q": 0},
          "Y": {"bid": 1010, "bid_q": 1e6, "ask": 0, "ask_q": 0}, "YD": {"bid": 0, "bid_q": 0, "ask": 1.0, "ask_q": 1e6}}
    r = ciclo(px, "X", "Y", 0.0, 0.0, 0.0, 100)
    assert r["neto_pct"] == pytest.approx(0.01)
    assert r["tam_usd"] == 100


def test_c15_costos_y_compuerta():
    c = costo_pata(0.001, 0.0001, 0.21)
    assert c == pytest.approx(0.001331)
    assert costo_ciclo(c) == pytest.approx(0.00531, rel=1e-2)   # > 0,4%: muere en la compuerta
    assert costo_ciclo(costo_pata(0.0, 0.0001, 0.21)) < 0.004


def test_c15_filtra_profundidad():
    px = {"X": {"bid": 0, "bid_q": 0, "ask": 1000, "ask_q": 1}, "XD": {"bid": 1.0, "bid_q": 1e6, "ask": 0, "ask_q": 0},
          "Y": {"bid": 1010, "bid_q": 1e6, "ask": 0, "ask_q": 0}, "YD": {"bid": 0, "bid_q": 0, "ask": 1.0, "ask_q": 1e6}}
    assert cruces_c15(px, ["X", "Y"], 0.0, 0.0, 0.0, 100, 50) == []   # 1 VN de X no alcanza


def test_iol_puntas():
    j = {"puntas": [{"cantidadCompra": 100, "precioCompra": 990, "precioVenta": 995, "cantidadVenta": 200}]}
    assert _puntas(j) == {"bid": 990, "bid_q": 100, "ask": 995, "ask_q": 200}
    assert _puntas({"puntas": []}) is None


# ─── C8 ───
def test_c8_brechas():
    libro = {"levels": [[{"px": "0.99", "sz": "1000", "n": 1}], [{"px": "1.00", "sz": "1000", "n": 1}]]}
    bids, asks = niveles_l2(libro)
    r = brecha_core_a_evm(asks, 50, 0.0, lambda t: t * 1.02)      # el AMM paga 1,02
    assert r["bruto_usd"] == pytest.approx(1.0)
    r = brecha_evm_a_core(bids, 50, 0.0, lambda usd: usd / 0.97)  # el AMM vende a 0,97
    assert r["bruto_usd"] == pytest.approx(50 / 0.97 * 0.99 - 50)
    assert excluir_top({"A": 5, "B": 9, "C": 1}, 1) == {"B"}


# ─── C1 ───
def test_c1_netos():
    # compro 50 USD → 50,6 feUSD (precio ~0,988); canje 0,5%; venta de garantía 0,3%; gas 0,10
    assert neto_liquity(50, 50.6, 0.005, 0.003, 0.10) == pytest.approx(50.6 * 0.995 * 0.997 - 50 - 0.10)
    assert neto_directo(50, 50.4, 0.1) == pytest.approx(0.3)
    assert precio_marginal(1.0101) == pytest.approx(0.99, rel=1e-3)


# ─── Seguimiento y reporte ───
def test_seguidor_cuenta_una_vez_tras_duracion(tmp_path):
    reg = Registro("test", tmp_path / "t.db")
    seg = Seguidor(reg, min_duracion_s=60, min_neto_pct=0.004)
    op = {"neto_usd": 0.5, "neto_pct": 0.01, "tam_usd": 50, "grupo": "a-b", "direccion": "a->b"}
    seg.observar(0, {"k": op})
    seg.observar(30, {"k": op})
    seg.observar(60, {"k": dict(op, neto_usd=0.4)})
    seg.observar(90, {"k": op})
    seg.observar(120, {})                        # desaparece: se cierra
    seg.observar(130, {"fugaz": op})             # dura 0 s
    seg.cerrar_todo()
    filas = reg.con.execute("SELECT clave, contada, neto_usd, duracion_s FROM oportunidades ORDER BY clave").fetchall()
    assert filas == [("fugaz", 0, None, 0.0), ("k", 1, 0.4, 90.0)]


def test_reporte_veredicto(tmp_path):
    ruta = tmp_path / "r.db"
    reg = Registro("x", ruta)
    import time
    t = time.time()
    reg.con.execute("INSERT INTO latidos VALUES (?,?,?,?)", (t - 72 * 3600, "x", 1, ""))
    reg.con.execute("INSERT INTO latidos VALUES (?,?,?,?)", (t, "x", 1, ""))
    for i in range(30):  # 30 × US$0,25 = US$7,5 en 3 días = US$2,5/día, mitad en cada dirección
        d = "a->b" if i % 2 else "b->a"
        reg.oportunidad({"clave": f"k{i}", "grupo": "a-b", "direccion": d, "inicio": t - i * 3600,
                         "fin": t - i * 3600 + 90, "neto_usd": 0.25, "neto_pct": 0.005, "contada": True})
    texto, pasa = reporte.analizar("x", {"meta_usd_dia": 2.0, "min_share_direccion": 0.3}, ruta)
    assert pasa, texto
    texto, pasa = reporte.analizar("x", {"meta_usd_dia": 3.0}, ruta)
    assert not pasa


def test_mejores_no_cuenta_tres_veces():
    from comun.seguimiento import mejores
    ops = [{"clave": "b->a", "neto_usd": 0.1}, {"clave": "b->a", "neto_usd": 0.3}, {"clave": "a->b", "neto_usd": 0.2}]
    m = mejores(ops)
    assert len(m) == 2 and m["b->a"]["neto_usd"] == 0.3
