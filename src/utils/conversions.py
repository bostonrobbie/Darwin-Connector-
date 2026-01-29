"""
Centralized Contract Conversion Module
Standardizes symbol mapping and position sizing across all brokers.
"""

import logging

logger = logging.getLogger("Conversions")


class ContractConverter:
    """
    Converts TradingView webhook symbols and volumes to broker-specific formats.
    Ensures consistent position sizing across MT5, TopStep, and IBKR.
    """

    def __init__(self, config: dict):
        self.config = config

    def convert_for_mt5(self, raw_symbol: str, volume: float) -> tuple:
        """
        MT5: Apply symbol map and multiplier from config.

        Args:
            raw_symbol: Symbol from webhook (e.g., "NQ1!", "MNQ1!")
            volume: Volume from webhook

        Returns:
            Tuple of (mt5_symbol, mt5_volume)
        """
        mt5_config = self.config.get('mt5', {})
        symbol_map = mt5_config.get('symbol_map', {})

        raw_upper = raw_symbol.upper()
        mapping = symbol_map.get(raw_upper)

        if mapping:
            if isinstance(mapping, dict):
                mt5_symbol = mapping.get('name', raw_upper)
                multiplier = mapping.get('multiplier', 1.0)
            else:
                mt5_symbol = mapping
                multiplier = 1.0
        else:
            mt5_symbol = raw_upper
            multiplier = 1.0

        mt5_volume = volume * multiplier
        logger.debug(f"MT5 Conversion: {raw_symbol} -> {mt5_symbol}, vol {volume} -> {mt5_volume}")

        return mt5_symbol, mt5_volume

    def convert_for_topstep(self, raw_symbol: str, volume: float) -> tuple:
        """
        TopStep: 1 Mini = N Micros, capped at max.

        Args:
            raw_symbol: Symbol from webhook
            volume: Volume in mini contracts

        Returns:
            Tuple of (topstep_symbol, topstep_volume)
        """
        ts_config = self.config.get('topstep', {})
        micros_per_mini = ts_config.get('micros_per_mini', 5)
        max_micros = ts_config.get('max_micros', 15)

        # Determine symbol based on input
        raw_upper = raw_symbol.upper()
        if 'ES' in raw_upper:
            ts_symbol = 'MES'
        else:
            ts_symbol = 'MNQ'  # Default to MNQ for NQ and unknown

        # Convert volume: minis -> micros, capped at max
        ts_volume = min(int(volume * micros_per_mini), max_micros)
        ts_volume = max(1, ts_volume)  # At least 1 contract

        logger.debug(f"TopStep Conversion: {raw_symbol} -> {ts_symbol}, vol {volume} minis -> {ts_volume} micros")

        return ts_symbol, ts_volume

    def convert_for_ibkr(self, raw_symbol: str, volume: float) -> tuple:
        """
        IBKR: 1 Mini = N Micros, capped at max.

        Args:
            raw_symbol: Symbol from webhook
            volume: Volume in mini contracts

        Returns:
            Tuple of (ibkr_symbol, ibkr_volume)
        """
        ib_config = self.config.get('ibkr', {})
        position_sizing = ib_config.get('position_sizing', {})
        micros_per_mini = position_sizing.get('micros_per_mini', 1)
        max_micros = position_sizing.get('max_micros', 3)

        # Get symbol map
        symbol_map = ib_config.get('symbol_map', {})

        # Clean TradingView ticker format
        raw_upper = raw_symbol.upper()
        clean_symbol = raw_upper.replace('1!', '').replace('2!', '')

        # Apply symbol map
        ib_symbol = symbol_map.get(raw_upper, symbol_map.get(clean_symbol, clean_symbol))

        # Convert volume: minis -> micros, capped at max
        ib_volume = min(int(volume * micros_per_mini), max_micros)
        ib_volume = max(1, ib_volume)  # At least 1 contract

        logger.debug(f"IBKR Conversion: {raw_symbol} -> {ib_symbol}, vol {volume} minis -> {ib_volume} micros")

        return ib_symbol, ib_volume

    def convert_all(self, raw_symbol: str, volume: float) -> dict:
        """
        Convert symbol and volume for all brokers at once.

        Args:
            raw_symbol: Symbol from webhook
            volume: Volume from webhook

        Returns:
            Dict with conversions for each broker
        """
        mt5_symbol, mt5_volume = self.convert_for_mt5(raw_symbol, volume)
        ts_symbol, ts_volume = self.convert_for_topstep(raw_symbol, volume)
        ib_symbol, ib_volume = self.convert_for_ibkr(raw_symbol, volume)

        return {
            'mt5': {'symbol': mt5_symbol, 'volume': mt5_volume},
            'topstep': {'symbol': ts_symbol, 'volume': ts_volume},
            'ibkr': {'symbol': ib_symbol, 'volume': ib_volume}
        }

    @staticmethod
    def clean_tradingview_symbol(symbol: str) -> str:
        """Remove TradingView-specific suffixes like 1! and 2!"""
        return symbol.upper().replace('1!', '').replace('2!', '')

    @staticmethod
    def is_futures_symbol(symbol: str) -> bool:
        """Check if symbol looks like a futures contract."""
        upper = symbol.upper()
        futures_indicators = ['1!', '2!', 'NQ', 'ES', 'MNQ', 'MES', 'GC', 'CL', 'RTY']
        return any(ind in upper for ind in futures_indicators)
