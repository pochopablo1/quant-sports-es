"""
Gestor Seguro de Billetera Web3 ("Burner Bot Wallet") y Firmador EIP-712 para Polymarket / Base / Polygon.
Reglas de Seguridad Innegociables:
1. JAMÁS imprime ni registra la clave privada (`BOT_WALLET_PRIVATE_KEY`) en consola, logs ni Telegram.
2. Si se ejecuta con `--crear-wallet`, genera una billetera EVM 100% nueva y aislada, guarda la clave
   únicamente dentro del archivo local `.env` (protegido por `.gitignore`) y muestra solo la dirección pública `0x...`.
3. Incluye verificador de saldos On-Chain en vivo (USDC.e, USDC y gas en Polygon y Base L2) sin gastar gas.
4. Incluye un interruptor de seguridad (`EJECUCION_REAL_HABILITADA=false` por defecto) para que ninguna orden
   real salga al mercado hasta que el usuario lo active explícitamente.
"""
import argparse
import logging
import os
from pathlib import Path
import secrets
import sys
from typing import Dict, Any, Tuple
from dotenv import load_dotenv, set_key
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from configuracion import RUTA_BASE

logger = logging.getLogger("GestorWalletWeb3")
RUTA_ENV = RUTA_BASE / ".env"

# RPCs públicos gratuitos (Polygon para Polymarket/Azuro y Base para Limitless)
RPC_POLYGON = "https://polygon-bor-rpc.publicnode.com"
RPC_BASE = "https://mainnet.base.org"

# Contratos oficiales de USDC y pUSD (6 decimales)
CONTRATO_PUSD_POLYGON = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"   # Colateral oficial Polymarket V2 (pUSD)
CONTRATO_USDCE_POLYGON = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # USDC.e en Polygon (Wrappeable 1:1 a pUSD)
CONTRATO_USDC_NATIVO_POLYGON = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
CONTRATO_USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"      # Colateral oficial de Limitless Exchange

# Contratos oficiales en Polygon para Swap 1:1 (Uniswap V3), Wrapper 1:1 pUSD y Polymarket CLOB
UNISWAP_V3_ROUTER_POLYGON = "0xE592427A0AEce92De3Edee1F18E0157C05861564"
POLY_PUSD_WRAPPER = "0x93070a847efef7f70739046a929d47a521f5b8ee"
POLY_CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
POLY_NEG_RISK_EXCHANGE = "0xC5d563A36AE78145C45a50134d48A1215220f80a"
POLY_NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
POLY_CONDITIONAL_TOKENS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

_CACHE_PROXIES_POLY: list[str] = []


def _obtener_proxies_polymarket_verificados() -> list[str]:
    """
    Obtiene y cachea proxies HTTPS verificados contra `https://polymarket.com/api/geoblock` (`blocked == False`)
    para sortear el bloqueo regional de IP (Argentina / EE.UU. en PythonAnywhere) únicamente en el POST final
    de la orden ya firmada localmente con EIP-712.
    """
    global _CACHE_PROXIES_POLY
    proxy_env = os.getenv("POLYMARKET_PROXY", "").strip()
    if proxy_env:
        return [proxy_env]
    if _CACHE_PROXIES_POLY:
        return _CACHE_PROXIES_POLY

    from concurrent.futures import ThreadPoolExecutor
    import httpx

    try:
        # Primero verificar si la IP actual ya está permitida sin proxy
        g_directo = requests.get("https://polymarket.com/api/geoblock", timeout=4).json()
        if g_directo.get("blocked") is False:
            return []
    except Exception:
        pass

    try:
        resp = requests.get(
            "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&proxy_format=protocolipport&format=json&timeout=3000",
            timeout=8,
        ).json()
        paises_bloqueados = {"US", "AR", "FR", "GB", "DE", "IT", "AU", "SG", "PL", "BE", "TH", "TW"}
        candidatos = [
            p["proxy"]
            for p in resp.get("proxies", [])
            if p.get("ssl") and p.get("ip_data", {}).get("countryCode") not in paises_bloqueados
        ]
    except Exception:
        candidatos = []

    def _probar(pr: str) -> str | None:
        try:
            with httpx.Client(proxy=pr, timeout=5.0) as c:
                g = c.get("https://polymarket.com/api/geoblock").json()
                if g.get("blocked") is False:
                    return pr
        except Exception:
            pass
        return None

    if candidatos:
        with ThreadPoolExecutor(max_workers=25) as ex:
            validos = [x for x in ex.map(_probar, candidatos[:75]) if x]
        if validos:
            _CACHE_PROXIES_POLY = validos[:8]
    return _CACHE_PROXIES_POLY


