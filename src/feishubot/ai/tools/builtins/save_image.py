from __future__ import annotations

import base64
import os
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from feishubot.ai.tools.base import Tool
from feishubot.config import settings


class SaveImageArguments(BaseModel):
    data_url: str = Field(
        description="Base64 data URL of the image in format data:{mime};base64,{data}",
        min_length=1,
    )
    filename: str | None = Field(
        default=None,
        description="Optional filename for the saved file; auto-generated if not provided",
    )


_MIME_TO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _parse_data_url(data_url: str) -> tuple[str, bytes]:
    if not data_url.startswith("data:"):
        raise ValueError("data_url must start with 'data:' prefix")

    header_end = data_url.index(",", 5)
    header = data_url[5:header_end]
    b64_data = data_url[header_end + 1 :]

    mime = header.split(";")[0]
    if mime not in _MIME_TO_EXT:
        raise ValueError(f"unsupported image mime type: {mime}")

    image_bytes = base64.b64decode(b64_data)
    return mime, image_bytes


def _resolve_save_dir() -> Path:
    configured = settings.image_local_dir.strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home() / ".feishubot" / "images"


def evict_oldest_images(save_dir: Path, max_count: int) -> None:
    if max_count <= 0 or not save_dir.exists():
        return
    files = sorted(save_dir.iterdir(), key=lambda f: f.stat().st_mtime)
    image_files = [
        f for f in files if f.is_file() and f.suffix in {".png", ".jpg", ".webp", ".gif"}
    ]
    while len(image_files) >= max_count:
        oldest = image_files.pop(0)
        oldest.unlink(missing_ok=True)


class SaveImageTool(Tool):
    name = "save_image"
    description = (
        "Save an image from a base64 data URL to a local file. "
        "Returns the absolute file path which can be used as a parameter for MCP services "
        "or other local processing that requires a file path."
    )
    args_model = SaveImageArguments

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        data_url = arguments["data_url"]
        filename = arguments.get("filename")

        mime, image_bytes = _parse_data_url(data_url)
        ext = _MIME_TO_EXT.get(mime, ".png")
        save_dir = _resolve_save_dir()
        os.makedirs(save_dir, exist_ok=True)

        evict_oldest_images(save_dir, settings.image_local_max_count)

        if filename:
            save_path = save_dir / filename
        else:
            save_path = save_dir / f"{uuid.uuid4().hex}{ext}"

        save_path.write_bytes(image_bytes)

        return {
            "path": str(save_path),
            "filename": save_path.name,
            "mime": mime,
            "size_bytes": len(image_bytes),
        }
