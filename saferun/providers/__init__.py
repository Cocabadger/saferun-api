"""
Provider manager for SafeRun API.
"""

from typing import Dict, Any, Optional
from saferun.models.models import ProviderType
from saferun.providers.github import GitHubProvider
from saferun.providers.notion import NotionProvider
from saferun.utils.errors import ProviderError
import structlog

logger = structlog.get_logger(__name__)


class ProviderManager:
    """Manages different provider integrations."""
    
    def __init__(self):
        self._providers = {}
        self._initialize_providers()
    
    def _initialize_providers(self):
        """Initialize all available providers."""
        try:
            self._providers[ProviderType.GITHUB] = GitHubProvider()
            logger.info("GitHub provider initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize GitHub provider: {e}")
        
        try:
            self._providers[ProviderType.NOTION] = NotionProvider()
            logger.info("Notion provider initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize Notion provider: {e}")
    
    def get_provider(self, provider_type: ProviderType):
        """Get a provider instance."""
        if provider_type not in self._providers:
            raise ProviderError(
                message=f"Provider '{provider_type}' is not available",
                provider=provider_type,
                details={"available_providers": list(self._providers.keys())}
            )
        
        return self._providers[provider_type]
    
    def is_provider_available(self, provider_type: ProviderType) -> bool:
        """Check if a provider is available."""
        return provider_type in self._providers
    
    def list_available_providers(self) -> list:
        """List all available providers."""
        return list(self._providers.keys())
    
    def add_provider(self, provider_type: ProviderType, provider_instance):
        """Add a custom provider instance."""
        self._providers[provider_type] = provider_instance
        logger.info(f"Added custom provider: {provider_type}")
    
    def remove_provider(self, provider_type: ProviderType):
        """Remove a provider."""
        if provider_type in self._providers:
            del self._providers[provider_type]
            logger.info(f"Removed provider: {provider_type}")


# Global provider manager instance
provider_manager = ProviderManager()