"""Threads 自動投稿作成ツール メインスクリプト。

参考投稿を読み込み → Claude APIで新規投稿を生成 → 自動投稿用スプシへ転記。
CLIから実行可能。cronでの定期実行にも対応。
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.config import load_config
from src.post_generator import generate_posts
from src.sheets_reader import list_sheet_names, read_reference_posts
from src.sheets_writer import write_posts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Threads 自動投稿作成ツール: 参考投稿をもとにClaude APIで新規投稿を生成し、スプレッドシートに転記します。",
    )
    parser.add_argument(
        "-c", "--config",
        help="設定ファイル (config.yaml) のパス。デフォルトはプロジェクトルートの config.yaml",
    )
    parser.add_argument(
        "-n", "--count",
        type=int,
        help="生成する投稿数 (デフォルトは config.yaml の posts_per_run)",
    )
    parser.add_argument(
        "-s", "--sheet",
        help="参考用スプレッドシートの読み込みシート名 (デフォルトは config.yaml の sheet_name)",
    )
    parser.add_argument(
        "--dest-sheet",
        help="転記先スプレッドシートのシート名 (デフォルトは config.yaml の dest_sheet.sheet_name)",
    )
    parser.add_argument(
        "--list-sheets",
        action="store_true",
        help="参考用スプレッドシートのシート名一覧を表示して終了",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="生成した投稿を表示するだけで、スプレッドシートには書き込まない",
    )

    parsed = parser.parse_args(args)

    # 設定読み込み
    from pathlib import Path
    config_path = Path(parsed.config) if parsed.config else None
    config = load_config(config_path)

    # シート一覧モード
    if parsed.list_sheets:
        sheets = list_sheet_names(config)
        print("参考用スプレッドシートのシート一覧:")
        for name in sheets:
            print(f"  - {name}")
        return 0

    # 1. 参考投稿の読み込み
    logger.info("=== 参考投稿の読み込み ===")
    reference_posts = read_reference_posts(config, sheet_name=parsed.sheet)

    if not reference_posts:
        logger.error("参考投稿が見つかりませんでした。スプレッドシートの設定を確認してください。")
        return 1

    logger.info("参考投稿: %d 件を読み込みました", len(reference_posts))

    # 2. 投稿の生成
    logger.info("=== 投稿の生成 ===")
    generated = generate_posts(config, reference_posts, count=parsed.count)

    if not generated:
        logger.error("投稿の生成に失敗しました")
        return 1

    logger.info("生成された投稿: %d 件", len(generated))

    # 生成結果の表示
    for i, post in enumerate(generated, 1):
        print(f"\n--- 生成投稿 {i} ---")
        print(f"本文: {post.body}")
        if post.reply:
            print(f"リプライ: {post.reply}")

    # 3. スプレッドシートへの転記
    if parsed.dry_run:
        logger.info("=== ドライラン: 転記をスキップします ===")
        return 0

    logger.info("=== スプレッドシートへの転記 ===")
    written = write_posts(config, generated, sheet_name=parsed.dest_sheet)
    logger.info("転記完了: %d 件をスプレッドシートに書き込みました", written)

    return 0


if __name__ == "__main__":
    sys.exit(main())
