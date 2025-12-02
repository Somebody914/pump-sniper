"""
Pump.fun Graduated Candidate Scanner

This module scans for pump.fun tokens that have graduated (migrated to Raydium)
and filters out bundled/bundler-bought coins. Integrates with Helius API for
on-chain analysis including holder concentration checks.
"""

import requests
import time
import json
import os
from dataclasses import dataclass, field
from typing import Optional

# ═══════════════════════════════════════════════════════════════════════════════
# CANDIDATE DATACLASS - Represents a graduated pump.fun token
# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class Candidate:
    """Represents a graduated pump.fun token candidate for trading."""
    mint: str
    symbol: str
    name: str
    price: float = 0.0
    market_cap: float = 0.0
    liquidity: float = 0.0
    volume_5m: float = 0.0
    volume_1h: float = 0.0
    volume_24h: float = 0.0
    change_5m: float = 0.0
    change_1h: float = 0.0
    change_24h: float = 0.0
    buys_5m: int = 0
    sells_5m: int = 0
    buys_1h: int = 0
    sells_1h: int = 0
    age_minutes: float = 9999
    holder_count: int = 0
    top_holder_percent: float = 0.0
    is_bundled: bool = False
    bundler_detected: bool = False
    graduated_at: Optional[float] = None
    pair_address: str = ""
    raydium_pool: str = ""
    pump_url: str = ""
    discovered_at: float = field(default_factory=time.time)

    def get_pump_url(self) -> str:
        """Returns the pump.fun URL for this token."""
        return f"https://pump.fun/{self.mint}"


# ═══════════════════════════════════════════════════════════════════════════════
# KNOWN BUNDLER ADDRESSES - Addresses known to bundle/snipe launches
# ═══════════════════════════════════════════════════════════════════════════════
DEFAULT_BUNDLER_ADDRESSES = {
    # Common bundler/sniper wallets (examples - can be expanded)
    "TSLvdd1pWpHVjahSpsvCXUbgwsL3YyCEEueFT7g4oqW",
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9",
    "DW8dL4YE9tX4N6PJkJvzPQGsLw2wELGNPPQPb4Y1a7qQ",
}


