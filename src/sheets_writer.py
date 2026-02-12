"""Google Sheets 書き込みモジュール。

生成された投稿を自動投稿用スプレッドシートに転記する。
"""

from __future__ import annotations

import logging
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

from src.config import AppConfig, DestSheetConfig
from src.post_generator import GeneratedPost

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]


def _col_letter_to_index(letter: str) -> int:
    """列文字 (A, B, ..., Z, AA, ...) を 0-indexed の列番号に変換する。"""
    result = 0
    for char in letter.upper():
        result = result * 26 + (ord(char) - ord("A") + 1)
    return result - 1


def _get_client(config: AppConfig) -> gspread.Client:
    """サービスアカウント認証で gspread クライアントを取得する。"""
    creds = Credentials.from_service_account_file(
        config.google_service_account_file,
        scopes=SCOPES,
    )
    return gspread.authorize(creds)


def _find_next_empty_row(worksheet: gspread.Worksheet, col_index: int, start_row: int) -> int:
    """指定列で次の空行を見つける。"""
    values = worksheet.col_values(col_index + 1)  # col_values は 1-indexed
    return max(len(values) + 1, start_row)


def write_posts(
    config: AppConfig,
    posts: list[GeneratedPost],
    sheet_name: str | None = None,
) -> int:
    """生成された投稿を自動投稿用スプレッドシートに書き込む。

    Args:
        config: アプリケーション設定。
        posts: 書き込む投稿のリスト。
        sheet_name: 書き込み先のシート名。None の場合は設定のデフォルトを使用。

    Returns:
        書き込んだ行数。
    """
    if not posts:
        logger.warning("書き込む投稿が0件のため、スキップします")
        return 0

    dst_config: DestSheetConfig = config.dest_sheet
    target_sheet = sheet_name or dst_config.sheet_name

    client = _get_client(config)
    spreadsheet = client.open_by_key(dst_config.spreadsheet_id)
    worksheet = spreadsheet.worksheet(target_sheet)

    # 列マッピングを取得
    col_map = {k: _col_letter_to_index(v) for k, v in dst_config.columns.items()}

    # body列を基準に次の空行を見つける
    body_col = col_map.get("body", 0)
    next_row = _find_next_empty_row(worksheet, body_col, dst_config.data_start_row)

    # バッチ更新用のセルリストを構築
    cells_to_update: list[gspread.Cell] = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for i, post in enumerate(posts):
        row = next_row + i

        if "body" in col_map:
            cells_to_update.append(
                gspread.Cell(row=row, col=col_map["body"] + 1, value=post.body)
            )

        if "reply" in col_map and post.reply:
            cells_to_update.append(
                gspread.Cell(row=row, col=col_map["reply"] + 1, value=post.reply)
            )

        if "status" in col_map:
            cells_to_update.append(
                gspread.Cell(row=row, col=col_map["status"] + 1, value="未投稿")
            )

        if "created_at" in col_map:
            cells_to_update.append(
                gspread.Cell(row=row, col=col_map["created_at"] + 1, value=now_str)
            )

    if cells_to_update:
        worksheet.update_cells(cells_to_update)

    written = len(posts)
    logger.info(
        "シート '%s' の行 %d-%d に %d 件の投稿を書き込みました",
        target_sheet,
        next_row,
        next_row + written - 1,
        written,
    )
    return written
