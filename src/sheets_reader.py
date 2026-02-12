"""Google Sheets 読み取りモジュール。

参考用スプレッドシートから投稿データを読み込む。
複数シート対応: シート名を指定して読み込み先を切り替え可能。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import gspread
from google.oauth2.service_account import Credentials

from src.config import AppConfig, SourceSheetConfig

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]


@dataclass
class ReferencePost:
    """参考用投稿データ。"""

    body: str
    reply: str
    row_number: int
    extra: dict | None = None


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


def read_reference_posts(
    config: AppConfig,
    sheet_name: str | None = None,
) -> list[ReferencePost]:
    """参考用スプレッドシートから投稿データを読み込む。

    Args:
        config: アプリケーション設定。
        sheet_name: 読み込むシート名。None の場合は設定のデフォルトを使用。
                    将来的にシートごとに投稿種類を分ける場合に使用。

    Returns:
        参考用投稿のリスト。
    """
    src_config: SourceSheetConfig = config.source_sheet
    target_sheet = sheet_name or src_config.sheet_name

    client = _get_client(config)
    spreadsheet = client.open_by_key(src_config.spreadsheet_id)
    worksheet = spreadsheet.worksheet(target_sheet)

    all_values = worksheet.get_all_values()

    body_col = _col_letter_to_index(src_config.columns["body"])
    reply_col = _col_letter_to_index(src_config.columns["reply"])

    # 設定された列以外の追加列を検出
    known_cols = {"body", "reply"}
    extra_cols = {
        k: _col_letter_to_index(v)
        for k, v in src_config.columns.items()
        if k not in known_cols
    }

    posts: list[ReferencePost] = []
    for row_idx, row in enumerate(all_values):
        row_number = row_idx + 1  # 1-indexed
        if row_number < src_config.data_start_row:
            continue

        body = row[body_col].strip() if body_col < len(row) else ""
        reply = row[reply_col].strip() if reply_col < len(row) else ""

        if not body:
            continue

        extra = {}
        for col_name, col_idx in extra_cols.items():
            extra[col_name] = row[col_idx].strip() if col_idx < len(row) else ""

        posts.append(ReferencePost(
            body=body,
            reply=reply,
            row_number=row_number,
            extra=extra if extra else None,
        ))

    logger.info("シート '%s' から %d 件の参考投稿を読み込みました", target_sheet, len(posts))
    return posts


def list_sheet_names(config: AppConfig) -> list[str]:
    """参考用スプレッドシートのシート名一覧を返す。

    投稿種類ごとにシートを分けている場合に、利用可能なシートを確認するために使用。
    """
    client = _get_client(config)
    spreadsheet = client.open_by_key(config.source_sheet.spreadsheet_id)
    return [ws.title for ws in spreadsheet.worksheets()]
