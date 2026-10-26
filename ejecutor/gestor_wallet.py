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
RPC_POLYGON = "https://polygon-rpc.com"
RPC_BASE = "https://mainnet.base.org"

# Contratos oficiales de USDC (6 decimales)
CONTRATO_USDCE_POLYGON = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"  # Colateral oficial de Polymarket CLOB
CONTRATO_USDC_NATIVO_POLYGON = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
CONTRATO_USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"  # Colateral oficial de Limitless Exchange


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

    usdce_poly = _consultar_erc20_balance(RPC_POLYGON, CONTRATO_USDCE_POLYGON, direccion)
    usdc_poly = _consultar_erc20_balance(RPC_POLYGON, CONTRATO_USDC_NATIVO_POLYGON, direccion)
    pol_gas = _consultar_balance_nativo(RPC_POLYGON, direccion)

    usdc_base = _consultar_erc20_balance(RPC_BASE, CONTRATO_USDC_BASE, direccion)
    eth_base_gas = _consultar_balance_nativo(RPC_BASE, direccion)

    total_usdc_operativo = round(usdce_poly + usdc_poly + usdc_base, 2)

    return {
        "configurada": True,
        "direccion_publica": direccion,
        "modo_ejecucion": "REAL_HABILITADO" if ejecucion_real else "SIMULACION_SEGURA (Paper Trading)",
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
    Firma y envía una orden al CLOB de Polymarket usando `py-clob-client` (EIP-712).
    - `lado`: "BUY" (compra de entrada) o "SELL" (venta Maker de salida en Motor 3).
    - `tipo_orden`: "FOK" (Fill-or-Kill inmediato para Motor 1 y 2) o "GTC" (Good-Till-Cancelled Maker para Motor 3).
    """
    load_dotenv(RUTA_ENV, override=True)
    ejecucion_real = os.getenv("EJECUCION_REAL_HABILITADA", "false").lower() == "true"
    priv_key = os.getenv("BOT_WALLET_PRIVATE_KEY", "").strip()

    if not ejecucion_real:
        return (
            False,
            "Candado activo (`EJECUCION_REAL_HABILITADA=false` en .env). Orden procesada en modo Paper Trading.",
        )

    if not priv_key:
        return False, "Falta `BOT_WALLET_PRIVATE_KEY` en .env."

    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import OrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY, SELL

        host = "https://clob.polymarket.com"
        chain_id = 137  # Polygon Mainnet
        cliente = ClobClient(host, key=priv_key, chain_id=chain_id)

        # Derivar o recuperar credenciales L2 (API Key / Secret / Passphrase) automáticamente con la firma EIP-712
        creds = cliente.create_or_derive_api_creds()
        cliente.set_api_creds(creds)

        const_lado = BUY if lado.upper() == "BUY" else SELL
        # Cantidad de contratos (shares) = tamano_usd / precio
        contratos = round(tamano_usd / precio, 2)
        if contratos < 5.0 and tipo_orden.upper() == "GTC":
            contratos = 5.0  # Mínimo técnico de Polymarket para órdenes Maker GTC

        orden_args = OrderArgs(
            price=round(precio, 3),
            size=contratos,
            side=const_lado,
            token_id=token_id,
        )
        orden_firmada = cliente.create_order(orden_args)
        tipo_enum = OrderType.FOK if tipo_orden.upper() == "FOK" else OrderType.GTC
        respuesta = cliente.post_order(orden_firmada, tipo_enum)
        return True, f"Orden {tipo_orden} enviada a Polymarket: {respuesta}"
    except Exception as exc:
        return False, f"Error firmando/enviando orden a Polymarket CLOB: {exc}"


def imprimir_panel_wallet(estado: Dict[str, Any]) -> None:
    print("\n" + "═" * 95)
    print("🔐 GESTOR DE BILLETERA WEB3 EXCLUSIVA DEL BOT (EVM: Polygon & Base L2)")
    print("═" * 95)
    if not estado.get("configurada"):
        print(f"⚠️  {estado.get('mensaje')}")
        print("═" * 95 + "\n")
        return

    print(f"📍 Dirección Pública del Bot (0x) : {estado['direccion_publica']}")
    print(f"🛡️  Estado del Candado Operativo  : {estado['modo_ejecucion']}")
    print("─" * 95)
    print("💰 SALDOS EN VIVO EN BLOCKCHAIN (Consultados vía RPC Público):")
    print(f"   • Polygon USDC.e (Polymarket) : ${estado['polygon_usdce_polymarket']:.2f} USD")
    print(f"   • Polygon USDC Nativo (Azuro) : ${estado['polygon_usdc_nativo']:.2f} USD")
    print(f"   • Polygon Gas (POL / MATIC)   : {estado['polygon_pol_gas']:.5f} POL")
    print(f"   • Base L2 USDC (Limitless)    : ${estado['base_usdc_limitless']:.2f} USD")
    print(f"   • Base L2 Gas (ETH)           : {estado['base_eth_gas']:.5f} ETH")
    print("─" * 95)
    print(f"🏦 CAPITAL TOTAL OPERATIVO EN BILLETERA: ${estado['total_usdc_disponible']:.2f} USDC")
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
    args = parser.parse_args()

    if args.crear_wallet:
        addr, creada = obtener_o_crear_wallet_bot(crear_si_no_existe=True)
        if creada:
            print(f"\n✅ Nueva Billetera Exclusiva del Bot creada y guardada de forma segura en `.env`: {addr}")
        else:
            print(f"\nℹ️  Ya existía una billetera configurada en `.env` (no se sobrescribió): {addr}")

    estado_actual = verificar_estado_wallet()
    imprimir_panel_wallet(estado_actual)
