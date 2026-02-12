"""Claude API を使った投稿生成モジュール。

参考投稿のトーンや内容を分析し、新しいThreads投稿を自動生成する。
ユーザーのプロジェクト設定に準拠した投稿ルールに従う。
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
あなたはスレッズ（Threads）の投稿を作成する専門アシスタントです。
ユーザーから提供される参考投稿を分析し、同じテイストで新しい投稿を作成してください。

# 投稿ルール

## 構成
- 必ず「本文」と「リプライ文」の2連投稿にする
- 本文の最後は「なぜなら、」「その理由は、」「それは、」など、続きが気になる言葉で切る
- リプライ文の最後にフォロー訴求を入れる

## 文体・口調
- 敬語で統一する（「〜です」「〜ますよ」）
- 小学生でもわかるような簡単な言葉を使う
- 1行目は読者の手が止まるようなフック（問いかけ、断言、共感など）にする
- 冒頭に【】は使わない

## 表現ルール
- 「○○な人ほど」系の投稿では、スピリチュアルな特別感を出す
  例：霊格が高い女性ほど / 魂の器が大きい人ほど / 器の大きい女性ほど / 魂の格が高い女性ほど / 魂のステージが高い人ほど
- 固有名詞（人名・職業名・ブランド名）は出さない
- 絵文字は🕊️✨のみ使用する（リプライ文のフォロー訴求付近に1回）

## テーマの方向性
- 40代女性の人生の転機・リセット
- 疲れやすい人・繊細な人への肯定
- 頑張らなくていい・無理しなくていい系のメッセージ
- 自分を大切にする・自分が主役になる
- 心が疲れた時の過ごし方
"""

DEFAULT_USER_PROMPT_TEMPLATE = """\
以下の参考投稿をもとに、新しいThreads投稿を{count}件作成してください。
参考投稿のテイスト・トーン・構成を分析し、同じ雰囲気で異なる切り口の投稿を作ってください。

### 参考投稿
{reference_posts}

### 出力形式
以下のJSON配列形式で出力してください。他の説明文は不要です。
本文は「なぜなら、」「その理由は、」「それは、」など続きが気になる言葉で終わらせてください。
リプライ文の最後にはフォロー訴求（🕊️✨付き）を入れてください。

```json
[
  {{
    "body": "投稿本文（続きが気になる形で切る）",
    "reply": "リプライ文（フォロー訴求で締める）"
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
        part = f"--- 参考投稿 {i} ---\n【本文】\n{post.body}"
        if post.reply:
            part += f"\n【リプライ】\n{post.reply}"
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
