"""Google Sheets 読み取りモジュール。

参考用スプレッドシートから投稿データを読み込む。
構成: A列=種別(投稿1/リプ1), B列=テキスト → 2行で1投稿セット。
複数シート対応: シート名を指定して投稿種類ごとに読み込み先を切り替え可能。
"""

from __future__ import annotations

import logging
import re
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
    """参考用投稿データ（本文 + リプライのペア）。"""

    body: str
    reply: str
    post_number: int


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


def _parse_label(label: str) -> tuple[str, int] | None:
    """種別ラベルから種類と番号を抽出する。

    例: "投稿1" → ("投稿", 1), "リプ3" → ("リプ", 3)
    """
    match = re.match(r"(投稿|リプ)\s*(\d+)", label.strip())
    if not match:
        return None
    return match.group(1), int(match.group(2))


def read_reference_posts(
    config: AppConfig,
    sheet_name: str | None = None,
) -> list[ReferencePost]:
    """参考用スプレッドシートから投稿データを読み込む。

    A列の種別ラベル（投稿N / リプN）をもとに、同じ番号の投稿+リプをペアにする。

    Args:
        config: アプリケーション設定。
        sheet_name: 読み込むシート名。None の場合は設定のデフォルトを使用。

    Returns:
        参考用投稿のリスト。
    """
    src_config: SourceSheetConfig = config.source_sheet
    target_sheet = sheet_name or src_config.sheet_name

    client = _get_client(config)
    spreadsheet = client.open_by_key(src_config.spreadsheet_id)
    worksheet = spreadsheet.worksheet(target_sheet)

    all_values = worksheet.get_all_values()

    label_col = _col_letter_to_index(src_config.columns["label"])
    text_col = _col_letter_to_index(src_config.columns["text"])

    # 投稿番号ごとに本文とリプを蓄積
    bodies: dict[int, str] = {}
    replies: dict[int, str] = {}

    for row_idx, row in enumerate(all_values):
        row_number = row_idx + 1
        if row_number < src_config.data_start_row:
            continue

        label = row[label_col].strip() if label_col < len(row) else ""
        text = row[text_col].strip() if text_col < len(row) else ""

        if not label or not text:
            continue

        parsed = _parse_label(label)
        if not parsed:
            logger.debug("行 %d: 不明なラベル '%s' をスキップ", row_number, label)
            continue

        kind, num = parsed
        if kind == "投稿":
            bodies[num] = text
        elif kind == "リプ":
            replies[num] = text

    # 番号順にペアを組み立て
    all_numbers = sorted(set(bodies.keys()) | set(replies.keys()))
    posts: list[ReferencePost] = []
    for num in all_numbers:
        body = bodies.get(num, "")
        reply = replies.get(num, "")
        if body:
            posts.append(ReferencePost(body=body, reply=reply, post_number=num))
        else:
            logger.warning("投稿番号 %d: 本文がありません（リプのみ）。スキップします", num)

    logger.info("シート '%s' から %d 件の参考投稿を読み込みました", target_sheet, len(posts))
    return posts


def list_sheet_names(config: AppConfig) -> list[str]:
    """参考用スプレッドシートのシート名一覧を返す。

    投稿種類ごとにシートを分けている場合に、利用可能なシートを確認するために使用。
    """
    client = _get_client(config)
    spreadsheet = client.open_by_key(config.source_sheet.spreadsheet_id)
    return [ws.title for ws in spreadsheet.worksheets()]
