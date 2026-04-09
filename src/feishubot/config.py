from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class ActiveLLMConfig:
    name: str
    provider: str
    base_url: str
    api_key: str
    model: str
    chat_path: str
    timeout_seconds: float
    system_prompt: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    log_level: str = "INFO"

    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_verification_token: str = ""
    feishu_encrypt_key: str = ""

    llm_provider: str = "echo"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_chat_path: str = "/v1/chat/completions"
    llm_timeout_seconds: float = 60.0
    llm_system_prompt: str = "You are a helpful assistant."
    llm_active_model: str = ""
    llm_models_json: str = ""
    ai_tools_config_path: str = ""

    def _resolve_from_model_map(self) -> ActiveLLMConfig | None:
        raw = self.llm_models_json.strip()
        if not raw:
            return None

        try:
            models = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM_MODELS_JSON is not valid JSON: {exc}") from exc

        if not isinstance(models, dict) or not models:
            raise ValueError("LLM_MODELS_JSON must be a non-empty JSON object")

        active_name = self.llm_active_model.strip() or next(iter(models))
        active_config = models.get(active_name)
        if not isinstance(active_config, dict):
            raise ValueError(f"active model '{active_name}' not found in LLM_MODELS_JSON")

        provider = str(active_config.get("provider", "openai_compatible"))
        base_url = str(active_config.get("base_url", ""))
        api_key = str(active_config.get("api_key", ""))
        model = str(active_config.get("model", ""))
        chat_path = str(active_config.get("chat_path", "/v1/chat/completions"))
        timeout_seconds_raw = active_config.get("timeout_seconds", self.llm_timeout_seconds)
        system_prompt = str(active_config.get("system_prompt", self.llm_system_prompt))

        try:
            timeout_seconds = float(timeout_seconds_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"timeout_seconds for active model '{active_name}' must be a number"
            ) from exc

        return ActiveLLMConfig(
            name=active_name,
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model=model,
            chat_path=chat_path,
            timeout_seconds=timeout_seconds,
            system_prompt=system_prompt,
        )

    def active_llm_config(self) -> ActiveLLMConfig:
        model_map_config = self._resolve_from_model_map()
        if model_map_config is not None:
            return model_map_config

        return ActiveLLMConfig(
            name=self.llm_active_model.strip() or self.llm_model,
            provider=self.llm_provider,
            base_url=self.llm_base_url,
            api_key=self.llm_api_key,
            model=self.llm_model,
            chat_path=self.llm_chat_path,
            timeout_seconds=self.llm_timeout_seconds,
            system_prompt=self.llm_system_prompt,
        )


settings = Settings()
