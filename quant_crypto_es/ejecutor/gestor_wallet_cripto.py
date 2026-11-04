"""
Gestor de Wallet y Ejecución On-Chain para Quant Crypto ES (Polygon).
=====================================================================
Conecta con los mismos canales ya auditados y verificados en Polygon:
1. MetaMask EOA (`0x178a6ca9...`): Firmante criptográfico y titular de POL / USDC.e / WETH / WBTC en Uniswap V3.
2. Polymarket V2 Deposit Wallet (`0x71DD64...`): Titular de `pUSD` (`0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB`) para el CLOB V2 de Polymarket.

Por seguridad estricta, `EJECUCION_REAL_HABILITADA` está en `false` por defecto (Modo Paper Trading con libro de órdenes real).
"""

import logging
import os
import time
from typing import Any, Dict

import requests
from dotenv import load_dotenv
from eth_abi import encode
from eth_account import Account
from eth_utils import to_checksum_address

from configuracion import (
    BANKROLL_DIARIO_CRIPTO_USD,
    MICRO_STAKE_MAX_USD,
    MICRO_STAKE_MIN_USD,
    TOKENS_POLYGON,
)

logger = logging.getLogger("GestorWalletCripto")

RPC_POLYGON = "https://polygon-bor-rpc.publicnode.com"
POLYMARKET_CLOB_URL = "https://clob.polymarket.com"
UNISWAP_V3_ROUTER = "0xE592427A0AEce92De3Edee1F18E0157C05861564"


def _configurar_proxy_polymarket_si_aplica() -> None:
    """Inyecta proxy residencial/gratuito si se ejecuta desde servidor cloud bloqueado."""
    load_dotenv(override=True)
    proxy_url = os.getenv("POLYMARKET_PROXY_URL", "").strip()
    if not proxy_url:
        return
    try:
        import httpx
        _orig_init = httpx.Client.__init__

        def _patched_init(self, *args, **kwargs):
            if "proxy" not in kwargs and "mounts" not in kwargs:
                kwargs["proxy"] = proxy_url
            _orig_init(self, *args, **kwargs)

        httpx.Client.__init__ = _patched_init
    except Exception as exc:
        logger.debug("No se pudo aplicar parche de proxy httpx: %s", exc)


