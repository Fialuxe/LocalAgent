from datetime import datetime

from .base import BaseProvider
from .models import ProviderResult, TimeContextData

_DAYS_JA = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]
_MONTHS  = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]


def _period(hour: int) -> str:
    if hour < 5:   return "深夜"
    if hour < 9:   return "朝"
    if hour < 12:  return "午前"
    if hour < 13:  return "昼"
    if hour < 18:  return "午後"
    if hour < 21:  return "夕方"
    return "夜"


def _comment(weekday: int, hour: int) -> str:
    # 曜日コメント
    day_comments = {
        0: "週のはじめですね、今週も頑張りましょう",
        1: "週の中盤ですね、きょうも頑張りましょう",
        2: "週の折り返しですね、ここらへんって疲れが出やすいですよね",
        3: "週の終わりが見えてきましたね",
        4: "もうすぐ週末ですね、今週もお疲れ様です",
        5: "週末ですね、たのしく過ごせるといいですね",
        6: "週末ですね",
    }
    base = day_comments[weekday]

    # 時間帯コメント（組み合わせると自然になるもの）
    if hour < 5:
        return f"夜遅いですね、{base}"
    if hour < 9:
        return f"おはようございます、{base}"
    if 12 <= hour < 13:
        return f"お昼ですね、{base}"
    if hour >= 21:
        return f"夜ですね、{base}"
    return base


class TimeContextProvider(BaseProvider):
    """
    外部APIなし・stdlib のみ。
    現在の曜日・時刻・時間帯を LLM コンテキストとして提供する。

    例: 「金曜日の夕方」→「もうすぐ週末ですね、今週もお疲れ様です」
    """

    name = "time_context"
    default_ttl = 60  # 1分ごとに更新

    async def fetch(self) -> ProviderResult:
        now = datetime.now()
        wd  = now.weekday()
        date_ja = (
            f"{now.year}年{_MONTHS[now.month - 1]}{now.day}日"
            f"（{_DAYS_JA[wd][0]}）"   # 短縮: 月〜日
        )
        return self._ok(TimeContextData(
            iso=now.isoformat(timespec="minutes"),
            date_ja=date_ja,
            time_str=now.strftime("%H:%M"),
            day_ja=_DAYS_JA[wd],
            period_ja=_period(now.hour),
            comment=_comment(wd, now.hour),
        ))
