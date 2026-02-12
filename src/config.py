"""設定管理モジュール。

.envファイルとconfig.yamlから設定を読み込み、アプリケーション全体で使用する。
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@dataclass
class SourceSheetConfig:
    """参考用スプレッドシートの設定。"""

    spreadsheet_id: str = ""
    sheet_name: str = "Sheet1"
    columns: dict = field(default_factory=lambda: {
        "body": "A",
        "reply": "B",
    })
    header_row: int = 1
    data_start_row: int = 2


@dataclass
class DestSheetConfig:
    """自動投稿用スプレッドシート（転記先）の設定。"""

    spreadsheet_id: str = ""
    sheet_name: str = "Sheet1"
    columns: dict = field(default_factory=lambda: {
        "body": "A",
        "reply": "B",
        "status": "C",
        "created_at": "D",
    })
    header_row: int = 1
    data_start_row: int = 2


@dataclass
class ClaudeConfig:
    """Claude API の設定。"""

    api_key: str = ""
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 1024
    temperature: float = 0.8


@dataclass
class GenerationConfig:
    """投稿生成の設定。"""

    posts_per_run: int = 5
    max_body_length: int = 500
    max_reply_length: int = 500
    prompt_template: str = ""


@dataclass
class AppConfig:
    """アプリケーション全体の設定。"""

    source_sheet: SourceSheetConfig = field(default_factory=SourceSheetConfig)
    dest_sheet: DestSheetConfig = field(default_factory=DestSheetConfig)
    claude: ClaudeConfig = field(default_factory=ClaudeConfig)
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    google_service_account_file: str = "credentials/service_account.json"


def _deep_update(base: dict, override: dict) -> dict:
    """ネストされた辞書を再帰的にマージする。"""
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def load_config(config_path: Path | None = None) -> AppConfig:
    """config.yaml と環境変数から設定を読み込む。"""
    path = config_path or CONFIG_PATH

    raw = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    config = AppConfig()

    # --- source_sheet ---
    src = raw.get("source_sheet", {})
    config.source_sheet = SourceSheetConfig(
        spreadsheet_id=os.getenv("SOURCE_SPREADSHEET_ID", src.get("spreadsheet_id", "")),
        sheet_name=src.get("sheet_name", "Sheet1"),
        columns=src.get("columns", config.source_sheet.columns),
        header_row=src.get("header_row", 1),
        data_start_row=src.get("data_start_row", 2),
    )

    # --- dest_sheet ---
    dst = raw.get("dest_sheet", {})
    config.dest_sheet = DestSheetConfig(
        spreadsheet_id=os.getenv("DEST_SPREADSHEET_ID", dst.get("spreadsheet_id", "")),
        sheet_name=dst.get("sheet_name", "Sheet1"),
        columns=dst.get("columns", config.dest_sheet.columns),
        header_row=dst.get("header_row", 1),
        data_start_row=dst.get("data_start_row", 2),
    )

    # --- claude ---
    cl = raw.get("claude", {})
    config.claude = ClaudeConfig(
        api_key=os.getenv("ANTHROPIC_API_KEY", cl.get("api_key", "")),
        model=cl.get("model", "claude-sonnet-4-20250514"),
        max_tokens=cl.get("max_tokens", 1024),
        temperature=cl.get("temperature", 0.8),
    )

    # --- generation ---
    gen = raw.get("generation", {})
    config.generation = GenerationConfig(
        posts_per_run=gen.get("posts_per_run", 5),
        max_body_length=gen.get("max_body_length", 500),
        max_reply_length=gen.get("max_reply_length", 500),
        prompt_template=gen.get("prompt_template", ""),
    )

    # --- google credentials ---
    config.google_service_account_file = os.getenv(
        "GOOGLE_SERVICE_ACCOUNT_FILE",
        raw.get("google_service_account_file", "credentials/service_account.json"),
    )

    return config
