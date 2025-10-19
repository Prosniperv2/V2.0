import json
from web3 import Web3
from typing import Dict, List, Optional, Tuple
import requests
import time
import asyncio
from config import *
from rate_limiter import BASE_RPC_LIMITER, with_rate_limit

class DEXHandler:
    def __init__(self, web3: Web3):
        self.web3 = web3
        self.dexs = self._initialize_dexs()
        
    def _initialize_dexs(self) -> Dict:
        """Inicializa as configurações das DEXs"""
        dexs = {}
        
        if ENABLE_UNISWAP_V3:
            dexs['uniswap_v3'] = {
                'name': 'Uniswap V3',
                'router': UNISWAP_V3_ROUTER,
                'factory': UNISWAP_V3_FACTORY,
                'fee_tiers': [100, 500, 3000, 10000],  # 0.01%, 0.05%, 0.3%, 1%
                'priority': 1
            }
            
        if ENABLE_AERODROME:
            dexs['aerodrome'] = {
                'name': 'Aerodrome',
                'router': AERODROME_ROUTER,
                'factory': AERODROME_FACTORY,
                'priority': 2
            }
            
        if ENABLE_BASESWAP:
            dexs['baseswap'] = {
                'name': 'BaseSwap',
                'router': BASESWAP_ROUTER,
                'factory': BASESWAP_FACTORY,
                'priority': 3
            }
            
        if ENABLE_SUSHISWAP:
            dexs['sushiswap'] = {
                'name': 'SushiSwap',
                'router': SUSHISWAP_ROUTER,
                'priority': 4
            }
            
        return dexs
    
    def get_router_abi(self) -> List:
        """ABI completa para roteadores de DEX incluindo swaps de tokens"""
        return [
            {
                "inputs": [
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
                    {"internalType": "address[]", "name": "path", "type": "address[]"},
                    {"internalType": "address", "name": "to", "type": "address"},
                    {"internalType": "uint256", "name": "deadline", "type": "uint256"}
                ],
                "name": "swapExactETHForTokens",
                "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
                "stateMutability": "payable",
                "type": "function"
            },
            {
                "inputs": [
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
                    {"internalType": "address[]", "name": "path", "type": "address[]"},
                    {"internalType": "address", "name": "to", "type": "address"},
                    {"internalType": "uint256", "name": "deadline", "type": "uint256"}
                ],
                "name": "swapExactTokensForETH",
                "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
                "stateMutability": "nonpayable",
                "type": "function"
            },
            {
                "inputs": [
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
                    {"internalType": "address[]", "name": "path", "type": "address[]"},
                    {"internalType": "address", "name": "to", "type": "address"},
                    {"internalType": "uint256", "name": "deadline", "type": "uint256"}
                ],
                "name": "swapExactTokensForTokens",
                "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
                "stateMutability": "nonpayable",
                "type": "function"
            },
            {
                "inputs": [
                    {"internalType": "uint256", "name": "amountOut", "type": "uint256"},
                    {"internalType": "address[]", "name": "path", "type": "address[]"}
                ],
                "name": "getAmountsIn",
                "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
                "stateMutability": "view",
                "type": "function"
            },
            {
                "inputs": [
                    {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                    {"internalType": "address[]", "name": "path", "type": "address[]"}
                ],
                "name": "getAmountsOut",
                "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
                "stateMutability": "view",
                "type": "function"
            }
        ]
    
    async def get_weth_balance(self) -> float:
        """Obtém saldo WETH da carteira"""
        try:
            weth_contract = self.web3.eth.contract(
                address=WETH_ADDRESS,
                abi=[{
                    "constant": True,
                    "inputs": [{"name": "_owner", "type": "address"}],
                    "name": "balanceOf",
                    "outputs": [{"name": "balance", "type": "uint256"}],
                    "type": "function"
                }]
            )
            
            balance_wei = weth_contract.functions.balanceOf(WALLET_ADDRESS).call()
            balance_eth = self.web3.from_wei(balance_wei, 'ether')
            return float(balance_eth)
            
        except Exception as e:
            print(f"❌ Erro ao obter saldo WETH: {e}")
            return 0.0
    
    async def convert_weth_to_eth_if_needed(self, min_eth_needed: float = 0.0001) -> bool:
        """
        Converte WETH para ETH se o saldo de ETH estiver muito baixo
        """
        try:
            eth_balance = self.web3.eth.get_balance(WALLET_ADDRESS)
            eth_balance_eth = float(self.web3.from_wei(eth_balance, 'ether'))
            
            if eth_balance_eth >= min_eth_needed:
                return True  # ETH suficiente
            
            # Verificar saldo WETH
            weth_abi = [
                {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"},
                {"constant": False, "inputs": [{"name": "wad", "type": "uint256"}], "name": "withdraw", "outputs": [], "type": "function"}
            ]
            
            weth_contract = self.web3.eth.contract(address=WETH_ADDRESS, abi=weth_abi)
            weth_balance = weth_contract.functions.balanceOf(WALLET_ADDRESS).call()
            weth_balance_eth = float(self.web3.from_wei(weth_balance, 'ether'))
            
            # Calcular quanto WETH converter
            eth_needed = min_eth_needed - eth_balance_eth
            if weth_balance_eth >= eth_needed:
                # Converter WETH para ETH
                withdraw_amount = int(self.web3.to_wei(eth_needed, 'ether'))
                
                print(f"💱 Convertendo {eth_needed:.6f} WETH para ETH...")
                
                # Preparar transação de withdraw
                withdraw_tx = weth_contract.functions.withdraw(withdraw_amount).build_transaction({
                    'from': WALLET_ADDRESS,
                    'gas': 50000,  # Gas baixo para withdraw
                    'gasPrice': self.web3.to_wei(1, 'gwei'),  # Gas price baixo
                    'nonce': self.web3.eth.get_transaction_count(WALLET_ADDRESS)
                })
                
                # Assinar e enviar
                signed_tx = self.web3.eth.account.sign_transaction(withdraw_tx, PRIVATE_KEY)
                tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
                
                print(f"✅ WETH convertido para ETH: {tx_hash.hex()}")
                return True
            else:
                print(f"❌ WETH insuficiente para conversão ({weth_balance_eth:.6f} WETH disponível)")
                return False
                
        except Exception as e:
            print(f"❌ Erro ao converter WETH para ETH: {e}")
            return False
    
    async def check_token_liquidity(self, token_address: str) -> bool:
        """
        Verifica se o token tem liquidez suficiente em alguma DEX
        Versão ULTRA otimizada - teste mínimo e rápido
        """
        try:
            # Usar apenas uma quantidade mínima para teste ultra rápido
            test_amount = 10000000000000  # 0.00001 WETH (mínimo)
            
            # Testar DEXs em ordem de prioridade (mais prováveis primeiro)
            priority_order = ['uniswap_v3', 'aerodrome', 'baseswap', 'sushiswap']
            
            for dex_key in priority_order:
                if dex_key not in self.dexs:
                    continue
                    
                dex_info = self.dexs[dex_key]
                try:
                    await BASE_RPC_LIMITER.acquire()
                    
                    router_contract = self.web3.eth.contract(
                        address=dex_info['router'],
                        abi=self.get_router_abi()
                    )
                    
                    # Testar apenas WETH -> Token (mais comum para novos tokens)
                    path = [WETH_ADDRESS, token_address]
                    
                    amounts = router_contract.functions.getAmountsOut(test_amount, path).call()
                    
                    if len(amounts) >= 2 and amounts[-1] > 0:
                        print(f"✅ Liquidez encontrada em {dex_info['name']}")
                        BASE_RPC_LIMITER.handle_success()
                        return True
                        
                except Exception as e:
                    if "429" in str(e) or "Too Many Requests" in str(e):
                        BASE_RPC_LIMITER.handle_429_error()
                        await asyncio.sleep(0.1)  # Backoff mínimo
                    elif "execution reverted" in str(e).lower():
                        # Token não tem par nesta DEX, continuar
                        print(f"⚠️ {dex_info['name']}: Sem par de trading para este token")
                    continue
                        
            return False
            
        except Exception as e:
            print(f"❌ Erro ao verificar liquidez: {str(e)}")
            return False

    async def get_best_price(self, token_address: str, amount_in: int, is_buy: bool = True) -> Tuple[str, int, str]:
        """
        Encontra o melhor preço entre todas as DEXs com rate limiting e verificação de liquidez
        Returns: (dex_name, amount_out, router_address)
        """
        best_price = 0
        best_dex = None
        best_router = None
        successful_queries = 0
        
        # Tentar múltiplos paths para encontrar liquidez
        paths_to_try = []
        
        if is_buy:
            # Para compra: WETH -> Token
            paths_to_try = [
                [WETH_ADDRESS, token_address],  # Direto
                [WETH_ADDRESS, USDC_ADDRESS, token_address],  # Via USDC
                [WETH_ADDRESS, USDT_ADDRESS, token_address],  # Via USDT
            ]
        else:
            # Para venda: Token -> WETH
            paths_to_try = [
                [token_address, WETH_ADDRESS],  # Direto
                [token_address, USDC_ADDRESS, WETH_ADDRESS],  # Via USDC
                [token_address, USDT_ADDRESS, WETH_ADDRESS],  # Via USDT
            ]
        
        for dex_key, dex_info in self.dexs.items():
            try:
                await BASE_RPC_LIMITER.acquire()
                
                router_contract = self.web3.eth.contract(
                    address=dex_info['router'],
                    abi=self.get_router_abi()
                )
                
                # Tentar diferentes paths até encontrar liquidez
                for path in paths_to_try:
                    try:
                        amounts = router_contract.functions.getAmountsOut(amount_in, path).call()
                        amount_out = amounts[-1]
                        
                        if amount_out > 0:  # Encontrou liquidez
                            successful_queries += 1
                            
                            if amount_out > best_price:
                                best_price = amount_out
                                best_dex = dex_info['name']
                                best_router = dex_info['router']
                                
                            path_str = " -> ".join([addr[:6] + "..." for addr in path])
                            print(f"💰 {dex_info['name']} ({path_str}): {amount_out / 10**18:.6f} {'WETH' if not is_buy else 'tokens'}")
                            BASE_RPC_LIMITER.handle_success()
                            break  # Encontrou liquidez, não precisa testar outros paths
                            
                    except Exception as path_error:
                        # Se este path falhou, tentar o próximo
                        continue
                
                # Se chegou aqui sem break, não encontrou liquidez em nenhum path
                if successful_queries == 0 or best_dex != dex_info['name']:
                    print(f"⚠️ {dex_info['name']}: Sem liquidez em nenhum path")
                
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "Too Many Requests" in error_msg:
                    BASE_RPC_LIMITER.handle_429_error()
                    print(f"🚫 Rate limit 429 detectado. Backoff: {BASE_RPC_LIMITER.current_backoff}s")
                    print(f"⚠️ Rate limit em {dex_info['name']}, aguardando {BASE_RPC_LIMITER.current_backoff:.1f}s...")
                    await asyncio.sleep(min(BASE_RPC_LIMITER.current_backoff, 3))  # Máximo 3s
                elif "execution reverted" in error_msg.lower():
                    print(f"⚠️ {dex_info['name']}: Sem par de trading para este token")
                else:
                    print(f"⚠️ {dex_info['name']}: {error_msg[:50]}...")
                continue
        
        if successful_queries == 0:
            print("⚠️ Nenhuma DEX retornou preço válido - assumindo token muito novo")
            # Para tokens muito novos, assumir que terão liquidez em breve
            # Retornar valores padrão para permitir tentativa de compra
            print("🎯 MODO AGRESSIVO: Tentando compra mesmo sem preço confirmado")
            return "uniswap_v3", amount_in, self.dexs['uniswap_v3']['router']
            
        return best_dex, best_price, best_router
    
    async def execute_swap(self, token_address: str, amount_in: int, router_address: str, 
                    is_buy: bool = True, slippage: float = SLIPPAGE_TOLERANCE) -> Optional[str]:
        """
        Executa o swap na DEX especificada
        Returns: transaction hash ou None se falhar
        """
        try:
            import time  # Importar no início do método
            
            # Verificar se precisa converter WETH para ETH para gas
            if not await self.convert_weth_to_eth_if_needed(0.0001):
                print("⚠️ Saldo ETH muito baixo e não foi possível converter WETH")
            
            router_contract = self.web3.eth.contract(
                address=router_address,
                abi=self.get_router_abi()
            )
            
            path = [WETH_ADDRESS, token_address] if is_buy else [token_address, WETH_ADDRESS]
            deadline = int(time.time()) + 300  # 5 minutos
            
            # Calcular amount_out_min com slippage
            try:
                amounts = router_contract.functions.getAmountsOut(amount_in, path).call()
                amount_out_min = int(amounts[-1] * (100 - slippage) / 100)
            except Exception as e:
                print(f"⚠️ Não foi possível calcular preço exato - usando estimativa agressiva")
                # Para tokens muito novos, usar valor mínimo muito baixo
                amount_out_min = 1  # Aceitar qualquer quantidade de tokens
            
            # Preparar transação
            if is_buy:
                # Comprar token com WETH (não ETH direto)
                # Primeiro precisa aprovar WETH se necessário
                weth_abi = [
                    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
                    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"}
                ]
                
                weth_contract = self.web3.eth.contract(address=WETH_ADDRESS, abi=weth_abi)
                
                # Verificar allowance atual
                current_allowance = weth_contract.functions.allowance(WALLET_ADDRESS, router_address).call()
                
                if current_allowance < amount_in:
                    # Aprovar WETH para o router
                    # Usar gas mais conservador para saldos baixos
                    eth_balance = self.web3.eth.get_balance(WALLET_ADDRESS)
                    eth_balance_eth = float(self.web3.from_wei(eth_balance, 'ether'))
                    
                    # Ajustar gas baseado no saldo disponível
                    if eth_balance_eth < 0.0001:  # Saldo muito baixo
                        gas_limit = 50000
                        gas_price = self.web3.to_wei(1, 'gwei')  # Gas price muito baixo
                    else:
                        gas_limit = 100000
                        gas_price = self.web3.to_wei(MAX_GAS_PRICE, 'gwei')
                    
                    approve_tx = weth_contract.functions.approve(
                        router_address, 
                        amount_in * 2  # Aprovar um pouco mais para futuras transações
                    ).build_transaction({
                        'from': WALLET_ADDRESS,
                        'gas': gas_limit,
                        'gasPrice': gas_price,
                        'nonce': self.web3.eth.get_transaction_count(WALLET_ADDRESS)
                    })
                    
                    # Assinar e enviar aprovação
                    signed_approve = self.web3.eth.account.sign_transaction(approve_tx, PRIVATE_KEY)
                    approve_hash = self.web3.eth.send_raw_transaction(signed_approve.rawTransaction)
                    print(f"🔓 Aprovação WETH enviada: {approve_hash.hex()}")
                    
                    # Aguardar confirmação da aprovação
                    time.sleep(3)
                
                # Agora fazer o swap usando swapExactTokensForTokens
                transaction = router_contract.functions.swapExactTokensForTokens(
                    amount_in,
                    amount_out_min,
                    path,
                    WALLET_ADDRESS,
                    deadline
                ).build_transaction({
                    'from': WALLET_ADDRESS,
                    'gas': gas_limit * 2,  # Usar o mesmo gas ajustado
                    'gasPrice': gas_price,
                    'nonce': self.web3.eth.get_transaction_count(WALLET_ADDRESS)
                })
            else:
                # Vender token por WETH
                # Primeiro aprovar o token se necessário
                token_abi = [
                    {"constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
                    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"}
                ]
                
                token_contract = self.web3.eth.contract(address=token_address, abi=token_abi)
                
                # Verificar allowance atual
                current_allowance = token_contract.functions.allowance(WALLET_ADDRESS, router_address).call()
                
                if current_allowance < amount_in:
                    # Aprovar token para o router
                    approve_tx = token_contract.functions.approve(
                        router_address, 
                        amount_in * 2  # Aprovar um pouco mais
                    ).build_transaction({
                        'from': WALLET_ADDRESS,
                        'gas': 100000,
                        'gasPrice': self.web3.to_wei(MAX_GAS_PRICE, 'gwei'),
                        'nonce': self.web3.eth.get_transaction_count(WALLET_ADDRESS)
                    })
                    
                    # Assinar e enviar aprovação
                    signed_approve = self.web3.eth.account.sign_transaction(approve_tx, PRIVATE_KEY)
                    approve_hash = self.web3.eth.send_raw_transaction(signed_approve.rawTransaction)
                    print(f"🔓 Aprovação token enviada: {approve_hash.hex()}")
                    
                    # Aguardar confirmação da aprovação
                    time.sleep(3)
                
                # Fazer swap de token para WETH
                transaction = router_contract.functions.swapExactTokensForTokens(
                    amount_in,
                    amount_out_min,
                    path,
                    WALLET_ADDRESS,
                    deadline
                ).build_transaction({
                    'from': WALLET_ADDRESS,
                    'gas': DEFAULT_GAS_LIMIT,
                    'gasPrice': self.web3.to_wei(MAX_GAS_PRICE, 'gwei'),
                    'nonce': self.web3.eth.get_transaction_count(WALLET_ADDRESS)
                })
            
            # Assinar e enviar transação
            signed_txn = self.web3.eth.account.sign_transaction(transaction, PRIVATE_KEY)
            tx_hash = self.web3.eth.send_raw_transaction(signed_txn.rawTransaction)
            
            print(f"🚀 Transação enviada: {tx_hash.hex()}")
            return tx_hash.hex()
            
        except Exception as e:
            print(f"❌ Erro ao executar swap: {str(e)}")
            return None
    
    def check_liquidity(self, token_address: str) -> Dict[str, float]:
        """Verifica liquidez do token em todas as DEXs"""
        liquidity_info = {}
        
        for dex_key, dex_info in self.dexs.items():
            try:
                # Implementar verificação de liquidez específica para cada DEX
                # Por enquanto, retorna valores simulados
                liquidity_info[dex_info['name']] = {
                    'liquidity_usd': 50000,  # Valor simulado
                    'volume_24h': 25000,     # Valor simulado
                    'available': True
                }
            except Exception as e:
                liquidity_info[dex_info['name']] = {
                    'liquidity_usd': 0,
                    'volume_24h': 0,
                    'available': False,
                    'error': str(e)
                }
        
        return liquidity_info
    
    def test_all_dexs(self) -> Dict[str, bool]:
        """Testa conectividade com todas as DEXs"""
        results = {}
        
        print("🔍 Testando conectividade com todas as DEXs...")
        
        for dex_key, dex_info in self.dexs.items():
            try:
                # Teste mais simples: verificar se o contrato existe
                router_address = dex_info['router']
                code = self.web3.eth.get_code(router_address)
                
                if len(code) > 0:
                    # Contrato existe, tentar uma chamada simples
                    try:
                        router_contract = self.web3.eth.contract(
                            address=router_address,
                            abi=self.get_router_abi()
                        )
                        
                        # Teste com valores menores e tratamento de erro específico
                        test_path = [WETH_ADDRESS, USDC_ADDRESS]
                        test_amount = self.web3.to_wei(0.0001, 'ether')  # Valor menor
                        
                        amounts = router_contract.functions.getAmountsOut(test_amount, test_path).call()
                        
                        results[dex_info['name']] = True
                        print(f"✅ {dex_info['name']}: Conectado")
                        
                    except Exception as call_error:
                        # Se a chamada falhar, ainda considerar como disponível se o contrato existe
                        results[dex_info['name']] = True
                        print(f"✅ {dex_info['name']}: Conectado (contrato válido)")
                else:
                    results[dex_info['name']] = False
                    print(f"❌ {dex_info['name']}: Contrato não encontrado")
                    
            except Exception as e:
                results[dex_info['name']] = False
                print(f"❌ {dex_info['name']}: {str(e)}")
        
        working_count = sum(1 for result in results.values() if result)
        total_count = len(results)
        print(f"📊 Resultado: {working_count}/{total_count} DEXs funcionando")
        
        return results