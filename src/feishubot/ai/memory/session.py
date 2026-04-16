from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from feishubot.ai.memory.store import JsonlMemoryStore, MemoryStore
from feishubot.ai.utils.path_utils import PathUtils

logger = logging.getLogger(__name__)

# File lock for thread-safe file operations
_file_lock = threading.RLock()


class SensitiveInfoDetector:
    """Sensitive information detector and sanitizer."""

    # Patterns for sensitive information
    PATTERNS = {
        "api_key": re.compile(r"(?i)(api[_-]?key|token)\s*[:=]\s*['\"]([^'\"]+)['\"]"),
        "password": re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]([^'\"]+)['\"]"),
        "token": re.compile(r"(?i)(token|auth[_-]?token)\s*[:=]\s*['\"]([^'\"]+)['\"]"),
        "credit_card": re.compile(r"\b(?:\d[ -]*?){13,16}\b"),
        "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
        "phone": re.compile(
            r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}\b"
        ),
    }

    @classmethod
    def detect(cls, text: str) -> bool:
        """Detect if text contains sensitive information."""
        for pattern in cls.PATTERNS.values():
            if pattern.search(text):
                return True
        return False

    @classmethod
    def sanitize(cls, text: str) -> str:
        """Sanitize sensitive information in text."""
        sanitized = text
        for name, pattern in cls.PATTERNS.items():
            if name == "email":
                # For emails, only keep the domain
                sanitized = pattern.sub(lambda m: "***@" + m.group(0).split("@")[1], sanitized)
            elif name == "phone":
                # For phone numbers, keep only the last 4 digits
                sanitized = pattern.sub(lambda m: "***-***-" + m.group(0)[-4:], sanitized)
            else:
                # For other sensitive info, replace with ***
                sanitized = pattern.sub(
                    lambda m: m.group(0).split("=")[0] + "=***" if "=" in m.group(0) else "***",
                    sanitized,
                )
        return sanitized


@dataclass
class Session:
    """A conversation session."""

    key: str  # user_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0  # Number of messages already consolidated to files

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """Add a message to the session."""
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs,
        }
        self.messages.append(msg)
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        """Return messages for LLM input, aligned to a legal tool-call boundary."""
        # Use all messages, not just unconsolidated ones
        all_messages = self.messages
        sliced = all_messages[-max_messages:]

        # Avoid starting mid-turn when possible.
        for i, message in enumerate(sliced):
            if message.get("role") == "user":
                sliced = sliced[i:]
                break

        # Drop orphan tool results at the front.
        start = self._find_legal_message_start(sliced)
        if start:
            sliced = sliced[start:]

        out: list[dict[str, Any]] = []
        for message in sliced:
            entry: dict[str, Any] = {
                "role": message["role"],
                "content": message.get("content", ""),
            }
            for key in ("tool_calls", "tool_call_id", "name", "reasoning_content"):
                if key in message:
                    entry[key] = message[key]
            out.append(entry)
        return out

    def clear(self) -> None:
        """Clear all messages and reset session to initial state."""
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()

    def retain_recent_legal_suffix(self, max_messages: int) -> None:
        """Keep a legal recent suffix, mirroring get_history boundary rules."""
        if max_messages <= 0:
            self.clear()
            return
        if len(self.messages) <= max_messages:
            return

        start_idx = max(0, len(self.messages) - max_messages)

        # If the cutoff lands mid-turn, extend backward to the nearest user turn.
        while start_idx > 0 and self.messages[start_idx].get("role") != "user":
            start_idx -= 1

        retained = self.messages[start_idx:]

        # Mirror get_history(): avoid persisting orphan tool results at the front.
        start = self._find_legal_message_start(retained)
        if start:
            retained = retained[start:]

        dropped = len(self.messages) - len(retained)
        self.messages = retained
        self.last_consolidated = max(0, self.last_consolidated - dropped)
        self.updated_at = datetime.now()

    def _find_legal_message_start(self, messages: list[dict[str, Any]]) -> int | None:
        """Find the first index of a legal message start."""
        for i, msg in enumerate(messages):
            role = msg.get("role")
            if role == "user" or (role == "assistant" and "tool_calls" in msg):
                return i
        return None


