from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from feishubot.ai.utils.path_utils import PathUtils

logger = logging.getLogger(__name__)


class SensitiveInfoDetector:
    """Sensitive information detector and sanitizer."""

    # Patterns for sensitive information
    PATTERNS = {
        "api_key": re.compile(r"(?i)(api[_-]?key|token)\s*[:=]\s*['\"]([^'\"]+)['\"]"),
        "password": re.compile(
            r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]([^'\"]+)['\"]"
        ),
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
                sanitized = pattern.sub(
                    lambda m: "***@" + m.group(0).split("@")[1], sanitized
                )
            elif name == "phone":
                # For phone numbers, keep only the last 4 digits
                sanitized = pattern.sub(
                    lambda m: "***-***-" + m.group(0)[-4:], sanitized
                )
            else:
                # For other sensitive info, replace with ***
                sanitized = pattern.sub(
                    lambda m: (
                        m.group(0).split("=")[0] + "=***"
                        if "=" in m.group(0)
                        else "***"
                    ),
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

    def _find_legal_message_start(
        self, messages: list[dict[str, Any]]
    ) -> Optional[int]:
        """Find the first index of a legal message start."""
        for i, msg in enumerate(messages):
            role = msg.get("role")
            if role == "user" or (role == "assistant" and "tool_calls" in msg):
                return i
        return None


class SessionManager:
    def __init__(self, max_history: int = 50, store_sensitive: bool = False):
        """Initialize SessionManager with path management and security features."""
        # Resolve history directory path
        self.history_dir = self._resolve_history_dir()
        self.max_history = max_history
        self.store_sensitive = store_sensitive
        self._cache: dict[str, Session] = {}

        # Create history directory with proper permissions
        self._create_history_dir()

    def _resolve_history_dir(self) -> Path:
        """Resolve history directory path to ensure consistency."""
        # Use PathUtils to get sessions directory
        path = PathUtils.get_sessions_dir()

        # Normalize path
        resolved_path = path.resolve()
        logger.info(f"Resolved history directory: {resolved_path}")
        return resolved_path

    def _create_history_dir(self) -> None:
        """Create history directory with proper permissions."""
        try:
            # Use PathUtils to ensure directory exists
            self.history_dir = PathUtils.ensure_directory(self.history_dir)

            # Set appropriate permissions (read/write for owner only)
            if os.name == "posix":  # Unix-like systems
                # Set permissions for .feishubot directory
                feishubot_dir = self.history_dir.parent
                os.chmod(feishubot_dir, 0o700)
                # Set permissions for sessions directory
                os.chmod(self.history_dir, 0o700)
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

    def _load(self, user_id: str) -> Optional[Session]:
        """Load a session from disk."""
        try:
            history_files = list(self.history_dir.glob("*.md"))
            history_files.sort(reverse=True)

            messages = []
            created_at = None

            for file_path in history_files:
                try:
                    content = file_path.read_text(encoding="utf-8")
                    lines = content.splitlines()

                    # Parse chat blocks
                    chat_blocks = []
                    current_block = {
                        "timestamp": "",
                        "user_id": "",
                        "user_input": "",
                        "bot_response": "",
                        "complete": False,
                    }

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
                            }
                        elif line.startswith("**User (") and "):" in line:
                            # User section
                            user_id_str = line.split("(")[1].split("):")[0]
                            current_block["user_id"] = user_id_str
                        elif (
                            current_block["user_id"]
                            and not current_block["user_input"]
                            and not line.startswith("**Bot:")
                            and line.strip()
                        ):
                            # User input
                            current_block["user_input"] += line.strip() + "\n"
                        elif line.startswith("**Bot:"):
                            # Bot section
                            pass
                        elif (
                            current_block["user_id"]
                            and current_block["user_input"]
                            and not line.startswith("**User (")
                            and line.strip()
                            and line != "---"
                        ):
                            # Bot response
                            current_block["bot_response"] += line.strip() + "\n"
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
                        created_at = datetime.strptime(
                            history_files[-1].stem, "%Y-%m-%d"
                        )

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
                if SensitiveInfoDetector.detect(
                    user_input
                ) or SensitiveInfoDetector.detect(bot_response):
                    # Sanitize sensitive information
                    user_input = SensitiveInfoDetector.sanitize(user_input)
                    bot_response = SensitiveInfoDetector.sanitize(bot_response)
                    logger.info(
                        f"Sensitive information detected and sanitized for user {user_id}"
                    )

            today = datetime.now().strftime("%Y-%m-%d")
            file_path = self.history_dir / f"{today}.md"
            logger.info(f"Saving chat history to: {file_path}")

            timestamp = datetime.now().strftime("%H:%M:%S")
            content = f"### {timestamp}\n\n"
            content += f"**User ({user_id}):**\n{user_input}\n\n"
            content += f"**Bot:**\n{bot_response}\n\n"
            content += "---\n\n"

            # Write with error handling
            try:
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

    def show_chat_history(
        self, user_id: str, date_filter: Optional[str] = None
    ) -> None:
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
                    lines = content.splitlines()

                    # Parse chat blocks
                    chat_blocks = []
                    current_block = {
                        "timestamp": "",
                        "user_id": "",
                        "user_input": "",
                        "bot_response": "",
                        "complete": False,
                    }

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
                            }
                        elif line.startswith("**User (") and "):" in line:
                            # User section
                            user_id_str = line.split("(")[1].split("):")[0]
                            current_block["user_id"] = user_id_str
                        elif (
                            current_block["user_id"]
                            and not current_block["user_input"]
                            and not line.startswith("**Bot:")
                            and line.strip()
                        ):
                            # User input
                            current_block["user_input"] += line.strip() + "\n"
                        elif line.startswith("**Bot:"):
                            # Bot section
                            pass
                        elif (
                            current_block["user_id"]
                            and current_block["user_input"]
                            and not line.startswith("**User (")
                            and line.strip()
                            and line != "---"
                        ):
                            # Bot response
                            current_block["bot_response"] += line.strip() + "\n"
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

                    # Filter blocks by user_id
                    filtered_blocks = [
                        block for block in chat_blocks if block["user_id"] == user_id
                    ]

                    # Print filtered blocks
                    if filtered_blocks:
                        for block in filtered_blocks:
                            print(f"### {block['timestamp']}\n")
                            print(
                                f"**User ({block['user_id']}):**\n{block['user_input']}\n"
                            )
                            print(f"**Bot:**\n{block['bot_response']}\n")
                            print("---\n")
                    else:
                        print(
                            f"No chat history found for user {user_id} on {file_path.stem}"
                        )
                except Exception as e:
                    logger.error(f"Error reading history file {file_path}: {e}")
                    print(f"Error reading history file {file_path}: {e}")
        except Exception as e:
            logger.error(f"Error showing chat history for user {user_id}: {e}")
            print(f"Error showing chat history: {e}")

    def add_to_history(
        self, user_id: str, role: str, content: str, **kwargs: Any
    ) -> None:
        """Add a message to the session history."""
        try:
            session = self.get_or_create(user_id)
            session.add_message(role, content, **kwargs)
            session.retain_recent_legal_suffix(self.max_history)
        except Exception as e:
            logger.error(f"Error adding to history for user {user_id}: {e}")

    def get_history(
        self, user_id: str, max_messages: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """Get the session history for a user."""
        try:
            session = self.get_or_create(user_id)
            return session.get_history(max_messages or self.max_history)
        except Exception as e:
            logger.error(f"Error getting history for user {user_id}: {e}")
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

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all sessions."""
        sessions = []

        try:
            # Check cache first
            for user_id, session in self._cache.items():
                sessions.append(
                    {
                        "key": user_id,
                        "created_at": session.created_at.isoformat(),
                        "updated_at": session.updated_at.isoformat(),
                        "message_count": len(session.messages),
                    }
                )

            # Check disk for additional sessions
            history_files = list(self.history_dir.glob("*.md"))
            seen_users = {s["key"] for s in sessions}

            for file_path in history_files:
                try:
                    content = file_path.read_text(encoding="utf-8")
                    lines = content.splitlines()

                    # Parse chat blocks to find unique users
                    for line in lines:
                        if line.startswith("**User (") and "):" in line:
                            user_id = line.split("(")[1].split("):")[0]
                            if user_id not in seen_users:
                                sessions.append(
                                    {
                                        "key": user_id,
                                        "created_at": file_path.stem,
                                        "updated_at": file_path.stem,
                                        "message_count": 0,  # We don't know the exact count without loading
                                    }
                                )
                                seen_users.add(user_id)
                except Exception as e:
                    logger.error(f"Error parsing history file {file_path}: {e}")
                    continue

            return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)
        except Exception as e:
            logger.error(f"Error listing sessions: {e}")
            return []
