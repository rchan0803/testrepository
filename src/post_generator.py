"""Claude API を使った投稿生成モジュール。

参考投稿のトーンや内容を分析し、新しいThreads投稿を自動生成する。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import anthropic

from src.config import AppConfig
from src.sheets_reader import ReferencePost

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """\
あなたはThreads（Meta社のSNS）の投稿を作成するプロのコピーライターです。
ユーザーから提供される参考投稿を分析し、そのトーン・文体・テーマに沿った新しい投稿を作成してください。

### ルール
- Threadsの投稿は最大500文字です。簡潔かつインパクトのある文章を心がけてください。
- 参考投稿にリプライ（連投）がある場合、同様にリプライ付きの投稿を作成してください。
- リプライも最大500文字です。
- 参考投稿の丸コピーは避け、同じテーマ・トーンで異なる切り口の投稿を作成してください。
- 絵文字や改行は参考投稿のスタイルに合わせてください。
- ハッシュタグは参考投稿で使われている場合のみ、同様に付けてください。
"""

DEFAULT_USER_PROMPT_TEMPLATE = """\
以下の参考投稿をもとに、新しいThreads投稿を{count}件作成してください。

### 参考投稿
{reference_posts}

### 出力形式
以下のJSON配列形式で出力してください。他の説明文は不要です。
```json
[
  {{
    "body": "投稿本文",
    "reply": "リプライ文（不要な場合は空文字）"
  }}
]
```
"""


@dataclass
class GeneratedPost:
    """生成された投稿データ。"""

    body: str
    reply: str


def _format_reference_posts(posts: list[ReferencePost]) -> str:
    """参考投稿をプロンプト用にフォーマットする。"""
    parts = []
    for i, post in enumerate(posts, 1):
        part = f"--- 参考投稿 {i} ---\n本文: {post.body}"
        if post.reply:
            part += f"\nリプライ: {post.reply}"
        parts.append(part)
    return "\n\n".join(parts)


def generate_posts(
    config: AppConfig,
    reference_posts: list[ReferencePost],
    count: int | None = None,
) -> list[GeneratedPost]:
    """Claude API を使って新しい投稿を生成する。

    Args:
        config: アプリケーション設定。
        reference_posts: 参考投稿のリスト。
        count: 生成する投稿数。None の場合は設定のデフォルト値を使用。

    Returns:
        生成された投稿のリスト。
    """
    num_posts = count or config.generation.posts_per_run

    if not reference_posts:
        logger.warning("参考投稿が0件のため、生成をスキップします")
        return []

    client = anthropic.Anthropic(api_key=config.claude.api_key)

    system_prompt = DEFAULT_SYSTEM_PROMPT
    if config.generation.max_body_length != 500 or config.generation.max_reply_length != 500:
        system_prompt += (
            f"\n- 本文の最大文字数: {config.generation.max_body_length}文字"
            f"\n- リプライの最大文字数: {config.generation.max_reply_length}文字"
        )

    user_prompt_template = config.generation.prompt_template or DEFAULT_USER_PROMPT_TEMPLATE
    user_prompt = user_prompt_template.format(
        count=num_posts,
        reference_posts=_format_reference_posts(reference_posts),
    )

    logger.info(
        "Claude API で %d 件の投稿を生成します (参考投稿: %d 件, モデル: %s)",
        num_posts,
        len(reference_posts),
        config.claude.model,
    )

    message = client.messages.create(
        model=config.claude.model,
        max_tokens=config.claude.max_tokens,
        temperature=config.claude.temperature,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    response_text = message.content[0].text
    return _parse_response(response_text, num_posts)


def _parse_response(response_text: str, expected_count: int) -> list[GeneratedPost]:
    """Claude API のレスポンスをパースして GeneratedPost のリストに変換する。"""
    # JSON部分を抽出 (```json ... ``` で囲まれている場合に対応)
    text = response_text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1]
        text = text.split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1]
        text = text.split("```", 1)[0]

    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.error("Claude APIのレスポンスをJSONとしてパースできませんでした:\n%s", response_text)
        raise ValueError(f"JSONパースエラー: {response_text[:200]}")

    if not isinstance(data, list):
        raise ValueError(f"レスポンスがJSON配列ではありません: {type(data)}")

    posts = []
    for item in data:
        if not isinstance(item, dict):
            logger.warning("不正なアイテムをスキップ: %s", item)
            continue
        posts.append(GeneratedPost(
            body=item.get("body", ""),
            reply=item.get("reply", ""),
        ))

    if len(posts) != expected_count:
        logger.warning(
            "期待した投稿数 (%d) と実際の投稿数 (%d) が異なります",
            expected_count,
            len(posts),
        )

    return posts
