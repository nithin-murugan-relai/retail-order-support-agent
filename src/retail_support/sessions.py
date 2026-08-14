from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{8,80}$")


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str
    created_at: str


@dataclass(frozen=True)
class ChatSession:
    id: str
    created_at: str
    updated_at: str
    message_count: int
    preview: str


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def logs_dir() -> Path:
    return Path(os.environ.get("RETAIL_SUPPORT_LOG_DIR", "logs")).resolve()


def ensure_logs_dir() -> Path:
    directory = logs_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def validate_session_id(session_id: str) -> str:
    if not SESSION_ID_PATTERN.match(session_id):
        raise ValueError("session id contains unsupported characters")
    return session_id


def session_path(session_id: str) -> Path:
    return ensure_logs_dir() / f"{validate_session_id(session_id)}.jsonl"


def session_id_from_log_name(log_name: str) -> str:
    name = Path(log_name).name
    if name.endswith(".jsonl"):
        name = name.removesuffix(".jsonl")
    return validate_session_id(name)


def create_session(session_id: str | None = None, overwrite: bool = False) -> ChatSession:
    session_id = validate_session_id(session_id) if session_id else f"session-{uuid4().hex[:16]}"
    timestamp = utc_now()
    path = session_path(session_id)
    mode = "w" if overwrite else "x"
    with path.open(mode, encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "session",
                    "id": session_id,
                    "created_at": timestamp,
                }
            )
            + "\n"
        )
    return ChatSession(
        id=session_id,
        created_at=timestamp,
        updated_at=timestamp,
        message_count=0,
        preview="New session",
    )


def delete_session(session_id: str) -> bool:
    path = session_path(session_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def append_message(session_id: str, role: str, content: str) -> ChatMessage:
    if role not in {"user", "assistant"}:
        raise ValueError("role must be user or assistant")
    message = ChatMessage(role=role, content=content, created_at=utc_now())
    with session_path(session_id).open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "message",
                    "role": message.role,
                    "content": message.content,
                    "created_at": message.created_at,
                },
                ensure_ascii=True,
            )
            + "\n"
        )
    return message


def read_messages(session_id: str) -> list[ChatMessage]:
    path = session_path(session_id)
    if not path.exists():
        raise FileNotFoundError(session_id)

    messages: list[ChatMessage] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("type") != "message":
                continue
            messages.append(
                ChatMessage(
                    role=str(event["role"]),
                    content=str(event["content"]),
                    created_at=str(event["created_at"]),
                )
            )
    return messages


def list_sessions() -> list[ChatSession]:
    ensure_logs_dir()
    sessions: list[ChatSession] = []
    for path in sorted(logs_dir().glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True):
        session_id = path.stem
        created_at = datetime.fromtimestamp(path.stat().st_ctime, UTC).isoformat()
        updated_at = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
        messages = read_messages(session_id)
        if messages:
            created_at = messages[0].created_at
            updated_at = messages[-1].created_at
        preview = next((message.content for message in messages if message.role == "user"), "New session")
        sessions.append(
            ChatSession(
                id=session_id,
                created_at=created_at,
                updated_at=updated_at,
                message_count=len(messages),
                preview=preview[:96],
            )
        )
    return sessions