class GestorWalletCripto:
    """
    Gestor unificado de billetera Polygon para:
    - Motor Cripto 1: Opciones Digitales de Corto Plazo en Polymarket V2 CLOB.
    - Motor Cripto 2: Micro-Swaps Spot en Uniswap V3 Polygon (`exactInputSingle`).
    """

    def __init__(self, rpc_url: str = RPC_POLYGON) -> None:
        load_dotenv(override=True)
        self.rpc_url = os.getenv("POLYGON_RPC_URL", rpc_url)
        self.address = os.getenv("BOT_WALLET_ADDRESS", "").strip()
        self.private_key = os.getenv("BOT_WALLET_PRIVATE_KEY", "").strip()
        self.deposit_wallet_override = os.getenv("POLYMARKET_DEPOSIT_WALLET", "").strip()
        # Variable independiente para que el experimento de 48h corra en Paper Trading seguro
        self.ejecucion_real = os.getenv("EJECUCION_REAL_CRIPTO_HABILITADA", "false").lower() == "true"

        self.capital_base_usd = float(os.getenv("CAPITAL_TRADING_CRIPTO_USD", str(BANKROLL_DIARIO_CRIPTO_USD)))
        self.stake_min_usd = float(os.getenv("MICRO_STAKE_MINIMO_USD", str(MICRO_STAKE_MIN_USD)))
        self.stake_max_usd = float(os.getenv("MICRO_STAKE_MAXIMO_USD", str(MICRO_STAKE_MAX_USD)))

    def _rpc_call(self, method: str, params: list) -> Any:
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        resp = requests.post(self.rpc_url, json=payload, timeout=12)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Error RPC Polygon: {data['error']}")
        return data.get("result")

    def consultar_balance_erc20(self, token_address: str, wallet_address: str, decimales: int = 6) -> float:
        if not wallet_address or not wallet_address.startswith("0x"):
            return 0.0
        addr_clean = wallet_address.lower().replace("0x", "").zfill(64)
        data = "0x70a08231" + addr_clean
        try:
            res = self._rpc_call("eth_call", [{"to": token_address, "data": data}, "latest"])
            if not res or res == "0x":
                return 0.0
            return int(res, 16) / (10 ** decimales)
        except Exception as exc:
            logger.debug("Error consultando ERC20 %s: %s", token_address, exc)
            return 0.0

    def consultar_balance_pol(self, wallet_address: str) -> float:
        if not wallet_address or not wallet_address.startswith("0x"):
            return 0.0
        try:
            res = self._rpc_call("eth_getBalance", [wallet_address, "latest"])
            return int(res, 16) / (10 ** 18) if res else 0.0
        except Exception:
            return 0.0

    def obtener_deposit_wallet_polymarket(self) -> str:
        """Obtiene la Deposit Wallet oficial de Polymarket V2 asociada a la EOA."""
        if self.deposit_wallet_override and self.deposit_wallet_override.startswith("0x"):
            return self.deposit_wallet_override
        if not self.private_key:
            return ""
        try:
            from polymarket_client import SecureClient
            pk = self.private_key if self.private_key.startswith("0x") else "0x" + self.private_key
            sc = SecureClient._create(private_key=pk, wallet=None)
            return str(sc.wallet_address)
        except Exception:
            return ""

    def obtener_resumen_billetera(self) -> Dict[str, Any]:
        """Devuelve el estado completo de saldos en Polygon (EOA + Deposit Wallet V2)."""
        if not self.address:
            return {
                "configurada": False,
                "modo_ejecucion": "REAL ON-CHAIN" if self.ejecucion_real else "SIMULACION / PAPER TRADING",
                "pol_gas": 0.0,
                "pusd_deposit_wallet": 0.0,
                "usdc_total_operativo": 0.0,
                "weth_eoa": 0.0,
                "wbtc_eoa": 0.0,
            }

        pol = self.consultar_balance_pol(self.address)
        usdc_e = self.consultar_balance_erc20(TOKENS_POLYGON["USDC_E"]["address"], self.address, 6)
        pusd_eoa = self.consultar_balance_erc20(TOKENS_POLYGON["PUSD"]["address"], self.address, 6)
        weth_eoa = self.consultar_balance_erc20(TOKENS_POLYGON["WETH"]["address"], self.address, 18)
        wbtc_eoa = self.consultar_balance_erc20(TOKENS_POLYGON["WBTC"]["address"], self.address, 8)

        dep_wallet = self.obtener_deposit_wallet_polymarket()
        pusd_dep = (
            self.consultar_balance_erc20(TOKENS_POLYGON["PUSD"]["address"], dep_wallet, 6)
            if dep_wallet
            else 0.0
        )

        return {
            "configurada": True,
            "direccion_eoa": self.address,
            "deposit_wallet_polymarket": dep_wallet,
            "modo_ejecucion": "REAL ON-CHAIN" if self.ejecucion_real else "SIMULACION / PAPER TRADING",
            "pol_gas": round(pol, 4),
            "pusd_deposit_wallet": round(pusd_dep, 2),
            "pusd_eoa": round(pusd_eoa, 2),
            "usdc_e_eoa": round(usdc_e, 2),
            "usdc_total_operativo": round(pusd_dep + pusd_eoa + usdc_e, 2),
            "weth_eoa": round(weth_eoa, 6),
            "wbtc_eoa": round(wbtc_eoa, 6),
        }

    def verificar_orderbook_polymarket_cripto(self, id_mercado: str, indice_lado: int, precio_objetivo: float) -> Dict[str, Any]:
        """
        Verifica en vivo el Orderbook real del CLOB de Polymarket para un contrato cripto
        antes de aprobar cualquier operación.
        """
        partes = str(id_mercado).split("::")
        token_id = partes[indice_lado] if len(partes) > indice_lado else partes[0]
        if not token_id:
            return {"liquidez_ok": False, "motivo": "Token ID vacío"}
        try:
            resp = requests.get(
                f"{POLYMARKET_CLOB_URL}/book",
                params={"token_id": str(token_id)},
                timeout=8,
            )
            if resp.status_code != 200:
                return {"liquidez_ok": False, "motivo": f"HTTP {resp.status_code}", "token_id": token_id}
            libro = resp.json()
            asks = libro.get("asks", [])
            bids = libro.get("bids", [])
            if not asks:
                return {"liquidez_ok": False, "motivo": "Sin vendedores (asks vacíos)", "token_id": token_id}

            mejor_ask = min(float(a["price"]) for a in asks)
            mejor_bid = max(float(b["price"]) for b in bids) if bids else 0.0
            spread = mejor_ask - mejor_bid if mejor_bid > 0 else 1.0

            liquidez_cercana_usd = sum(
                float(a["price"]) * float(a["size"])
                for a in asks
                if float(a["price"]) <= max(precio_objetivo * 1.04, mejor_ask + 0.02)
            )

            return {
                "liquidez_ok": liquidez_cercana_usd >= self.stake_min_usd and mejor_ask <= 0.90,
                "token_id": token_id,
                "mejor_ask": round(mejor_ask, 4),
                "mejor_bid": round(mejor_bid, 4),
                "spread": round(spread, 4),
                "liquidez_usd": round(liquidez_cercana_usd, 2),
            }
        except Exception as exc:
            return {"liquidez_ok": False, "motivo": str(exc), "token_id": token_id}

    def ejecutar_orden_polymarket_cripto(
        self,
        id_mercado: str,
        indice_lado: int,
        precio_limite: float,
        stake_usd: float,
        descripcion: str,
    ) -> Dict[str, Any]:
        """
        Ejecuta una micro-operación en Polymarket V2 CLOB (o la registra en Paper Trading
        verificando primero el libro de órdenes real).
        """
        stake_final = round(min(max(stake_usd, self.stake_min_usd), self.stake_max_usd), 2)
        verificacion = self.verificar_orderbook_polymarket_cripto(id_mercado, indice_lado, precio_limite)
        token_id = verificacion.get("token_id", "")

        if not self.ejecucion_real:
            return {
                "exito": True,
                "modo": "PAPER_TRADING_VERIFICADO",
                "descripcion": descripcion,
                "token_id": str(token_id),
                "precio_ejecucion": verificacion.get("mejor_ask", round(precio_limite, 3)),
                "stake_usd": stake_final,
                "liquidez_orderbook_usd": verificacion.get("liquidez_usd", 0.0),
                "orderbook_ok": verificacion.get("liquidez_ok", False),
            }

        if not self.private_key:
            return {"exito": False, "modo": "REAL_ERROR", "error": "Falta BOT_WALLET_PRIVATE_KEY en .env"}

        try:
            _configurar_proxy_polymarket_si_aplica()
            from polymarket_client import OrderArgs, OrderType, SecureClient, Side

            pk = self.private_key if self.private_key.startswith("0x") else "0x" + self.private_key
            sc = SecureClient._create(private_key=pk, wallet=None)
            sc._ctx.rpc._transport._base_url = self.rpc_url

            precio_clob = round(verificacion.get("mejor_ask") or precio_limite, 2)
            precio_clob = min(max(precio_clob, 0.02), 0.95)
            contratos = round(max(stake_final / precio_clob, 5.0), 2)

            order_args = OrderArgs(
                token_id=str(token_id),
                price=precio_clob,
                size=contratos,
                side=Side.BUY,
            )
            signed_order = sc.create_order(order_args)
            resp = sc.post_order(signed_order, OrderType.GTC, post_only=False)
            return {
                "exito": True,
                "modo": "REAL_ON_CHAIN_POLYMARKET_V2",
                "descripcion": descripcion,
                "precio_clob": precio_clob,
                "contratos": contratos,
                "stake_usd": round(contratos * precio_clob, 2),
                "respuesta_clob": resp,
            }
        except Exception as exc:
            logger.error("Error enviando orden real cripto a Polymarket V2: %s", exc)
            return {"exito": False, "modo": "REAL_ERROR", "error": str(exc)}

    def cotizar_o_ejecutar_swap_uniswap_v3(
        self,
        simbolo: str,
        precio_spot_ref: float,
        stake_usd: float,
    ) -> Dict[str, Any]:
        """
        Motor Cripto 2: Prepara, cotiza o ejecuta un micro-swap en Uniswap V3 (Polygon)
        usando `exactInputSingle` con pool fee 0.05% (500 bps).
        Por defecto opera en modo Paper Trading auditado.
        """
        stake_final = round(min(max(stake_usd, self.stake_min_usd), self.stake_max_usd), 2)
        mapa_tokens = {
            "BTC": (TOKENS_POLYGON["WBTC"]["address"], 8),
            "ETH": (TOKENS_POLYGON["WETH"]["address"], 18),
            "POL": (TOKENS_POLYGON["WPOL"]["address"], 18),
        }
        token_out, decimales_out = mapa_tokens.get(simbolo, (TOKENS_POLYGON["WETH"]["address"], 18))
        cantidad_estimada = round(stake_final / precio_spot_ref, 6) if precio_spot_ref > 0 else 0.0

        if not self.ejecucion_real:
            return {
                "exito": True,
                "modo": "PAPER_TRADING_UNISWAP_V3",
                "simbolo": simbolo,
                "router_polygon": UNISWAP_V3_ROUTER,
                "token_in": TOKENS_POLYGON["USDC_E"]["address"],
                "token_out": token_out,
                "fee_tier_bps": 5,
                "stake_usd": stake_final,
                "precio_entrada_spot": precio_spot_ref,
                "cantidad_token_estimada": cantidad_estimada,
            }

        if simbolo not in mapa_tokens:
            return {
                "exito": False,
                "modo": "UNISWAP_SKIP",
                "motivo": f"{simbolo} no tiene pool directo 0.05% en Uniswap V3 Polygon (usar BTC/ETH/POL).",
            }

        try:
            pk = self.private_key if self.private_key.startswith("0x") else "0x" + self.private_key
            acct = Account.from_key(pk)
            eoa = to_checksum_address(acct.address)
            amount_in_wei = int(stake_final * (10 ** 6))
            deadline = int(time.time()) + 300
            min_out_wei = int((stake_final / (precio_spot_ref * 1.005)) * (10 ** decimales_out))

            selector = bytes.fromhex("414bf389")
            encoded_args = encode(
                ["(address,address,uint24,address,uint256,uint256,uint256,uint160)"],
                [(
                    to_checksum_address(TOKENS_POLYGON["USDC_E"]["address"]),
                    to_checksum_address(token_out),
                    500,
                    eoa,
                    deadline,
                    amount_in_wei,
                    min_out_wei,
                    0,
                )],
            )
            calldata = "0x" + (selector + encoded_args).hex()
            return {
                "exito": True,
                "modo": "CALLDATA_LISTO_UNISWAP_V3",
                "router": UNISWAP_V3_ROUTER,
                "calldata_preview": calldata[:66] + "...",
                "stake_usd": stake_final,
            }
        except Exception as exc:
            return {"exito": False, "modo": "UNISWAP_ERROR", "error": str(exc)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    gestor = GestorWalletCripto()
    resumen = gestor.obtener_resumen_billetera()
    print("\n===========================================================================")
    print("🔐 ESTADO DE BILLETERA POLYGON — QUANT CRYPTO ES")
    print("===========================================================================")
    for k, v in resumen.items():
        print(f"  • {k}: {v}")
    print("===========================================================================\n")
