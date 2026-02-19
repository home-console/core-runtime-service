"""Strategy registry and factory (plugin system)."""

from typing import Dict, Optional, Type
import asyncio

from .strategy import (
    RotationStrategy,
    RotationStrategyType,
    StrategyExecutionError,
)


class StrategyRegistry:
    """
    Registry for rotation strategies (plugin system).
    
    Supports:
    - Dynamic registration of new strategies
    - Built-in strategies (generate_new_secret, agent_push, webhook)
    - Strategy lookup by type name
    - Type-safe strategy retrieval
    """
    
    def __init__(self):
        """Initialize empty registry."""
        self._strategies: Dict[str, RotationStrategy] = {}
        self._lock = asyncio.Lock()
    
    async def register(
        self,
        strategy: RotationStrategy,
        overwrite: bool = False,
    ) -> None:
        """
        Register a rotation strategy.
        
        Args:
            strategy: Strategy instance to register
            overwrite: Allow overwriting existing strategy
        
        Raises:
            ValueError: If strategy already registered and overwrite=False
        """
        async with self._lock:
            key = strategy.strategy_type.value
            
            if key in self._strategies and not overwrite:
                raise ValueError(
                    f"Strategy '{key}' already registered. "
                    f"Use overwrite=True to replace."
                )
            
            self._strategies[key] = strategy
    
    async def register_by_type(
        self,
        strategy_type: RotationStrategyType,
        strategy: RotationStrategy,
        overwrite: bool = False,
    ) -> None:
        """
        Register a strategy by explicit type.
        
        Args:
            strategy_type: Strategy type enum value
            strategy: Strategy instance
            overwrite: Allow overwriting existing strategy
        """
        await self.register(strategy, overwrite)
    
    async def unregister(self, strategy_type: RotationStrategyType) -> bool:
        """
        Unregister a strategy.
        
        Args:
            strategy_type: Type of strategy to remove
        
        Returns:
            True if strategy was registered and removed, False otherwise
        """
        async with self._lock:
            key = strategy_type.value
            if key in self._strategies:
                del self._strategies[key]
                return True
            return False
    
    async def get(
        self,
        strategy_type: RotationStrategyType,
    ) -> Optional[RotationStrategy]:
        """
        Get a strategy by type.
        
        Args:
            strategy_type: Type of strategy to retrieve
        
        Returns:
            Strategy instance or None if not registered
        """
        async with self._lock:
            return self._strategies.get(strategy_type.value)
    
    async def get_or_fail(
        self,
        strategy_type: RotationStrategyType,
    ) -> RotationStrategy:
        """
        Get a strategy by type, raising if not found.
        
        Args:
            strategy_type: Type of strategy to retrieve
        
        Returns:
            Strategy instance
        
        Raises:
            StrategyExecutionError: If strategy not registered
        """
        strategy = await self.get(strategy_type)
        if not strategy:
            raise StrategyExecutionError(
                "registry",
                f"Strategy '{strategy_type.value}' not registered",
                error_code="strategy_not_found",
            )
        return strategy
    
    async def list_strategies(self) -> Dict[str, str]:
        """
        List all registered strategies.
        
        Returns:
            Dict mapping strategy type (string) to strategy name
        """
        async with self._lock:
            return {
                key: strategy.name
                for key, strategy in self._strategies.items()
            }
    
    async def is_registered(
        self,
        strategy_type: RotationStrategyType,
    ) -> bool:
        """
        Check if strategy is registered.
        
        Args:
            strategy_type: Type to check
        
        Returns:
            True if registered, False otherwise
        """
        async with self._lock:
            return strategy_type.value in self._strategies
    
    async def clear(self) -> None:
        """Clear all registered strategies."""
        async with self._lock:
            self._strategies.clear()
    
    def __len__(self) -> int:
        """Get number of registered strategies."""
        return len(self._strategies)
    
    def __repr__(self) -> str:
        strategies = list(self._strategies.keys())
        return f"<StrategyRegistry: {len(strategies)} strategies [{', '.join(strategies)}]>"
