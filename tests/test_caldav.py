from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone
from timeopt.caldav_client import CalDAVClient, CalendarEvent


def _mock_event(title: str, start: str, end: str):
    ev = MagicMock()
    ev.instance.vevent.summary.value = title
    ev.instance.vevent.dtstart.value = datetime.fromisoformat(start)
    ev.instance.vevent.dtend.value = datetime.fromisoformat(end)
    ev.instance.vevent.uid.value = f"uid-{title}"
    return ev


def test_get_events_returns_list():
    with patch("timeopt.caldav_client.caldav") as mock_caldav:
        mock_client = MagicMock()
        mock_caldav.DAVClient.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_caldav.DAVClient.return_value.__exit__ = MagicMock(return_value=False)

        mock_principal = MagicMock()
        mock_client.principal.return_value = mock_principal
        mock_cal = MagicMock()
        mock_principal.calendars.return_value = [mock_cal]
        type(mock_cal).name = PropertyMock(return_value="Work")

        ev1 = _mock_event("Standup", "2026-03-28T09:00:00+00:00", "2026-03-28T10:00:00+00:00")
        mock_cal.date_search.return_value = [ev1]

        client = CalDAVClient(
            url="https://caldav.yandex.ru",
            username="user",
            password="pass",
            read_calendars="all",
            tasks_calendar="Timeopt",
        )
        events = client.get_events("2026-03-28")

    assert len(events) == 1
    assert events[0].title == "Standup"
    assert events[0].start == "2026-03-28T09:00:00+00:00"


def test_get_events_filters_by_calendar_name():
    with patch("timeopt.caldav_client.caldav") as mock_caldav:
        mock_client = MagicMock()
        mock_caldav.DAVClient.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_caldav.DAVClient.return_value.__exit__ = MagicMock(return_value=False)

        mock_principal = MagicMock()
        mock_client.principal.return_value = mock_principal

        work_cal = MagicMock()
        type(work_cal).name = PropertyMock(return_value="Work")
        personal_cal = MagicMock()
        type(personal_cal).name = PropertyMock(return_value="Personal")
        mock_principal.calendars.return_value = [work_cal, personal_cal]

        work_cal.date_search.return_value = [
            _mock_event("Standup", "2026-03-28T09:00:00+00:00", "2026-03-28T10:00:00+00:00")
        ]
        personal_cal.date_search.return_value = []

        client = CalDAVClient(
            url="https://caldav.yandex.ru",
            username="user",
            password="pass",
            read_calendars="Work",  # only Work calendar
            tasks_calendar="Timeopt",
        )
        events = client.get_events("2026-03-28")

    assert len(events) == 1
    work_cal.date_search.assert_called_once()
    personal_cal.date_search.assert_not_called()


def test_caldav_unreachable_returns_empty():
    with patch("timeopt.caldav_client.caldav") as mock_caldav:
        mock_caldav.DAVClient.side_effect = Exception("Connection refused")
        client = CalDAVClient(
            url="https://caldav.yandex.ru",
            username="user",
            password="pass",
            read_calendars="all",
            tasks_calendar="Timeopt",
        )
        events = client.get_events("2026-03-28")
    assert events == []
