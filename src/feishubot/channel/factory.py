from __future__ import annotations

from feishubot.channel.base import Channel
from feishubot.channel.feishu import FeishuChannel
from feishubot.config import settings


def create_channel(channel_name: str) -> Channel:
    resolved = channel_name.strip().lower()
    if resolved == "feishu":
        return FeishuChannel(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret,
        )
    raise ValueError(f"unsupported channel: {channel_name}")


def create_default_channel() -> Channel:
    return create_channel(settings.default_channel)
