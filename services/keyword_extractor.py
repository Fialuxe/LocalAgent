"""
日本語キーワード抽出 — コンパニオンメモリのトピックマッチング用。

ユーザーの発言から名詞を抽出し、保存済みメモリのキーワードと照合する。
Janome が利用可能な場合はそれを使い、未インストールの場合は
正規表現ベースのヒューリスティック（カタカナ列 / 漢字列）にフォールバックする。
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ── Janome ロード（オプション依存） ─────────────────────────────────────────

try:
    from janome.tokenizer import Tokenizer as _JanomeTokenizer

    _tokenizer = _JanomeTokenizer()
    _JANOME_AVAILABLE = True
except ImportError:
    _tokenizer = None  # type: ignore[assignment]
    _JANOME_AVAILABLE = False
    logger.warning(
        "Janome がインストールされていません。"
        "正規表現ベースのヒューリスティックにフォールバックします。"
        "精度を上げるには: pip install janome"
    )

# 対象品詞カテゴリ（Janome の part_of_speech 形式: "名詞,一般,...")
_INCLUDE_CATEGORIES = {"名詞-一般", "名詞-固有名詞", "名詞-サ変接続"}
_EXCLUDE_CATEGORIES = {"名詞-数", "名詞-接尾", "名詞-非自立"}

# フォールバック用: カタカナ2文字以上 / 漢字2文字以上
_RE_KATAKANA = re.compile(r"[゠-ヿ]{2,}")
_RE_KANJI = re.compile(r"[一-鿿々]{2,}")


# ── 公開API ──────────────────────────────────────────────────────────────────


def extract_nouns(text: str) -> set[str]:
    """
    日本語テキストから内容語の名詞を抽出する。

    Janome が使える場合:
      含む: 名詞-一般、名詞-固有名詞、名詞-サ変接続
      除外: 名詞-数、名詞-接尾、名詞-非自立、1文字以下の語

    Janome が使えない場合:
      カタカナ列（2文字以上）と漢字列（2文字以上）を近似名詞として返す。

    Returns:
        表層形（surface form）の集合。
    """
    if _JANOME_AVAILABLE:
        return _extract_nouns_janome(text)
    return _extract_nouns_heuristic(text)


def nouns_to_keywords_string(nouns: set[str]) -> str:
    """
    名詞セットをスペース区切りの文字列に変換する（DB保存用）。

    >>> nouns_to_keywords_string({"発酵食品", "健康"})
    '発酵食品 健康'
    """
    return " ".join(sorted(nouns))


def match_memories(user_text: str, memories: list[dict]) -> list[dict]:
    """
    ユーザー発言と保存済みメモリのキーワードを照合し、
    1語以上一致するメモリを返す。

    Args:
        user_text: ユーザーの発言テキスト。
        memories:  各要素が少なくとも
                   {'id', 'topic', 'keywords', 'researched_summary', 'research_type'}
                   を持つ辞書のリスト。
                   'keywords' はスペース区切り文字列（nouns_to_keywords_string の出力形式）。

    Returns:
        キーワードが1語以上一致したメモリ辞書のリスト（元の順序を維持）。
    """
    user_nouns = extract_nouns(user_text)
    if not user_nouns:
        return []

    matched: list[dict] = []
    for memory in memories:
        raw_keywords = memory.get("keywords", "") or ""
        memory_keywords = set(raw_keywords.split())
        if user_nouns & memory_keywords:
            matched.append(memory)

    return matched


# ── 内部実装 ──────────────────────────────────────────────────────────────────


def _extract_nouns_janome(text: str) -> set[str]:
    """Janome を使った品詞フィルタリングによる名詞抽出。"""
    nouns: set[str] = set()
    for token in _tokenizer.tokenize(text):
        pos = token.part_of_speech  # 例: "名詞,一般,*,*,*,*,..."
        pos_parts = pos.split(",")
        # "名詞-一般" のような "-" 結合キーを構築
        if len(pos_parts) < 2:
            continue
        category = f"{pos_parts[0]}-{pos_parts[1]}"

        if pos_parts[0] != "名詞":
            continue
        if category in _EXCLUDE_CATEGORIES:
            continue
        if category not in _INCLUDE_CATEGORIES:
            continue

        surface = token.surface
        if len(surface) <= 1:
            continue
        nouns.add(surface)

    return nouns


def _extract_nouns_heuristic(text: str) -> set[str]:
    """
    Janome 未インストール時のフォールバック。
    カタカナ列（2文字以上）と漢字列（2文字以上）を近似名詞として返す。
    発酵食品、円安、AI規制 のような一般的なトピック語に対応する。
    """
    nouns: set[str] = set()
    nouns.update(_RE_KATAKANA.findall(text))
    nouns.update(_RE_KANJI.findall(text))
    return nouns