# ═══════════════════════════════════════════════════════════════════════════════
# GRADUATED SCANNER CLASS
# ═══════════════════════════════════════════════════════════════════════════════
class GraduatedScanner:
    """
    Scans for pump.fun graduated tokens (migrated to Raydium).
    
    Features:
    - Fetches graduated tokens from pump.fun API
    - Filters out bundled/bundler-bought coins
    - Integrates with Helius API for holder concentration analysis
    - Returns Candidate objects for trading evaluation
    """

    def __init__(self, helius_api_key: Optional[str] = None, known_bundlers_file: str = "known_bundlers.json"):
        """
        Initialize the GraduatedScanner.
        
        Args:
            helius_api_key: Optional Helius API key for on-chain analysis
            known_bundlers_file: Path to JSON file with known bundler addresses
        """
        self.helius_api_key = helius_api_key
        self.known_bundlers = self._load_bundlers(known_bundlers_file)
        
        # Log initialization status
        if self.helius_api_key and len(self.helius_api_key) > 10:
            print(f"🔍 GraduatedScanner: Helius API enabled for holder analysis")
        else:
            print(f"⚠️ GraduatedScanner: No Helius API key - skipping holder concentration checks")
        
        print(f"🚫 GraduatedScanner: Loaded {len(self.known_bundlers)} known bundler addresses")

    def _load_bundlers(self, filepath: str) -> set:
        """Load known bundler addresses from JSON file or use defaults."""
        bundlers = set(DEFAULT_BUNDLER_ADDRESSES)
        
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        bundlers.update(data)
                    elif isinstance(data, dict) and 'addresses' in data:
                        bundlers.update(data['addresses'])
                print(f"📁 Loaded bundlers from {filepath}")
            except Exception as e:
                print(f"⚠️ Error loading {filepath}: {e}, using defaults")
        
        return bundlers

    def _is_valid_solana_address(self, address: str) -> bool:
        """Check if address is a valid Solana address (not Ethereum)."""
        if not address:
            return False
        # Skip Ethereum addresses (start with 0x)
        if address.startswith('0x'):
            return False
        # Solana addresses are base58 encoded, typically 32-44 characters
        if len(address) < 32 or len(address) > 44:
            return False
        return True

    def _fetch_graduated_tokens(self, limit: int = 30) -> list:
        """
        Fetch graduated tokens from pump.fun API.
        
        These are tokens that have migrated from pump.fun bonding curve to Raydium.
        """
        tokens = []
        
        # Try multiple pump.fun API endpoints for graduated/migrated tokens
        endpoints = [
            # Graduated tokens (completed bonding curve, now on Raydium)
            f"https://frontend-api.pump.fun/coins?offset=0&limit={limit}&sort=last_trade_timestamp&order=desc&includeNsfw=false",
            # Recently active tokens
            f"https://frontend-api.pump.fun/coins?offset=0&limit={limit}&sort=market_cap&order=desc&includeNsfw=false",
        ]
        
        for endpoint in endpoints:
            try:
                r = requests.get(endpoint, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, list):
                        for coin in data:
                            # Check if token has graduated (migrated to Raydium)
                            # Graduated tokens have complete=true or raydium_pool set
                            is_graduated = (
                                coin.get('complete', False) or 
                                coin.get('raydium_pool') or
                                coin.get('king_of_the_hill_timestamp')
                            )
                            if is_graduated:
                                tokens.append(coin)
                    time.sleep(0.1)
            except Exception as e:
                print(f"⚠️ Error fetching from pump.fun: {e}")
        
        # Deduplicate by mint address
        seen_mints = set()
        unique_tokens = []
        for token in tokens:
            mint = token.get('mint', '')
            if mint and mint not in seen_mints:
                seen_mints.add(mint)
                unique_tokens.append(token)
        
        return unique_tokens[:limit]

    def _check_bundler(self, mint: str) -> tuple[bool, bool]:
        """
        Check if token was bundled or bought by known bundlers.
        
        Returns:
            Tuple of (is_bundled, bundler_detected)
        """
        if not self.helius_api_key or len(self.helius_api_key) < 10:
            return False, False
        
        try:
            # Use Helius to get token creation/first transactions
            url = f"https://api.helius.xyz/v0/addresses/{mint}/transactions?api-key={self.helius_api_key}&limit=10"
            r = requests.get(url, timeout=10)
            
            if r.status_code == 200:
                txns = r.json()
                if txns:
                    # Check first few transactions for bundler wallets
                    for txn in txns[:5]:
                        # Check all involved accounts
                        accounts = txn.get('accountData', [])
                        for acc in accounts:
                            addr = acc.get('account', '')
                            if addr in self.known_bundlers:
                                return False, True  # Bundler detected
                        
                        # Check for bundle patterns (multiple transfers in same tx)
                        token_transfers = txn.get('tokenTransfers', [])
                        if len(token_transfers) > 5:
                            # Multiple transfers in single tx could indicate bundling
                            return True, False
            
        except Exception as e:
            # Silently fail - bundler check is best-effort
            pass
        
        return False, False

    def _get_holder_concentration(self, mint: str) -> tuple[int, float]:
        """
        Get holder count and top holder percentage using Helius API.
        
        Returns:
            Tuple of (holder_count, top_holder_percent)
        """
        if not self.helius_api_key or len(self.helius_api_key) < 10:
            return 0, 0.0
        
        try:
            # Use Helius to get token holders
            url = f"https://api.helius.xyz/v1/mintlist?api-key={self.helius_api_key}"
            payload = {
                "query": {
                    "mints": [mint]
                },
                "options": {
                    "limit": 20
                }
            }
            r = requests.post(url, json=payload, timeout=10)
            
            if r.status_code == 200:
                data = r.json()
                # Parse holder data if available
                if data and 'result' in data:
                    result = data['result']
                    if result:
                        holder_count = len(result)
                        # Calculate top holder percentage
                        if holder_count > 0:
                            amounts = [float(h.get('amount', 0)) for h in result]
                            total = sum(amounts)
                            if total > 0:
                                top_holder_percent = (max(amounts) / total) * 100
                                return holder_count, top_holder_percent
        except Exception as e:
            pass
        
        return 0, 0.0

    def _fetch_pair_data(self, mint: str) -> Optional[dict]:
        """
        Fetch trading pair data for price/volume info.
        Uses pump.fun API or fallback sources.
        """
        try:
            # Try pump.fun coin endpoint
            r = requests.get(f"https://frontend-api.pump.fun/coins/{mint}", timeout=8)
            if r.status_code == 200:
                return r.json()
        except:
            pass
        
        return None

    def scan_graduated_candidates(self, limit: int = 30) -> list[Candidate]:
        """
        Scan for graduated pump.fun candidates.
        
        Args:
            limit: Maximum number of candidates to return
            
        Returns:
            List of Candidate objects, filtered for bundlers
        """
        print(f"\n🔍 Scanning Pump.fun graduated candidates...")
        
        candidates = []
        raw_tokens = self._fetch_graduated_tokens(limit * 2)  # Fetch extra for filtering
        
        print(f"   📊 Fetched {len(raw_tokens)} raw tokens from pump.fun")
        
        for token_data in raw_tokens:
            mint = token_data.get('mint', '')
            
            # Validate Solana address
            if not self._is_valid_solana_address(mint):
                continue
            
            symbol = token_data.get('symbol', 'UNKNOWN')
            name = token_data.get('name', symbol)
            
            # Check for bundlers (if Helius available)
            is_bundled, bundler_detected = self._check_bundler(mint)
            
            if bundler_detected:
                print(f"   🚫 Skipping {symbol}: bundler detected")
                continue
            
            if is_bundled:
                print(f"   🚫 Skipping {symbol}: bundled token")
                continue
            
            # Get holder concentration (if Helius available)
            holder_count, top_holder_percent = self._get_holder_concentration(mint)
            
            # Parse basic data from pump.fun response
            market_cap = float(token_data.get('usd_market_cap', 0) or 0)
            
            # Calculate age from created_timestamp
            age_minutes = 9999
            created = token_data.get('created_timestamp')
            if created:
                try:
                    age_seconds = time.time() - (created / 1000 if created > 1e12 else created)
                    age_minutes = max(0, age_seconds / 60)
                except:
                    pass
            
            # Get additional pair data
            pair_data = self._fetch_pair_data(mint)
            
            price = 0.0
            liquidity = 0.0
            volume_5m = 0.0
            volume_1h = 0.0
            volume_24h = 0.0
            change_5m = 0.0
            change_1h = 0.0
            buys_5m = 0
            sells_5m = 0
            
            if pair_data:
                # Try to extract pricing data
                price = float(pair_data.get('price', 0) or 0)
                
                # Virtual SOL reserves indicate liquidity
                virtual_sol = float(pair_data.get('virtual_sol_reserves', 0) or 0)
                if virtual_sol > 0:
                    # Convert to USD estimate (assuming ~$150 per SOL)
                    liquidity = virtual_sol * 150 / 1e9  # Reserves are in lamports
            
            # Create candidate
            candidate = Candidate(
                mint=mint,
                symbol=symbol,
                name=name,
                price=price,
                market_cap=market_cap,
                liquidity=liquidity,
                volume_5m=volume_5m,
                volume_1h=volume_1h,
                volume_24h=volume_24h,
                change_5m=change_5m,
                change_1h=change_1h,
                change_24h=0.0,
                buys_5m=buys_5m,
                sells_5m=sells_5m,
                buys_1h=0,
                sells_1h=0,
                age_minutes=age_minutes,
                holder_count=holder_count,
                top_holder_percent=top_holder_percent,
                is_bundled=is_bundled,
                bundler_detected=bundler_detected,
                pair_address=token_data.get('raydium_pool', ''),
                raydium_pool=token_data.get('raydium_pool', ''),
                pump_url=f"https://pump.fun/{mint}"
            )
            
            candidates.append(candidate)
            
            # Respect rate limits
            time.sleep(0.1)
            
            if len(candidates) >= limit:
                break
        
        print(f"   ✓ Found {len(candidates)} graduated candidates (filtered)")
        
        # Debug: show sample URLs
        if candidates:
            print(f"   📎 Sample pump.fun URLs:")
            for c in candidates[:3]:
                holder_info = f" | Holders: {c.holder_count}, Top: {c.top_holder_percent:.1f}%" if c.holder_count > 0 else ""
                print(f"      {c.symbol}: {c.get_pump_url()}{holder_info}")
        
        return candidates
