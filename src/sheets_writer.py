"""Google Sheets 書き込みモジュール。

生成された投稿を自動投稿用スプレッドシートに転記する。
構成: A列=ツリー型(番号), B列=ポスト文 → 本文行+リプ行の2行で1投稿セット。
"""

from __future__ import annotations

import logging

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


def _find_next_tree_number(worksheet: gspread.Worksheet, col_index: int) -> int:
    """既存のツリー型番号の最大値を取得し、次の番号を返す。"""
    values = worksheet.col_values(col_index + 1)  # 1-indexed
    max_num = 0
    for val in values:
        val = val.strip()
        if val.isdigit():
            max_num = max(max_num, int(val))
    return max_num + 1


def write_posts(
    config: AppConfig,
    posts: list[GeneratedPost],
    sheet_name: str | None = None,
) -> int:
    """生成された投稿を自動投稿用スプレッドシートに書き込む。

    各投稿は2行で書き込まれる:
      行1: ツリー型=N, ポスト文=本文
      行2: ツリー型=N, ポスト文=リプライ文

    Args:
        config: アプリケーション設定。
        posts: 書き込む投稿のリスト。
        sheet_name: 書き込み先のシート名。None の場合は設定のデフォルトを使用。

    Returns:
        書き込んだ投稿数（行数ではなくセット数）。
    """
    if not posts:
        logger.warning("書き込む投稿が0件のため、スキップします")
        return 0

    dst_config: DestSheetConfig = config.dest_sheet
    target_sheet = sheet_name or dst_config.sheet_name

    client = _get_client(config)
    spreadsheet = client.open_by_key(dst_config.spreadsheet_id)
    worksheet = spreadsheet.worksheet(target_sheet)

    col_map = {k: _col_letter_to_index(v) for k, v in dst_config.columns.items()}
    tree_col = col_map.get("tree_type", 0)
    text_col = col_map.get("post_text", 1)

    # 次の空行とツリー番号を取得
    next_row = _find_next_empty_row(worksheet, text_col, dst_config.data_start_row)
    next_tree_num = _find_next_tree_number(worksheet, tree_col)

    # バッチ更新用のセルリストを構築
    cells_to_update: list[gspread.Cell] = []

    for i, post in enumerate(posts):
        tree_num = next_tree_num + i
        body_row = next_row + (i * 2)
        reply_row = body_row + 1

        # 本文行
        cells_to_update.append(
            gspread.Cell(row=body_row, col=tree_col + 1, value=str(tree_num))
        )
        cells_to_update.append(
            gspread.Cell(row=body_row, col=text_col + 1, value=post.body)
        )

        # リプライ行
        cells_to_update.append(
            gspread.Cell(row=reply_row, col=tree_col + 1, value=str(tree_num))
        )
        cells_to_update.append(
            gspread.Cell(row=reply_row, col=text_col + 1, value=post.reply)
        )

    if cells_to_update:
        worksheet.update_cells(cells_to_update)

    total_rows = len(posts) * 2
    logger.info(
        "シート '%s' の行 %d-%d に %d 件の投稿 (%d 行) を書き込みました "
        "(ツリー型: %d-%d)",
        target_sheet,
        next_row,
        next_row + total_rows - 1,
        len(posts),
        total_rows,
        next_tree_num,
        next_tree_num + len(posts) - 1,
    )
    return len(posts)
