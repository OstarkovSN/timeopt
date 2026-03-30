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


def test_create_event_returns_uid():
    with patch("timeopt.caldav_client.caldav") as mock_caldav:
        mock_client = MagicMock()
        mock_caldav.DAVClient.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_caldav.DAVClient.return_value.__exit__ = MagicMock(return_value=False)

        mock_principal = MagicMock()
        mock_client.principal.return_value = mock_principal
        mock_tasks_cal = MagicMock()
        type(mock_tasks_cal).name = PropertyMock(return_value="Timeopt")
        mock_principal.calendars.return_value = [mock_tasks_cal]
        created_event = MagicMock()
        created_event.instance.vevent.uid.value = "new-uid-123"
        mock_tasks_cal.save_event.return_value = created_event

        client = CalDAVClient(
            url="https://caldav.yandex.ru",
            username="user",
            password="pass",
            read_calendars="all",
            tasks_calendar="Timeopt",
        )
        uid = client.create_event(
            title="Fix login bug",
            start="2026-03-28T10:00:00+00:00",
            end="2026-03-28T11:00:00+00:00",
        )
    assert uid == "new-uid-123"


def test_delete_event_calls_caldav():
    with patch("timeopt.caldav_client.caldav") as mock_caldav:
        mock_client = MagicMock()
        mock_caldav.DAVClient.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_caldav.DAVClient.return_value.__exit__ = MagicMock(return_value=False)

        mock_principal = MagicMock()
        mock_client.principal.return_value = mock_principal
        mock_tasks_cal = MagicMock()
        type(mock_tasks_cal).name = PropertyMock(return_value="Timeopt")
        mock_principal.calendars.return_value = [mock_tasks_cal]
        mock_event = MagicMock()
        mock_tasks_cal.event_by_uid.return_value = mock_event

        client = CalDAVClient(
            url="https://caldav.yandex.ru",
            username="user",
            password="pass",
            read_calendars="all",
            tasks_calendar="Timeopt",
        )
        client.delete_event("uid-to-delete")

    mock_tasks_cal.event_by_uid.assert_called_once_with("uid-to-delete")
    mock_event.delete.assert_called_once()


def test_create_tasks_calendar_if_missing():
    with patch("timeopt.caldav_client.caldav") as mock_caldav:
        mock_client = MagicMock()
        mock_caldav.DAVClient.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_caldav.DAVClient.return_value.__exit__ = MagicMock(return_value=False)

        mock_principal = MagicMock()
        mock_client.principal.return_value = mock_principal
        # No Timeopt calendar yet
        mock_principal.calendars.return_value = []
        mock_principal.make_calendar.return_value = MagicMock()

        client = CalDAVClient(
            url="https://caldav.yandex.ru",
            username="user",
            password="pass",
            read_calendars="all",
            tasks_calendar="Timeopt",
        )
        client._ensure_tasks_calendar(mock_principal)

    mock_principal.make_calendar.assert_called_once_with(name="Timeopt")
