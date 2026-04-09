from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional


class SessionManager:
    def __init__(self, history_dir: str = "history", max_history: int = 50):
        self.history_dir = Path(history_dir)
        self.history_dir.mkdir(exist_ok=True)
        self.chat_history: List[Dict[str, str]] = []
        self.max_history = max_history
    
    def save_chat_history(self, user_input: str, bot_response: str, user_id: str) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        file_path = self.history_dir / f"{today}.md"
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        content = f"### {timestamp}\n\n"
        content += f"**User ({user_id}):**\n{user_input}\n\n"
        content += f"**Bot:**\n{bot_response}\n\n"
        content += "---\n\n"
        
        file_path.open("a", encoding="utf-8").write(content)
    
    def show_chat_history(self, user_id: str, date_filter: Optional[str] = None) -> None:
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
                print(f"Invalid date format. Please use YYYY-MM-DD format.")
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
                user_chat_lines = []
                in_user_chat = False
                
                for line in lines:
                    if line.startswith("### "):
                        in_user_chat = False
                        user_chat_lines.append(line)
                    elif line.startswith("**User (") and f"({user_id}):" in line:
                        in_user_chat = True
                        user_chat_lines.append(line)
                    elif in_user_chat or line.startswith("**Bot:") or line == "---":
                        user_chat_lines.append(line)
                
                filtered_content = "\n".join(user_chat_lines)
                if filtered_content.strip():
                    print(filtered_content)
                else:
                    print(f"No chat history found for user {user_id} on {file_path.stem}")
            except Exception as e:
                print(f"Error reading history file {file_path}: {e}")
    
    def add_to_history(self, role: str, content: str) -> None:
        self.chat_history.append({"role": role, "content": content})
        if len(self.chat_history) > self.max_history:
            self.chat_history = self.chat_history[-self.max_history:]
    
    def get_history(self) -> List[Dict[str, str]]:
        return self.chat_history
    
    def clear_history(self) -> None:
        self.chat_history = []
