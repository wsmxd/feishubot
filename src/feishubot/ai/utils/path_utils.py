from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class PathUtils:
    """路径工具类，用于处理应用程序的各种路径配置"""

    @staticmethod
    def get_feishubot_dir() -> Path:
        """获取 FeishuBot 的主目录路径

        Returns:
            Path: FeishuBot 主目录路径 (~/.feishubot/)
        """
        user_home = Path.home()
        feishubot_dir = user_home / ".feishubot"
        return feishubot_dir

    @staticmethod
    def get_sessions_dir() -> Path:
        """获取会话存储目录路径

        Returns:
            Path: 会话存储目录路径 (~/.feishubot/sessions/)
        """
        feishubot_dir = PathUtils.get_feishubot_dir()
        sessions_dir = feishubot_dir / "sessions"
        return sessions_dir

    @staticmethod
    def ensure_directory(path: Path) -> Path:
        """确保目录存在，如果不存在则创建

        Args:
            path: 要确保存在的目录路径

        Returns:
            Path: 确保存在的目录路径
        """
        try:
            path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Directory ensured: {path}")
            return path
        except OSError as e:
            logger.error(f"Failed to ensure directory {path}: {e}")
            raise
