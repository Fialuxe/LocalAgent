import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .base import BaseProvider
from .models import CalendarData, CalendarEvent, ProviderResult

_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


class GoogleCalendarProvider(BaseProvider):
    """
    Google Calendar API プロバイダ（読み取り専用）。

    初回起動時にブラウザで OAuth 認証が行われ、token.json に保存される。
    credentials.json が存在しない場合はスキップ（エラーにはしない）。

    Args:
        credentials_file: GCP コンソールからダウンロードした認証情報ファイル
        token_file:       アクセストークン保存先
        days_ahead:       何日先までの予定を取得するか
        max_events:       最大取得件数
    """

    name = "calendar"
    default_ttl = 600  # 10分

    def __init__(
        self,
        credentials_file: str = "credentials.json",
        token_file: str = "token.json",
        days_ahead: int = 1,
        max_events: int = 10,
    ) -> None:
        self.credentials_file = Path(credentials_file)
        self.token_file = Path(token_file)
        self.days_ahead = days_ahead
        self.max_events = max_events

    async def fetch(self) -> ProviderResult:
        if not self.credentials_file.exists():
            return self._err(
                f"{self.credentials_file} が見つかりません — "
                "Google Calendar はスキップされます。"
                "GCP コンソールから OAuth 認証情報をダウンロードしてください。"
            )
        try:
            return await asyncio.to_thread(self._sync_fetch)
        except Exception as e:
            return self._err(str(e))

    def _sync_fetch(self) -> ProviderResult:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds: Optional[Credentials] = None

        import logging as _log
        _logger = _log.getLogger(__name__)

        # keyring 優先、なければファイルにフォールバック
        token_json: Optional[str] = None
        try:
            import keyring
            token_json = keyring.get_password("localagent", "google_calendar_token")
        except ImportError:
            pass  # keyring 未インストール → ファイルにフォールバック
        except Exception as _e:
            _logger.warning("keyring 読み込みエラー（ファイルにフォールバック）: %s", _e)
        if not token_json and self.token_file.exists():
            token_json = self.token_file.read_text(encoding="utf-8")
        if token_json:
            creds = Credentials.from_authorized_user_info(
                __import__("json").loads(token_json), _SCOPES
            )

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as _e:
                    # リフレッシュ失敗 → 古いトークンを削除して再認証フローへ
                    _logger.warning("トークンリフレッシュ失敗、再認証が必要です: %s", _e)
                    try:
                        import keyring
                        keyring.delete_password("localagent", "google_calendar_token")
                    except Exception:
                        pass
                    if self.token_file.exists():
                        self.token_file.unlink()
                    raise
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_file), _SCOPES
                )
                creds = flow.run_local_server(port=0)
            try:
                import keyring
                keyring.set_password("localagent", "google_calendar_token", creds.to_json())
            except ImportError:
                _logger.warning(
                    "keyring 未インストール — トークンをファイルに保存します: %s "
                    "（本番環境では 'pip install keyring' を推奨）",
                    self.token_file,
                )
                self.token_file.write_text(creds.to_json(), encoding="utf-8")
            except Exception as _e:
                _logger.warning("keyring 書き込みエラー — ファイルにフォールバック: %s", _e)
                self.token_file.write_text(creds.to_json(), encoding="utf-8")

        service = build("calendar", "v3", credentials=creds)
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(days=self.days_ahead)

        raw = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=time_max.isoformat(),
                maxResults=self.max_events,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        def _parse(s: str) -> Optional[datetime]:
            if not s:
                return None
            return datetime.fromisoformat(s.replace("Z", "+00:00"))

        events: list[CalendarEvent] = []
        for item in raw.get("items", []):
            start_obj = item.get("start", {})
            end_obj   = item.get("end", {})
            is_all_day = "date" in start_obj and "dateTime" not in start_obj
            start_raw = start_obj.get("dateTime") or start_obj.get("date") or ""
            end_raw   = end_obj.get("dateTime")   or end_obj.get("date")   or ""
            events.append(CalendarEvent(
                title=item.get("summary", "（無題）"),
                start=_parse(start_raw) or now,
                end=_parse(end_raw),
                location=item.get("location"),
                is_all_day=is_all_day,
            ))

        return self._ok(CalendarData(events=events, fetch_range_days=self.days_ahead))