def _consultar_erc20_balance(rpc_url: str, contrato: str, direccion: str, decimales: int = 6) -> float:
    """Consulta `balanceOf(address)` vía JSON-RPC `eth_call` sin necesitar librerías pesadas."""
    addr_limpia = direccion.lower().replace("0x", "").zfill(64)
    data = "0x70a08231" + addr_limpia
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": contrato, "data": data}, "latest"],
    }
    try:
        resp = requests.post(rpc_url, json=payload, timeout=8)
        res_hex = resp.json().get("result", "0x0")
        if not res_hex or res_hex == "0x":
            return 0.0
        return round(int(res_hex, 16) / (10**decimales), 2)
    except Exception:
        return 0.0


def _consultar_balance_nativo(rpc_url: str, direccion: str) -> float:
    """Consulta el saldo de gas nativo (POL en Polygon / ETH en Base)."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getBalance",
        "params": [direccion, "latest"],
    }
    try:
        resp = requests.post(rpc_url, json=payload, timeout=8)
        res_hex = resp.json().get("result", "0x0")
        if not res_hex or res_hex == "0x":
            return 0.0
        return round(int(res_hex, 16) / (10**18), 5)
    except Exception:
        return 0.0


def obtener_o_crear_wallet_bot(crear_si_no_existe: bool = False) -> Tuple[str, bool]:
    """
    Lee `BOT_WALLET_ADDRESS` desde `.env`.
    Si no existe y `crear_si_no_existe=True`, genera un par criptográfico secp256k1 nuevo,
    guarda `BOT_WALLET_PRIVATE_KEY` y `BOT_WALLET_ADDRESS` en `.env` y devuelve `(direccion_publica, fue_creada)`.
    """
    load_dotenv(RUTA_ENV, override=True)
    priv_key = os.getenv("BOT_WALLET_PRIVATE_KEY", "").strip()
    pub_addr = os.getenv("BOT_WALLET_ADDRESS", "").strip()

    if priv_key and pub_addr:
        return pub_addr, False

    if not crear_si_no_existe:
        return "", False

    from eth_account import Account

    nueva_entropia = "0x" + secrets.token_hex(32)
    cuenta = Account.from_key(nueva_entropia)

    if not RUTA_ENV.exists():
        RUTA_ENV.write_text("", encoding="utf-8")

    set_key(str(RUTA_ENV), "BOT_WALLET_ADDRESS", cuenta.address)
    set_key(str(RUTA_ENV), "BOT_WALLET_PRIVATE_KEY", nueva_entropia)
    set_key(str(RUTA_ENV), "EJECUCION_REAL_HABILITADA", "false")

    return cuenta.address, True


def _obtener_deposit_wallet_polymarket(direccion_eoa: str) -> str:
    """Deriva la dirección determinista de la Deposit Wallet oficial de Polymarket V2 para el EOA."""
    try:
        from polymarket._internal.environment import get_environment_config
        from polymarket._internal.wallet import derive_beacon_deposit_wallet_address
        from polymarket.environments import PRODUCTION

        cfg = get_environment_config(PRODUCTION)
        return derive_beacon_deposit_wallet_address(direccion_eoa, cfg.wallet_derivation)
    except Exception:
        return ""


def verificar_estado_wallet() -> Dict[str, Any]:
    """Verifica la configuración de la billetera del bot y sus saldos en vivo en Polygon y Base."""
    load_dotenv(RUTA_ENV, override=True)
    direccion = os.getenv("BOT_WALLET_ADDRESS", "").strip()
    ejecucion_real = os.getenv("EJECUCION_REAL_HABILITADA", "false").lower() == "true"

    if not direccion:
        return {
            "configurada": False,
            "mensaje": "Aún no hay una billetera configurada en .env. Ejecuta con `--crear-wallet` para generar una.",
        }

    deposit_wallet = _obtener_deposit_wallet_polymarket(direccion)
    pusd_eoa = _consultar_erc20_balance(RPC_POLYGON, CONTRATO_PUSD_POLYGON, direccion)
    pusd_dw = _consultar_erc20_balance(RPC_POLYGON, CONTRATO_PUSD_POLYGON, deposit_wallet) if deposit_wallet else 0.0
    pusd_poly = round(pusd_eoa + pusd_dw, 2)

    usdce_poly = _consultar_erc20_balance(RPC_POLYGON, CONTRATO_USDCE_POLYGON, direccion)
    usdc_poly = _consultar_erc20_balance(RPC_POLYGON, CONTRATO_USDC_NATIVO_POLYGON, direccion)
    pol_gas = _consultar_balance_nativo(RPC_POLYGON, direccion)

    usdc_base = _consultar_erc20_balance(RPC_BASE, CONTRATO_USDC_BASE, direccion)
    eth_base_gas = _consultar_balance_nativo(RPC_BASE, direccion)

    total_usdc_operativo = round(pusd_poly + usdce_poly + usdc_poly + usdc_base, 2)

    return {
        "configurada": True,
        "direccion_publica": direccion,
        "deposit_wallet_polymarket": deposit_wallet,
        "modo_ejecucion": "REAL_HABILITADO" if ejecucion_real else "SIMULACION_SEGURA (Paper Trading)",
        "polygon_pusd_polymarket": pusd_poly,
        "polygon_usdce_polymarket": usdce_poly,
        "polygon_usdc_nativo": usdc_poly,
        "polygon_pol_gas": pol_gas,
        "base_usdc_limitless": usdc_base,
        "base_eth_gas": eth_base_gas,
        "total_usdc_disponible": total_usdc_operativo,
    }


def firmar_orden_polymarket_clob(
    token_id: str,
    precio: float,
    tamano_usd: float,
    lado: str = "BUY",
    tipo_orden: str = "FOK",
) -> Tuple[bool, str]:
    """
    Firma y envía una orden al CLOB de Polymarket V2 usando el SDK oficial `polymarket-client` (Deposit Wallet V2).
    - `lado`: "BUY" (compra de entrada) o "SELL" (venta Maker de salida).
    """
    load_dotenv(RUTA_ENV, override=True)
    ejecucion_real = os.getenv("EJECUCION_REAL_HABILITADA", "false").lower() == "true"
    priv_key = os.getenv("BOT_WALLET_PRIVATE_KEY", "").strip()
    pub_addr = os.getenv("BOT_WALLET_ADDRESS", "").strip()

    if not ejecucion_real:
        return (
            False,
            "Candado activo (`EJECUCION_REAL_HABILITADA=false` en .env). Orden procesada en modo Paper Trading.",
        )

    if not priv_key or not pub_addr:
        return False, "Falta `BOT_WALLET_PRIVATE_KEY` o `BOT_WALLET_ADDRESS` en .env."

    try:
        from decimal import Decimal
        import httpx
        from polymarket import SecureClient

        # Usar la Deposit Wallet oficial derivada del EOA (wallet=None)
        sc = SecureClient._create(private_key=priv_key, wallet=None)
        const_lado = "BUY" if lado.upper() == "BUY" else "SELL"

        # Redondear a 2 decimales estándar de tick grid (0.01) y calcular contratos (mínimo técnico: 5 shares)
        precio_limpio = round(float(precio), 2)
        contratos = max(5.0, round(float(tamano_usd) / precio_limpio, 2))

        orden_firmada = sc.create_limit_order(
            token_id=str(token_id),
            price=Decimal(f"{precio_limpio:.2f}"),
            size=Decimal(f"{contratos:.2f}"),
            side=const_lado,
        )

        # Enviar orden usando conexión directa o puente HTTPS anti-geobloqueo (AR / PythonAnywhere US)
        cliente_orig = sc._ctx.secure_clob._client
        base_url_clob = sc._ctx.secure_clob._base_url
        proxies_disp = _obtener_proxies_polymarket_verificados()
        ultimo_error = None

        lista_intentos = [None] if not proxies_disp else proxies_disp
        try:
            for pr_url in lista_intentos:
                try:
                    if pr_url:
                        sc._ctx.secure_clob._client = httpx.Client(
                            base_url=base_url_clob,
                            http2=True,
                            proxy=pr_url,
                            timeout=12.0,
                        )
                    respuesta = sc.post_order(orden_firmada)
                    return (
                        True,
                        f"Orden ejecutada en Polymarket V2 ({contratos} contratos @ ${precio_limpio:.2f} | ID: {respuesta.order_id} | Estado: {respuesta.status})",
                    )
                except Exception as e_post:
                    ultimo_error = e_post
                    if pr_url and pr_url in _CACHE_PROXIES_POLY:
                        _CACHE_PROXIES_POLY.remove(pr_url)
                finally:
                    sc._ctx.secure_clob._client = cliente_orig
        finally:
            sc.close()

        return False, f"Error enviando orden a Polymarket CLOB V2: {ultimo_error}"
    except Exception as exc:
        return False, f"Error firmando/enviando orden a Polymarket CLOB V2: {exc}"


def _rpc_call_polygon(method: str, params: list) -> Any:
    resp = requests.post(
        RPC_POLYGON,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=12,
    )
    datos = resp.json()
    if "error" in datos:
        raise RuntimeError(f"Error RPC Polygon ({method}): {datos['error']}")
    return datos.get("result")


def _enviar_tx_polygon_y_esperar(priv_key: str, to_addr: str, data_hex: str, gas_limit: int = 250000) -> str:
    """Firma y envía una transacción en Polygon esperando confirmación On-Chain."""
    import time
    from eth_account import Account
    from eth_utils.address import to_checksum_address

    cuenta = Account.from_key(priv_key)
    nonce = int(_rpc_call_polygon("eth_getTransactionCount", [cuenta.address, "pending"]), 16)
    gas_price = int(int(_rpc_call_polygon("eth_gasPrice", []), 16) * 1.35)

    tx = {
        "nonce": nonce,
        "to": to_checksum_address(to_addr),
        "value": 0,
        "gas": gas_limit,
        "gasPrice": gas_price,
        "data": data_hex,
        "chainId": 137,
    }
    firmada = Account.sign_transaction(tx, priv_key)
    raw_hex = "0x" + firmada.raw_transaction.hex()
    tx_hash = _rpc_call_polygon("eth_sendRawTransaction", [raw_hex])
    print(f"   ⏳ Transacción enviada a Polygon: {tx_hash} (esperando confirmación...)")

    for _ in range(35):
        time.sleep(2.5)
        try:
            recibo = _rpc_call_polygon("eth_getTransactionReceipt", [tx_hash])
        except Exception:
            recibo = None
        if recibo:
            status = int(recibo.get("status", "0x0"), 16)
            if status == 1:
                print(f"   ✅ Confirmada en bloque {int(recibo['blockNumber'], 16)}")
                return tx_hash
            raise RuntimeError(f"La transacción {tx_hash} falló On-Chain (status=0)")
    raise TimeoutError(f"Timeout esperando confirmación de {tx_hash}")


def preparar_wallet_polymarket_onchain() -> None:
    """
    1. Si hay USDC Nativo en Polygon, lo convierte 1:1 a USDC.e vía pool 0.01% de Uniswap V3.
    2. Si hay USDC.e en Polygon, lo envuelve 1:1 (0% comisión) a pUSD (Polymarket USD V2).
    3. Habilita (approve) todos los contratos oficiales de Polymarket V2 para operar sin fricción.
    """
    import time
    from eth_abi import encode
    from polymarket import SecureClient

    load_dotenv(RUTA_ENV, override=True)
    priv_key = os.getenv("BOT_WALLET_PRIVATE_KEY", "").strip()
    direccion = os.getenv("BOT_WALLET_ADDRESS", "").strip()
    if not priv_key or not direccion:
        print("❌ Faltan credenciales de billetera en .env")
        return

    print("\n" + "═" * 95)
    print("⚙️  PREPARACIÓN AUTOMÁTICA ON-CHAIN PARA POLYMARKET V2 (USDC -> USDC.e -> pUSD + Permisos)")
    print("═" * 95)

    # 1. Consultar saldo crudo (6 decimales) de USDC Nativo
    addr_pad = direccion.lower().replace("0x", "").zfill(64)
    res_hex = _rpc_call_polygon(
        "eth_call",
        [{"to": CONTRATO_USDC_NATIVO_POLYGON, "data": "0x70a08231" + addr_pad}, "latest"],
    )
    unidades_usdc_nativo = int(res_hex or "0x0", 16)

    if unidades_usdc_nativo >= 1_000_000:  # >= $1.00 USDC
        monto_usd = unidades_usdc_nativo / 1e6
        print(f"🔄 Paso A: Convirtiendo ${monto_usd:.2f} USDC Nativo -> USDC.e vía Uniswap V3 (0.01% fee)...")
        data_allow_uni = "0xdd62ed3e" + encode(["address", "address"], [direccion, UNISWAP_V3_ROUTER_POLYGON]).hex()
        allow_uni = int(_rpc_call_polygon("eth_call", [{"to": CONTRATO_USDC_NATIVO_POLYGON, "data": data_allow_uni}, "latest"]) or "0x0", 16)
        if allow_uni < unidades_usdc_nativo:
            data_approve_uni = "0x095ea7b3" + encode(["address", "uint256"], [UNISWAP_V3_ROUTER_POLYGON, unidades_usdc_nativo]).hex()
            _enviar_tx_polygon_y_esperar(priv_key, CONTRATO_USDC_NATIVO_POLYGON, data_approve_uni, gas_limit=100000)

        min_out = int(unidades_usdc_nativo * 0.998)
        deadline = int(time.time()) + 600
        params_tuple = (
            CONTRATO_USDC_NATIVO_POLYGON,
            CONTRATO_USDCE_POLYGON,
            100,
            direccion,
            deadline,
            unidades_usdc_nativo,
            min_out,
            0,
        )
        data_swap = "0x414bf389" + encode(
            ["(address,address,uint24,address,uint256,uint256,uint256,uint160)"],
            [params_tuple],
        ).hex()
        _enviar_tx_polygon_y_esperar(priv_key, UNISWAP_V3_ROUTER_POLYGON, data_swap, gas_limit=280000)
        print("   🎉 Conversión a USDC.e completada con éxito!")
    else:
        print("ℹ️  Paso A: No hay USDC Nativo pendiente de convertir.")

    deposit_wallet = _obtener_deposit_wallet_polymarket(direccion)

    # 2. Envolver USDC.e -> pUSD (Polymarket USD V2) 1:1 directo hacia la Deposit Wallet
    res_usdce_hex = _rpc_call_polygon(
        "eth_call",
        [{"to": CONTRATO_USDCE_POLYGON, "data": "0x70a08231" + addr_pad}, "latest"],
    )
    unidades_usdce = int(res_usdce_hex or "0x0", 16)
    if unidades_usdce >= 100_000:  # >= $0.10 USDC.e
        monto_usdce = unidades_usdce / 1e6
        print(f"\n🔄 Paso B: Envolviendo ${monto_usdce:.2f} USDC.e -> pUSD (Deposit Wallet V2) 1:1 (0% comisión)...")
        data_allow_wrap = "0xdd62ed3e" + encode(["address", "address"], [direccion, POLY_PUSD_WRAPPER]).hex()
        allow_wrap = int(_rpc_call_polygon("eth_call", [{"to": CONTRATO_USDCE_POLYGON, "data": data_allow_wrap}, "latest"]) or "0x0", 16)
        if allow_wrap < unidades_usdce:
            max_uint256 = (2**256) - 1
            data_app_wrap = "0x095ea7b3" + encode(["address", "uint256"], [POLY_PUSD_WRAPPER, max_uint256]).hex()
            _enviar_tx_polygon_y_esperar(priv_key, CONTRATO_USDCE_POLYGON, data_app_wrap, gas_limit=100000)

        # wrap(address token, address to, uint256 amount) -> selector 0x62355638
        destino_pusd = deposit_wallet or direccion
        data_wrap = "0x62355638" + encode(
            ["address", "address", "uint256"],
            [CONTRATO_USDCE_POLYGON, destino_pusd, unidades_usdce],
        ).hex()
        _enviar_tx_polygon_y_esperar(priv_key, POLY_PUSD_WRAPPER, data_wrap, gas_limit=180000)
        print(f"   🎉 ¡${monto_usdce:.2f} pUSD acreditados 1:1 en tu Deposit Wallet para Polymarket V2!")
    else:
        print("ℹ️  Paso B: No hay USDC.e pendiente de envolver.")

    # 2.5 Si hay pUSD en la EOA, transferirlo 1:1 a la Deposit Wallet derivada
    res_pusd_eoa_hex = _rpc_call_polygon(
        "eth_call",
        [{"to": CONTRATO_PUSD_POLYGON, "data": "0x70a08231" + addr_pad}, "latest"],
    )
    unidades_pusd_eoa = int(res_pusd_eoa_hex or "0x0", 16)
    if deposit_wallet and unidades_pusd_eoa >= 100_000:
        monto_pusd_eoa = unidades_pusd_eoa / 1e6
        print(f"\n🔄 Paso B.2: Moviendo ${monto_pusd_eoa:.2f} pUSD de tu MetaMask EOA -> Deposit Wallet Polymarket V2 ({deposit_wallet})...")
        data_transfer = "0xa9059cbb" + encode(["address", "uint256"], [deposit_wallet, unidades_pusd_eoa]).hex()
        _enviar_tx_polygon_y_esperar(priv_key, CONTRATO_PUSD_POLYGON, data_transfer, gas_limit=120000)
        print(f"   🎉 ¡${monto_pusd_eoa:.2f} pUSD listos en tu Deposit Wallet ({deposit_wallet})!")

    # 3. Desplegar (si hace falta) y habilitar permisos sin gas en la Deposit Wallet de Polymarket V2
    print("\n🔐 Paso C: Verificando Deposit Wallet y permisos sin gas en Polymarket V2...")
    sc_tmp = SecureClient._create(private_key=priv_key, wallet=None)
    try:
        bk = sc_tmp.create_builder_api_key()
    finally:
        sc_tmp.close()

    sc = SecureClient.create(private_key=priv_key, api_key=bk)
    try:
        sc._ctx.rpc._transport._base_url = RPC_POLYGON
        sc._ctx.rpc._transport._client.base_url = RPC_POLYGON
        sc.setup_trading_approvals()
        print(f"   • Deposit Wallet ({sc.wallet}) desplegada y 100% habilitada sin gas ✅")
    finally:
        sc.close()

    print("═" * 95 + "\n")


def imprimir_panel_wallet(estado: Dict[str, Any]) -> None:
    print("\n" + "═" * 95)
    print("🔐 GESTOR DE BILLETERA WEB3 EXCLUSIVA DEL BOT (EVM: Polygon & Base L2)")
    print("═" * 95)
    if not estado.get("configurada"):
        print(f"⚠️  {estado.get('mensaje')}")
        print("═" * 95 + "\n")
        return

    print(f"📍 Dirección MetaMask EOA (0x)    : {estado['direccion_publica']}")
    if estado.get("deposit_wallet_polymarket"):
        print(f"🏦 Deposit Wallet Polymarket V2   : {estado['deposit_wallet_polymarket']}")
    print(f"🛡️  Estado del Candado Operativo  : {estado['modo_ejecucion']}")
    print("─" * 95)
    print("💰 SALDOS EN VIVO EN BLOCKCHAIN (Consultados vía RPC Público):")
    print(f"   • Polygon pUSD (Polymarket V2): ${estado.get('polygon_pusd_polymarket', 0.0):.2f} USD")
    print(f"   • Polygon USDC.e (Puente)     : ${estado['polygon_usdce_polymarket']:.2f} USD")
    print(f"   • Polygon USDC Nativo (Azuro) : ${estado['polygon_usdc_nativo']:.2f} USD")
    print(f"   • Polygon Gas (POL / MATIC)   : {estado['polygon_pol_gas']:.5f} POL")
    print(f"   • Base L2 USDC (Limitless)    : ${estado['base_usdc_limitless']:.2f} USD")
    print(f"   • Base L2 Gas (ETH)           : {estado['base_eth_gas']:.5f} ETH")
    print("─" * 95)
    print(f"🏦 CAPITAL TOTAL OPERATIVO EN BILLETERA: ${estado['total_usdc_disponible']:.2f} USD")
    print("═" * 95 + "\n")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Gestor Seguro de Billetera Web3 para el Bot Cuantitativo")
    parser.add_argument(
        "--crear-wallet",
        action="store_true",
        help="Genera una billetera Web3 nueva y aislada, guardando la clave privada solo en .env",
    )
    parser.add_argument(
        "--preparar-polymarket",
        action="store_true",
        help="Convierte USDC Nativo a USDC.e 1:1 en Uniswap V3 y habilita contratos de Polymarket",
    )
    args = parser.parse_args()

    if args.crear_wallet:
        addr, creada = obtener_o_crear_wallet_bot(crear_si_no_existe=True)
        if creada:
            print(f"\n✅ Nueva Billetera Exclusiva del Bot creada y guardada de forma segura en `.env`: {addr}")
        else:
            print(f"\nℹ️  Ya existía una billetera configurada en `.env` (no se sobrescribió): {addr}")

    if args.preparar_polymarket:
        preparar_wallet_polymarket_onchain()

    estado_actual = verificar_estado_wallet()
    imprimir_panel_wallet(estado_actual)