class SessionManager:
    def __init__(
        self,
        max_history: int = 50,
        store_sensitive: bool = False,
        store: MemoryStore | None = None,
    ):
        """Initialize SessionManager with path management and security features."""
        # Resolve history directory path
        self.history_dir = self._resolve_history_dir()
        self.max_history = max_history
        self.store_sensitive = store_sensitive
        self._cache: dict[str, Session] = {}

        # Create history directory with proper permissions
        self._create_history_dir()
        self._store: MemoryStore = store or JsonlMemoryStore(base_dir=self.history_dir)

    def _resolve_history_dir(self) -> Path:
        """Resolve history directory path to ensure consistency."""
        # Use PathUtils to get sessions directory
        path = PathUtils.get_sessions_dir()

        # Normalize path
        resolved_path = path.resolve()
        logger.info(f"Resolved history directory: {resolved_path}")
        return resolved_path

    def _jsonl_path(self, date_str: str) -> Path:
        return self.history_dir / f"{date_str}.jsonl"

    def _append_jsonl_record(self, record: dict[str, Any]) -> None:
        timestamp = record.get("timestamp")
        if isinstance(timestamp, str) and len(timestamp) >= 10:
            date_str = timestamp[:10]
        else:
            date_str = datetime.now().strftime("%Y-%m-%d")

        line = json.dumps(record, ensure_ascii=False)
        with _file_lock:
            self._store.append(date_str, line)

    @staticmethod
    def _parse_timestamp(raw: Any) -> datetime | None:
        if not isinstance(raw, str) or not raw.strip():
            return None
        value = raw.strip()
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        return None

    def _is_expected_history_dir(self, path: Path) -> bool:
        """校验路径是否为预期的 ~/.feishubot 会话目录

        Args:
            path: 要校验的路径

        Returns:
            bool: 如果路径是预期的会话目录，返回 True，否则返回 False
        """
        try:
            # 获取预期的会话目录路径
            expected_path = PathUtils.get_sessions_dir().resolve()
            # 解析输入路径
            resolved_path = path.resolve()
            # 检查是否匹配
            return resolved_path == expected_path
        except Exception as e:
            logger.error(f"Error checking if path is expected history directory: {e}")
            return False

    def _create_history_dir(self) -> None:
        """Create history directory with proper permissions."""
        try:
            # Use PathUtils to ensure directory exists
            self.history_dir = PathUtils.ensure_directory(self.history_dir)

            # Set appropriate permissions (read/write for owner only)
            if os.name == "posix":  # Unix-like systems
                # 仅在路径合法时执行 chmod
                if self._is_expected_history_dir(self.history_dir):
                    os.chmod(self.history_dir, 0o700)
                else:
                    logger.warning(
                        f"Skipping chmod for unexpected history directory: {self.history_dir}"
                    )
            elif os.name == "nt":  # Windows
                # Windows permissions are more complex, we'll rely on default permissions
                pass

            logger.info(f"History directory created at: {self.history_dir}")
        except Exception as e:
            logger.error(f"Failed to create history directory: {e}")
            logger.error(f"History directory path: {self.history_dir}")
            raise

    def get_or_create(self, user_id: str) -> Session:
        """Get an existing session or create a new one."""
        if user_id in self._cache:
            return self._cache[user_id]

        session = self._load(user_id)
        if session is None:
            session = Session(key=user_id)

        self._cache[user_id] = session
        return session

    def _parse_chat_blocks(self, content: str) -> list[dict[str, Any]]:
        """解析聊天区块，支持多行内容

        Args:
            content: Markdown 格式的聊天内容

        Returns:
            解析后的聊天区块列表
        """
        chat_blocks = []
        current_block = {
            "timestamp": "",
            "user_id": "",
            "user_input": "",
            "bot_response": "",
            "complete": False,
            "in_bot_section": False,
        }

        lines = content.splitlines()
        for line in lines:
            if line.startswith("### "):
                # New block
                if current_block["complete"]:
                    chat_blocks.append(current_block)
                current_block = {
                    "timestamp": line[4:],
                    "user_id": "",
                    "user_input": "",
                    "bot_response": "",
                    "complete": False,
                    "in_bot_section": False,
                }
            elif line.startswith("**User (") and "):" in line:
                # User section
                user_id_str = line.split("(")[1].split("):")[0]
                current_block["user_id"] = user_id_str
                current_block["in_bot_section"] = False
            elif (
                current_block["user_id"]
                and not current_block["in_bot_section"]
                and not line.startswith("**Bot:")
                and line.strip()
            ):
                # User input (including multi-line input)
                current_block["user_input"] += line + "\n"
            elif line.startswith("**Bot:"):
                # Bot section start
                current_block["in_bot_section"] = True
            elif (
                current_block["user_id"]
                and current_block["in_bot_section"]
                and not line.startswith("**User (")
                and line.strip()
                and line != "---"
            ):
                # Bot response (including multi-line response)
                current_block["bot_response"] += line + "\n"
            elif line == "---":
                # End of block
                if (
                    current_block["user_id"]
                    and current_block["user_input"]
                    and current_block["bot_response"]
                ):
                    current_block["complete"] = True

        # Add the last block
        if current_block["complete"]:
            chat_blocks.append(current_block)

        return chat_blocks

    def _load(self, user_id: str) -> Session | None:
        """Load a session from disk."""
        try:
            # Prefer structured JSONL records for reliable parsing.
            jsonl_files = list(self.history_dir.glob("*.jsonl"))
            jsonl_files.sort(reverse=True)
            messages: list[dict[str, Any]] = []
            created_at: datetime | None = None

            for file_path in jsonl_files:
                try:
                    date_key = file_path.stem
                    lines = self._store.read(date_key)
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        if not isinstance(record, dict):
                            continue
                        if record.get("user_id") != user_id:
                            continue

                        role = record.get("role")
                        if not isinstance(role, str) or not role:
                            continue

                        content = record.get("content", "")
                        if not isinstance(content, str):
                            content = json.dumps(content, ensure_ascii=False)

                        timestamp = record.get("timestamp")
                        message: dict[str, Any] = {
                            "role": role,
                            "content": content,
                            "timestamp": timestamp if isinstance(timestamp, str) else "",
                        }
                        kind = record.get("kind")
                        if isinstance(kind, str) and kind:
                            message["kind"] = kind
                        meta = record.get("metadata")
                        if isinstance(meta, dict) and meta:
                            message["metadata"] = meta

                        ts = self._parse_timestamp(message.get("timestamp"))
                        if ts and (created_at is None or ts < created_at):
                            created_at = ts

                        messages.append(message)
                except Exception as e:
                    logger.error(f"Error loading jsonl history from {file_path}: {e}")
                    continue

            if messages:
                messages.sort(
                    key=lambda m: self._parse_timestamp(m.get("timestamp")) or datetime.min
                )
                return Session(
                    key=user_id,
                    messages=messages,
                    created_at=created_at or datetime.now(),
                    last_consolidated=len(messages),
                )

            # Fallback to legacy markdown format for backward compatibility.
            history_files = list(self.history_dir.glob("*.md"))
            history_files.sort(reverse=True)

            messages = []
            created_at = None

            for file_path in history_files:
                try:
                    content = file_path.read_text(encoding="utf-8")

                    # Parse chat blocks using shared method
                    chat_blocks = self._parse_chat_blocks(content)

                    # Filter blocks by user_id and add to messages
                    for block in chat_blocks:
                        if block["user_id"] == user_id:
                            # Add user message
                            messages.append(
                                {
                                    "role": "user",
                                    "content": block["user_input"],
                                    "timestamp": f"{file_path.stem} {block['timestamp']}",
                                }
                            )
                            # Add assistant message
                            messages.append(
                                {
                                    "role": "assistant",
                                    "content": block["bot_response"],
                                    "timestamp": f"{file_path.stem} {block['timestamp']}",
                                }
                            )

                    # Set created_at to the earliest file date
                    if created_at is None and history_files:
                        created_at = datetime.strptime(history_files[-1].stem, "%Y-%m-%d")

                except Exception as e:
                    logger.error(f"Error loading history from {file_path}: {e}")
                    continue

            if messages:
                return Session(
                    key=user_id,
                    messages=messages,
                    created_at=created_at or datetime.now(),
                    last_consolidated=len(messages),
                )
            return None
        except Exception as e:
            logger.error(f"Error loading session for user {user_id}: {e}")
            return None

    def save_chat_history(
        self, user_input: str, bot_response: str, user_id: str, **kwargs: Any
    ) -> bool:
        """Save a chat history entry with sensitive information protection."""
        try:
            # Check for sensitive information
            if not self.store_sensitive:
                if SensitiveInfoDetector.detect(user_input) or SensitiveInfoDetector.detect(
                    bot_response
                ):
                    # Sanitize sensitive information
                    user_input = SensitiveInfoDetector.sanitize(user_input)
                    bot_response = SensitiveInfoDetector.sanitize(bot_response)
                    logger.info(f"Sensitive information detected and sanitized for user {user_id}")

            today = datetime.now().strftime("%Y-%m-%d")
            file_path = self.history_dir / f"{today}.md"
            logger.info(f"Saving chat history to: {file_path}")

            timestamp = datetime.now().strftime("%H:%M:%S")
            content = f"### {timestamp}\n\n"
            content += f"**User ({user_id}):**\n{user_input}\n\n"
            content += f"**Bot:**\n{bot_response}\n\n"
            content += "---\n\n"

            # Write with error handling and thread safety
            try:
                with _file_lock:
                    with file_path.open("a", encoding="utf-8") as f:
                        f.write(content)

                    # Set appropriate permissions for the file
                    if os.name == "posix":  # Unix-like systems
                        os.chmod(file_path, 0o600)
                    elif os.name == "nt":  # Windows
                        # Windows permissions are more complex, we'll rely on default permissions
                        pass
                logger.info(f"Successfully saved chat history to: {file_path}")
            except Exception as e:
                logger.error(f"Failed to write to history file {file_path}: {e}")
                logger.error(f"History directory exists: {self.history_dir.exists()}")
                logger.error(
                    f"History directory is writable: {os.access(self.history_dir, os.W_OK)}"
                )
                raise

            # Structured record append (preferred runtime format).
            now_iso = datetime.now().isoformat()
            self._append_jsonl_record(
                {
                    "timestamp": now_iso,
                    "user_id": user_id,
                    "role": "user",
                    "content": user_input,
                    "kind": "chat",
                    "metadata": dict(kwargs),
                }
            )
            self._append_jsonl_record(
                {
                    "timestamp": now_iso,
                    "user_id": user_id,
                    "role": "assistant",
                    "content": bot_response,
                    "kind": "chat",
                    "metadata": dict(kwargs),
                }
            )

            # Update session in cache
            session = self.get_or_create(user_id)
            session.add_message("user", user_input, **kwargs)
            session.add_message("assistant", bot_response, **kwargs)
            session.last_consolidated = len(session.messages)

            return True
        except Exception as e:
            logger.error(f"Failed to save chat history for user {user_id}: {e}")
            logger.error(f"History directory: {self.history_dir}")
            import traceback

            logger.error(f"Error traceback: {traceback.format_exc()}")
            return False

    def save_memory_event(
        self,
        *,
        user_id: str,
        role: str,
        content: str,
        kind: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Persist a structured memory event for retrieval and session continuity."""
        try:
            event_content = content
            if not self.store_sensitive and SensitiveInfoDetector.detect(event_content):
                event_content = SensitiveInfoDetector.sanitize(event_content)

            timestamp = datetime.now().isoformat()
            record = {
                "timestamp": timestamp,
                "user_id": user_id,
                "role": role,
                "content": event_content,
                "kind": kind,
                "metadata": metadata or {},
            }
            self._append_jsonl_record(record)

            session = self.get_or_create(user_id)
            session.add_message(role, event_content, kind=kind, metadata=metadata or {})
            session.retain_recent_legal_suffix(self.max_history)
            return True
        except Exception as e:
            logger.error(f"Failed to save memory event for user {user_id}: {e}")
            return False

    def show_chat_history(self, user_id: str, date_filter: str | None = None) -> None:
        """Show chat history for a user."""
        try:
            if not self.history_dir.exists():
                print("No chat history found.")
                return

            history_files = list(self.history_dir.glob("*.md"))
            if not history_files:
                print("No chat history found.")
                return

            history_files.sort(reverse=True)

            filtered_files = []
            if date_filter:
                try:
                    datetime.strptime(date_filter, "%Y-%m-%d")
                    filtered_files = [f for f in history_files if f.stem == date_filter]
                except ValueError:
                    print("Invalid date format. Please use YYYY-MM-DD format.")
                    return
            else:
                filtered_files = history_files

            if not filtered_files:
                print(f"No chat history found for date: {date_filter}")
                return

            for file_path in filtered_files:
                print(f"\n=== Chat History for {file_path.stem} ===")
                try:
                    content = file_path.read_text(encoding="utf-8")

                    # Parse chat blocks using shared method
                    chat_blocks = self._parse_chat_blocks(content)

                    # Filter blocks by user_id
                    filtered_blocks = [
                        block for block in chat_blocks if block["user_id"] == user_id
                    ]

                    # Print filtered blocks
                    if filtered_blocks:
                        for block in filtered_blocks:
                            print(f"### {block['timestamp']}\n")
                            print(f"**User ({block['user_id']}):**\n{block['user_input']}\n")
                            print(f"**Bot:**\n{block['bot_response']}\n")
                            print("---\n")
                    else:
                        print(f"No chat history found for user {user_id} on {file_path.stem}")
                except Exception as e:
                    logger.error(f"Error reading history file {file_path}: {e}")
                    print(f"Error reading history file {file_path}: {e}")
        except Exception as e:
            logger.error(f"Error showing chat history for user {user_id}: {e}")
            print(f"Error showing chat history: {e}")

    def add_to_history(self, user_id: str, role: str, content: str, **kwargs: Any) -> None:
        """Add a message to the session history."""
        try:
            session = self.get_or_create(user_id)
            session.add_message(role, content, **kwargs)
            session.retain_recent_legal_suffix(self.max_history)
        except Exception as e:
            logger.error(f"Error adding to history for user {user_id}: {e}")

    def get_history(self, user_id: str, max_messages: int | None = None) -> list[dict[str, Any]]:
        """Get the session history for a user."""
        try:
            session = self.get_or_create(user_id)
            return session.get_history(max_messages or self.max_history)
        except Exception as e:
            logger.error(f"Error getting history for user {user_id}: {e}")
            return []

    def retrieve_memories(self, user_id: str, query: str, top_k: int = 6) -> list[str]:
        """Retrieve memory snippets by simple lexical overlap + recency.

        This is a stage-1 lightweight retriever that can later be swapped for vectors.
        """
        try:
            session = self.get_or_create(user_id)
            query_tokens = set(re.findall(r"\w+", query.lower()))
            if not query_tokens:
                return []

            scored: list[tuple[float, str]] = []
            now = datetime.now()
            for msg in session.messages:
                content = msg.get("content", "")
                if not isinstance(content, str) or not content.strip():
                    continue

                content_tokens = set(re.findall(r"\w+", content.lower()))
                overlap = len(query_tokens & content_tokens)
                if overlap <= 0:
                    continue

                ts = self._parse_timestamp(msg.get("timestamp"))
                age_hours = (now - ts).total_seconds() / 3600.0 if ts else 24 * 365
                recency = 1.0 / (1.0 + age_hours / 24.0)
                score = float(overlap) + recency

                snippet = content.strip().replace("\n", " ")
                if len(snippet) > 280:
                    snippet = snippet[:280] + "..."
                scored.append((score, snippet))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [item[1] for item in scored[:top_k]]
        except Exception as e:
            logger.error(f"Error retrieving memories for user {user_id}: {e}")
            return []

    def clear_history(self, user_id: str) -> bool:
        """Clear the session history for a user."""
        try:
            if user_id in self._cache:
                session = self._cache[user_id]
                session.clear()
            return True
        except Exception as e:
            logger.error(f"Error clearing history for user {user_id}: {e}")
            return False

    def load_history(self, user_id: str, days: int = 1) -> bool:
        """Load history for a user."""
        try:
            # This method is now handled by _load and get_or_create
            self.get_or_create(user_id)
            return True
        except Exception as e:
            logger.error(f"Error loading history for user {user_id}: {e}")
            return False

    def invalidate(self, user_id: str) -> None:
        """Remove a session from the in-memory cache."""
        try:
            self._cache.pop(user_id, None)
        except Exception as e:
            logger.error(f"Error invalidating session for user {user_id}: {e}")

    def list_sessions(self, include_expired: bool = False, days: int = 30) -> list[dict[str, Any]]:
        """List all sessions.

        Args:
            include_expired: Whether to include expired sessions.
            days: Number of days after which a session is considered expired.

        Returns:
            List of session information dictionaries.
        """
        sessions = []
        cutoff_date = datetime.now() - timedelta(days=days)

        try:
            # 按日期从新到旧排序文件
            history_files = list(self.history_dir.glob("*.md"))
            history_files.sort(key=lambda x: x.stem, reverse=True)

            # 跨所有文件聚合用户数据
            user_data = {}

            # 首先处理缓存中的会话
            for user_id, session in self._cache.items():
                # 检查是否过期
                if not include_expired and session.updated_at < cutoff_date:
                    continue

                user_data[user_id] = {
                    "key": user_id,
                    "created_at": session.created_at.isoformat(),
                    "updated_at": session.updated_at.isoformat(),
                    "message_count": len(session.messages),
                }

            # 处理磁盘上的历史文件
            for file_path in history_files:
                try:
                    # 检查文件是否过期
                    file_date = datetime.strptime(file_path.stem, "%Y-%m-%d")
                    if not include_expired and file_date < cutoff_date:
                        continue

                    content = file_path.read_text(encoding="utf-8")

                    # 使用共享的解析方法
                    chat_blocks = self._parse_chat_blocks(content)

                    # 处理每个聊天区块
                    for block in chat_blocks:
                        user_id = block["user_id"]
                        if user_id and user_id not in user_data:
                            # 只处理不在缓存中的用户
                            # 计算此区块的消息数（用户+机器人）
                            block_message_count = 2

                            # 更新用户数据
                            if user_id not in user_data:
                                # 新用户，初始化数据
                                user_data[user_id] = {
                                    "key": user_id,
                                    "created_at": file_path.stem,
                                    "updated_at": f"{file_path.stem} {block['timestamp']}",
                                    "message_count": block_message_count,
                                }
                            else:
                                # 已有用户，更新数据
                                current_data = user_data[user_id]
                                # 更新消息计数
                                current_data["message_count"] += block_message_count
                                # 更新最新活动时间
                                block_datetime = datetime.strptime(
                                    f"{file_path.stem} {block['timestamp']}", "%Y-%m-%d %H:%M:%S"
                                )
                                current_updated_at = datetime.fromisoformat(
                                    current_data["updated_at"]
                                )
                                if block_datetime > current_updated_at:
                                    current_data["updated_at"] = (
                                        f"{file_path.stem} {block['timestamp']}"
                                    )
                except Exception as e:
                    logger.error(f"Error parsing history file {file_path}: {e}")
                    continue

            # 转换为列表并排序
            sessions = list(user_data.values())

            # 按 updated_at 降序排序
            def get_updated_at(session_info):
                updated_at_str = session_info.get("updated_at", "")
                try:
                    # 尝试解析为完整时间格式
                    return datetime.strptime(updated_at_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    try:
                        # 尝试解析为日期格式
                        return datetime.strptime(updated_at_str, "%Y-%m-%d")
                    except ValueError:
                        try:
                            # 尝试解析为 ISO 格式
                            return datetime.fromisoformat(updated_at_str)
                        except ValueError:
                            return datetime.min

            return sorted(sessions, key=get_updated_at, reverse=True)
        except Exception as e:
            logger.error(f"Error listing sessions: {e}")
            return []

    def cleanup_expired_sessions(self, days: int = 30) -> int:
        """Clean up expired sessions.

        Args:
            days: Number of days after which a session is considered expired.

        Returns:
            Number of expired sessions cleaned up.
        """
        try:
            expired_count = 0
            cutoff_date = datetime.now() - timedelta(days=days)
            sessions = self.list_sessions(include_expired=True)

            for session_info in sessions:
                updated_at_str = session_info.get("updated_at", "")
                try:
                    if updated_at_str:
                        # Try to parse as ISO format
                        try:
                            updated_at = datetime.fromisoformat(updated_at_str)
                        except ValueError:
                            # Try to parse as date only (YYYY-MM-DD)
                            updated_at = datetime.strptime(updated_at_str, "%Y-%m-%d")

                        if updated_at < cutoff_date:
                            user_id = session_info.get("key", "")
                            if user_id:
                                # Remove from cache
                                self.invalidate(user_id)
                                # Remove from disk
                                self._remove_session_from_disk(user_id)
                                expired_count += 1
                                logger.info(f"Cleaned up expired session: {user_id}")
                except Exception as e:
                    session_key = session_info.get("key", "unknown")
                    logger.error(f"Error checking session expiration for {session_key}: {e}")
                    continue

            return expired_count
        except Exception as e:
            logger.error(f"Error cleaning up expired sessions: {e}")
            return 0

    def _remove_session_from_disk(self, user_id: str) -> None:
        """Remove a session from disk."""
        try:
            history_files = list(self.history_dir.glob("*.md"))
            for file_path in history_files:
                try:
                    content = file_path.read_text(encoding="utf-8")
                    if f"**User ({user_id}):" in content:
                        # 首先完整解析所有区块
                        chat_blocks = self._parse_chat_blocks(content)

                        # 过滤掉目标用户的区块
                        filtered_blocks = [
                            block for block in chat_blocks if block["user_id"] != user_id
                        ]

                        # 重新构建文件内容
                        new_content = ""
                        for block in filtered_blocks:
                            # 保留完整的区块结构
                            new_content += f"### {block['timestamp']}\n\n"
                            new_content += (
                                f"**User ({block['user_id']}):**\n{block['user_input']}\n\n"
                            )
                            new_content += f"**Bot:**\n{block['bot_response']}\n\n"
                            new_content += "---\n\n"

                        # 写入更新后的内容
                        if new_content.strip():
                            try:
                                file_path.write_text(new_content, encoding="utf-8")
                            except Exception as e:
                                logger.error(f"Failed to write updated content to {file_path}: {e}")
                        else:
                            # 如果文件为空，则删除
                            try:
                                if file_path.exists():
                                    file_path.unlink()
                                    logger.info(f"Deleted empty history file: {file_path}")
                            except Exception as e:
                                logger.error(
                                    f"Failed to delete empty history file {file_path}: {e}"
                                )
                except Exception as e:
                    logger.error(f"Error processing history file {file_path}: {e}")
                    continue
        except Exception as e:
            logger.error(f"Error removing session from disk: {e}")

    def cleanup_all_sessions(self) -> int:
        """Clean up all sessions.

        Returns:
            Number of sessions cleaned up.
        """
        try:
            cleanup_count = 0
            sessions = self.list_sessions(include_expired=True)

            for session_info in sessions:
                user_id = session_info.get("key", "")
                if user_id:
                    # Remove from cache
                    self.invalidate(user_id)
                    # Remove from disk
                    self._remove_session_from_disk(user_id)
                    cleanup_count += 1
                    logger.info(f"Cleaned up session: {user_id}")

            return cleanup_count
        except Exception as e:
            logger.error(f"Error cleaning up all sessions: {e}")
            return 0
