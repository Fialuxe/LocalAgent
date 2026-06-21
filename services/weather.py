import httpx

from .base import BaseProvider
from .models import ProviderResult, WeatherCurrent, WeatherData, WeatherHour

# WMO Weather Interpretation Codes → (English, 日本語)
_WMO: dict[int, tuple[str, str]] = {
    0:  ("Clear sky",              "快晴"),
    1:  ("Mainly clear",           "概ね晴れ"),
    2:  ("Partly cloudy",          "一部曇り"),
    3:  ("Overcast",               "曇り"),
    45: ("Fog",                    "霧"),
    48: ("Icing fog",              "着氷性の霧"),
    51: ("Light drizzle",          "弱い霧雨"),
    53: ("Moderate drizzle",       "霧雨"),
    55: ("Dense drizzle",          "濃い霧雨"),
    61: ("Light rain",             "弱い雨"),
    63: ("Moderate rain",          "雨"),
    65: ("Heavy rain",             "大雨"),
    71: ("Light snow",             "小雪"),
    73: ("Moderate snow",          "雪"),
    75: ("Heavy snow",             "大雪"),
    77: ("Snow grains",            "霧雪"),
    80: ("Light showers",          "にわか雨（弱）"),
    81: ("Moderate showers",       "にわか雨"),
    82: ("Heavy showers",          "激しいにわか雨"),
    85: ("Light snow showers",     "にわか雪（弱）"),
    86: ("Heavy snow showers",     "激しいにわか雪"),
    95: ("Thunderstorm",           "雷雨"),
    96: ("Thunderstorm with hail", "ひょうを伴う雷雨"),
    99: ("Severe thunderstorm",    "激しい雷雨"),
}

_API = "https://api.open-meteo.com/v1/forecast"


def _decode(code: int) -> tuple[str, str]:
    return _WMO.get(code, ("Unknown", "不明"))


class WeatherProvider(BaseProvider):
    """
    Open-Meteo を使った天気プロバイダ（APIキー不要・無料）。

    Args:
        latitude:  緯度（デフォルト: 東京）
        longitude: 経度（デフォルト: 東京）
        location:  表示用の地名
        timezone:  タイムゾーン文字列
    """

    name = "weather"
    default_ttl = 900  # 15分

    def __init__(
        self,
        latitude: float = 35.6762,
        longitude: float = 139.6503,
        location: str = "東京",
        timezone: str = "Asia/Tokyo",
    ) -> None:
        self.latitude = latitude
        self.longitude = longitude
        self.location = location
        self.timezone = timezone

    async def fetch(self) -> ProviderResult:
        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "current": ",".join([
                "temperature_2m",
                "relative_humidity_2m",
                "apparent_temperature",
                "weather_code",
                "wind_speed_10m",
            ]),
            "hourly": "temperature_2m,weather_code",
            "timezone": self.timezone,
            "forecast_days": 1,
            "wind_speed_unit": "ms",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(_API, params=params)
                resp.raise_for_status()
                raw = resp.json()

            cur = raw["current"]
            code = cur.get("weather_code", 0)
            en, ja = _decode(code)

            current = WeatherCurrent(
                temperature=round(cur["temperature_2m"], 1),
                feels_like=round(cur["apparent_temperature"], 1),
                humidity=int(cur["relative_humidity_2m"]),
                wind_speed=round(cur["wind_speed_10m"], 1),
                condition=en,
                condition_ja=ja,
            )

            times  = raw["hourly"]["time"]
            temps  = raw["hourly"]["temperature_2m"]
            codes  = raw["hourly"]["weather_code"]
            hourly = [
                WeatherHour(
                    time=t[11:16],
                    temperature=round(temp, 1),
                    condition_ja=_decode(wcode)[1],
                )
                for t, temp, wcode in zip(times, temps, codes)
            ]

            return self._ok(WeatherData(
                location=self.location,
                latitude=self.latitude,
                longitude=self.longitude,
                current=current,
                hourly=hourly,
                timezone=self.timezone,
            ))
        except Exception as e:
            return self._err(str(e))
