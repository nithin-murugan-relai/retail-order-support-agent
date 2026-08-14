from __future__ import annotations

import asyncio
import argparse
from collections.abc import Callable
import sys
from typing import TextIO

from dotenv import load_dotenv

from retail_support.agent import stream_agent_response
from retail_support.sessions import (
    append_message,
    create_session,
    read_messages,
    session_id_from_log_name,
    session_path,
)


EXIT_COMMANDS = {"exit", "quit", "q"}


async def chat(
    log_name: str | None = None,
    input_func: Callable[[str], str] = input,
    output_stream: TextIO | None = None,
) -> str:
    load_dotenv()
    output = output_stream or sys.stdout
    session_id = session_id_from_log_name(log_name) if log_name else None
    session = create_session(session_id=session_id, overwrite=log_name is not None)
    log_path = session_path(session.id)

    print("Northwind Retail Support", file=output)
    print(f"Session: {session.id}", file=output)
    print(f"Log: {log_path}", file=output)
    print("Type exit, quit, or q to end the chat.", file=output)

    while True:
        try:
            user_text = input_func("\nYou: ")
        except EOFError:
            print(file=output)
            break

        user_text = user_text.strip()
        if not user_text:
            continue
        if user_text.lower() in EXIT_COMMANDS:
            break

        append_message(session.id, "user", user_text)
        messages = read_messages(session.id)
        chunks: list[str] = []

        print("\nAgent: ", end="", file=output, flush=True)
        async for delta in stream_agent_response(messages):
            chunks.append(delta)
            print(delta, end="", file=output, flush=True)
        print(file=output)

        assistant_text = "".join(chunks).strip()
        if assistant_text:
            append_message(session.id, "assistant", assistant_text)

    print(f"\nSaved conversation log to {log_path}", file=output)
    return str(log_path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chat with the Northwind Retail support agent.")
    parser.add_argument(
        "log_name",
        nargs="?",
        help="Optional session log file name, saved as logs/<name>.jsonl. Existing named logs are overwritten.",
    )
    return parser.parse_args(argv)


def run() -> None:
    args = parse_args()
    asyncio.run(chat(log_name=args.log_name))


def main() -> None:
    run()


if __name__ == "__main__":
    main()
