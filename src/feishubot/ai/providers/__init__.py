from feishubot.ai.core.errors import ProviderNotFoundError
from feishubot.ai.providers.base import ModelProvider
from feishubot.ai.providers.echo import EchoProvider
from feishubot.ai.providers.openai_compatible.client import OpenAICompatibleProvider
from feishubot.config import ActiveLLMConfig, settings


def create_provider(config: ActiveLLMConfig) -> ModelProvider:
    if config.provider == "openai_compatible":
        return OpenAICompatibleProvider(
            base_url=config.base_url,
            api_key=config.api_key,
            model=config.model,
            chat_path=config.chat_path,
            timeout_seconds=config.timeout_seconds,
        )

    if config.provider == "echo":
        return EchoProvider()

    raise ProviderNotFoundError(f"unsupported LLM provider: {config.provider}")


def create_active_provider() -> ModelProvider:
    return create_provider(settings.active_llm_config())


__all__ = [
    "EchoProvider",
    "ModelProvider",
    "OpenAICompatibleProvider",
    "create_active_provider",
    "create_provider",
]
