"""Provider adapters that translate between plural types and vendor APIs.

Examples:
    >>> from plural.providers import OpenAIProvider, AnthropicProvider, GoogleProvider
    >>> OpenAIProvider.__name__
    'OpenAIProvider'
"""

from __future__ import annotations

from plural.providers.anthropic import AnthropicProvider
from plural.providers.azure import AzureOpenAIProvider
from plural.providers.base import Provider, ProviderConfig
from plural.providers.bedrock import BedrockProvider
from plural.providers.google import GoogleProvider
from plural.providers.openai_compatible import (
    BasetenProvider,
    DeepSeekProvider,
    FireworksProvider,
    GroqProvider,
    MetaProvider,
    MistralProvider,
    MoonshotProvider,
    OpenAICompatible,
    OpenAIProvider,
    QwenProvider,
    TogetherProvider,
    XAIProvider,
    ZhipuProvider,
)
from plural.providers.openai_responses import OpenAIResponsesProvider

__all__ = [
    "AnthropicProvider",
    "AzureOpenAIProvider",
    "BasetenProvider",
    "BedrockProvider",
    "DeepSeekProvider",
    "FireworksProvider",
    "GoogleProvider",
    "GroqProvider",
    "MetaProvider",
    "MistralProvider",
    "MoonshotProvider",
    "OpenAICompatible",
    "OpenAIProvider",
    "OpenAIResponsesProvider",
    "Provider",
    "ProviderConfig",
    "QwenProvider",
    "TogetherProvider",
    "XAIProvider",
    "ZhipuProvider",
]
