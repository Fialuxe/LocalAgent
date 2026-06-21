"""
APIキー管理。
.env ファイルまたは環境変数から読み込む。

優先順位: 環境変数 > .env ファイル
"""

import os
from pathlib import Path

# python-dotenv がインストールされていれば .env を自動ロード
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env", override=False)
except ImportError:
    pass  # 環境変数だけで動作する


class APIConfig:
    # ── NewsAPI.org （日本語ニュース取得）──────────────────────────────────
    # 無料: 100リクエスト/日  登録: https://newsapi.org/register
    NEWSAPI_KEY: str | None = os.getenv("NEWSAPI_KEY")

    # ── Naver Open API（韓国ニュース・検索トレンド）──────────────────────
    # 無料。登録: https://developers.naver.com/apps/#/register
    NAVER_CLIENT_ID: str | None = os.getenv("NAVER_CLIENT_ID")
    NAVER_CLIENT_SECRET: str | None = os.getenv("NAVER_CLIENT_SECRET")

    @classmethod
    def has_newsapi(cls) -> bool:
        return bool(cls.NEWSAPI_KEY)

    @classmethod
    def has_naver(cls) -> bool:
        return bool(cls.NAVER_CLIENT_ID and cls.NAVER_CLIENT_SECRET)
