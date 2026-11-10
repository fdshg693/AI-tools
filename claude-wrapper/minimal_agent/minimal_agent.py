"""Claude Agent SDK の最小動作確認スクリプト。

カタログの default モデルに一回限りのクエリを送り、応答テキストと終了ステータスを表示する。
認証は `claude` CLI のログイン状態、または環境変数 ANTHROPIC_API_KEY に依存する。
"""

import asyncio
import sys
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

_WRAPPER_ROOT = Path(__file__).resolve().parents[1]
if str(_WRAPPER_ROOT) not in sys.path:
    sys.path.insert(0, str(_WRAPPER_ROOT))

from util.models import load_catalog  # noqa: E402

try:
    MODEL = load_catalog().default_id
except (OSError, ValueError) as exc:
    raise SystemExit(f"モデルカタログを読めません: {exc}") from exc
PROMPT = "自己紹介を1文でお願いします。"


async def main() -> None:
    options = ClaudeAgentOptions(
        model=MODEL,
        max_turns=1,
    )

    async for message in query(prompt=PROMPT, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    print(block.text)
        elif isinstance(message, ResultMessage):
            print(f"終了: {message.subtype}")
            if message.subtype != "success":
                raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
