"""Lecturas EVM por RPC (solo eth_call; nunca firma ni envía transacciones)."""
from __future__ import annotations

import logging

from web3 import Web3

log = logging.getLogger("dryrun")

ABI_ERC20 = [
    {"name": "decimals", "inputs": [], "outputs": [{"type": "uint8"}], "stateMutability": "view", "type": "function"},
    {"name": "symbol", "inputs": [], "outputs": [{"type": "string"}], "stateMutability": "view", "type": "function"},
]

# Uniswap V3 QuoterV2 (y forks con la misma interfaz: HyperSwap V3, KittenSwap CL, etc.)
ABI_QUOTER_V2 = [{
    "name": "quoteExactInputSingle", "type": "function", "stateMutability": "nonpayable",
    "inputs": [{"name": "params", "type": "tuple", "components": [
        {"name": "tokenIn", "type": "address"}, {"name": "tokenOut", "type": "address"},
        {"name": "amountIn", "type": "uint256"}, {"name": "fee", "type": "uint24"},
        {"name": "sqrtPriceLimitX96", "type": "uint160"}]}],
    "outputs": [{"name": "amountOut", "type": "uint256"}, {"name": "sqrtPriceX96After", "type": "uint160"},
                {"name": "initializedTicksCrossed", "type": "uint32"}, {"name": "gasEstimate", "type": "uint256"}],
}]

ABI_FACTORY_V3 = [{
    "name": "getPool", "type": "function", "stateMutability": "view",
    "inputs": [{"type": "address"}, {"type": "address"}, {"type": "uint24"}],
    "outputs": [{"type": "address"}],
}]

ABI_CURVE = [{
    "name": "get_dy", "type": "function", "stateMutability": "view",
    "inputs": [{"type": "int128"}, {"type": "int128"}, {"type": "uint256"}],
    "outputs": [{"type": "uint256"}],
}]

# Oráculo de gas de las cadenas OP Stack (Base, Optimism): costo de publicar en L1.
DIR_GAS_PRICE_ORACLE = "0x420000000000000000000000000000000000000F"
ABI_GAS_PRICE_ORACLE = [{
    "name": "getL1FeeUpperBound", "type": "function", "stateMutability": "view",
    "inputs": [{"type": "uint256"}], "outputs": [{"type": "uint256"}],
}]

CERO = "0x0000000000000000000000000000000000000000"


def es_direccion(x) -> bool:
    return isinstance(x, str) and Web3.is_address(x) and x.lower() != CERO


class Cadena:
    def __init__(self, nombre: str, rpc: str, op_stack: bool = False):
        self.nombre = nombre
        self.w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 15}))
        self.op_stack = op_stack
        self._decimales: dict[str, int] = {}

    def c(self, direccion: str, abi):
        return self.w3.eth.contract(address=Web3.to_checksum_address(direccion), abi=abi)

    def tiene_codigo(self, direccion: str) -> bool:
        return len(self.w3.eth.get_code(Web3.to_checksum_address(direccion))) > 0

    def decimales(self, token: str) -> int:
        k = token.lower()
        if k not in self._decimales:
            self._decimales[k] = self.c(token, ABI_ERC20).functions.decimals().call()
        return self._decimales[k]

    def simbolo(self, token: str) -> str:
        try:
            return self.c(token, ABI_ERC20).functions.symbol().call()
        except Exception:
            return "?"

    def cotizar_v3(self, quoter: str, token_in: str, token_out: str, monto_in: float, fee: int) -> float | None:
        """Cuánto `token_out` se recibe por `monto_in` de `token_in` (en unidades humanas)."""
        try:
            d_in, d_out = self.decimales(token_in), self.decimales(token_out)
            crudo = int(monto_in * 10 ** d_in)
            res = self.c(quoter, ABI_QUOTER_V2).functions.quoteExactInputSingle(
                (Web3.to_checksum_address(token_in), Web3.to_checksum_address(token_out), crudo, fee, 0)
            ).call()
            return res[0] / 10 ** d_out
        except Exception as e:  # pool inexistente, sin liquidez, RPC caído
            log.debug("cotizar_v3 falló %s→%s: %s", token_in, token_out, e)
            return None

    def cotizar_curve(self, pool: str, i: int, j: int, monto_in: float, dec_in: int, dec_out: int) -> float | None:
        try:
            dy = self.c(pool, ABI_CURVE).functions.get_dy(i, j, int(monto_in * 10 ** dec_in)).call()
            return dy / 10 ** dec_out
        except Exception as e:
            log.debug("get_dy falló en %s: %s", pool, e)
            return None

    def pool_v3(self, factory: str, a: str, b: str, fee: int) -> str | None:
        try:
            p = self.c(factory, ABI_FACTORY_V3).functions.getPool(
                Web3.to_checksum_address(a), Web3.to_checksum_address(b), fee).call()
            return p if es_direccion(p) else None
        except Exception:
            return None

    def gas_nativo(self, unidades_gas: int, tam_tx_bytes: int = 600) -> float:
        """Costo de gas en moneda nativa (ETH/HYPE), sumando el fee de L1 en OP Stack."""
        precio = self.w3.eth.gas_price
        total = unidades_gas * precio
        if self.op_stack:
            try:
                total += self.c(DIR_GAS_PRICE_ORACLE, ABI_GAS_PRICE_ORACLE).functions.getL1FeeUpperBound(
                    tam_tx_bytes).call()
            except Exception as e:
                log.debug("getL1FeeUpperBound falló: %s", e)
        return total / 1e18
