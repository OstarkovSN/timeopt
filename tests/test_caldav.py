from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone
import uuid
import pytest
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


def test_create_event_save_event_failure_propagates():
    """When save_event() raises, the exception should propagate to caller."""
    with patch("timeopt.caldav_client.caldav") as mock_caldav:
        mock_client = MagicMock()
        mock_caldav.DAVClient.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_caldav.DAVClient.return_value.__exit__ = MagicMock(return_value=False)

        mock_principal = MagicMock()
        mock_client.principal.return_value = mock_principal
        mock_tasks_cal = MagicMock()
        type(mock_tasks_cal).name = PropertyMock(return_value="Timeopt")
        mock_principal.calendars.return_value = [mock_tasks_cal]

        # save_event raises
        mock_tasks_cal.save_event.side_effect = Exception("Permission denied")

        client = CalDAVClient(
            url="https://caldav.yandex.ru",
            username="user",
            password="pass",
            read_calendars="all",
            tasks_calendar="Timeopt",
        )

        # Exception should propagate
        with pytest.raises(Exception, match="Permission denied"):
            client.create_event(
                title="New event",
                start="2026-03-28T10:00:00+00:00",
                end="2026-03-28T11:00:00+00:00",
            )


def test_delete_event_swallows_failures_gracefully():
    """When delete_event encounters exceptions, they should be logged but not re-raised."""
    with patch("timeopt.caldav_client.caldav") as mock_caldav:
        mock_client = MagicMock()
        mock_caldav.DAVClient.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_caldav.DAVClient.return_value.__exit__ = MagicMock(return_value=False)

        mock_principal = MagicMock()
        mock_client.principal.return_value = mock_principal
        mock_tasks_cal = MagicMock()
        type(mock_tasks_cal).name = PropertyMock(return_value="Timeopt")
        mock_principal.calendars.return_value = [mock_tasks_cal]

        # event_by_uid raises
        mock_tasks_cal.event_by_uid.side_effect = Exception("Event not found")

        client = CalDAVClient(
            url="https://caldav.yandex.ru",
            username="user",
            password="pass",
            read_calendars="all",
            tasks_calendar="Timeopt",
        )

        # Should not raise
        client.delete_event("uid-missing")


def test_ensure_tasks_calendar_creation_failure_propagates():
    """When principal.make_calendar() raises (permission error), exception should propagate."""
    with patch("timeopt.caldav_client.caldav") as mock_caldav:
        mock_client = MagicMock()
        mock_caldav.DAVClient.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_caldav.DAVClient.return_value.__exit__ = MagicMock(return_value=False)

        mock_principal = MagicMock()
        mock_client.principal.return_value = mock_principal
        # No Timeopt calendar
        mock_principal.calendars.return_value = []
        # make_calendar raises (permission error)
        mock_principal.make_calendar.side_effect = Exception("403 Forbidden")

        client = CalDAVClient(
            url="https://caldav.yandex.ru",
            username="user",
            password="pass",
            read_calendars="all",
            tasks_calendar="Timeopt",
        )

        # Exception should propagate
        with pytest.raises(Exception, match="403 Forbidden"):
            client._ensure_tasks_calendar(mock_principal)


def test_get_events_partial_failure():
    """When one calendar fails during date_search, others' events are still returned."""
    with patch("timeopt.caldav_client.caldav") as mock_caldav:
        mock_client = MagicMock()
        mock_caldav.DAVClient.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_caldav.DAVClient.return_value.__exit__ = MagicMock(return_value=False)

        mock_principal = MagicMock()
        mock_client.principal.return_value = mock_principal

        # Two calendars: Work (succeeds) and Personal (fails)
        work_cal = MagicMock()
        type(work_cal).name = PropertyMock(return_value="Work")
        personal_cal = MagicMock()
        type(personal_cal).name = PropertyMock(return_value="Personal")
        mock_principal.calendars.return_value = [work_cal, personal_cal]

        # Work calendar succeeds
        ev1 = _mock_event("Team sync", "2026-03-28T09:00:00+00:00", "2026-03-28T10:00:00+00:00")
        work_cal.date_search.return_value = [ev1]

        # Personal calendar raises
        personal_cal.date_search.side_effect = Exception("timeout")

        client = CalDAVClient(
            url="https://caldav.yandex.ru",
            username="user",
            password="pass",
            read_calendars="all",
            tasks_calendar="Timeopt",
        )
        events = client.get_events("2026-03-28")

        # Should return events from Work calendar only
        assert len(events) == 1
        assert events[0].title == "Team sync"
        personal_cal.date_search.assert_called_once()


def test_create_event_uid_fallback():
    """When event.instance.vevent.uid.value raises, use locally-generated UUID."""
    with patch("timeopt.caldav_client.caldav") as mock_caldav:
        mock_client = MagicMock()
        mock_caldav.DAVClient.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_caldav.DAVClient.return_value.__exit__ = MagicMock(return_value=False)

        mock_principal = MagicMock()
        mock_client.principal.return_value = mock_principal
        mock_tasks_cal = MagicMock()
        type(mock_tasks_cal).name = PropertyMock(return_value="Timeopt")
        mock_principal.calendars.return_value = [mock_tasks_cal]

        # Create event that raises when accessing uid
        created_event = MagicMock()
        uid_mock = MagicMock()
        type(uid_mock).value = PropertyMock(side_effect=Exception("no uid"))
        created_event.instance.vevent.uid = uid_mock
        mock_tasks_cal.save_event.return_value = created_event

        client = CalDAVClient(
            url="https://caldav.yandex.ru",
            username="user",
            password="pass",
            read_calendars="all",
            tasks_calendar="Timeopt",
        )

        uid = client.create_event(
            title="Event without server UID",
            start="2026-03-28T10:00:00+00:00",
            end="2026-03-28T11:00:00+00:00",
        )

        # Should return the locally-generated UUID (not the server one)
        # Verify it's a valid UUID format
        uuid.UUID(uid)


def test_get_events_auth_failure_logs_exception(caplog):
    """Auth error should be logged with traceback (logger.exception), not just a warning."""
    import logging
    client = CalDAVClient(
        url="https://caldav.example.com",
        username="user",
        password="wrong",
    )
    mock_caldav_module = MagicMock()
    mock_caldav_module.DAVClient.return_value.__enter__.return_value.principal.side_effect = (
        Exception("401 Unauthorized")
    )
    with patch("timeopt.caldav_client.caldav", mock_caldav_module):
        with caplog.at_level(logging.ERROR, logger="timeopt.caldav_client"):
            result = client.get_events("2026-04-10")
    assert result == []
    assert any(r.exc_info is not None for r in caplog.records), \
        "Expected logger.exception (with traceback), got logger.warning (no traceback)"


def test_get_events_when_caldav_not_installed_returns_empty():
    """If caldav package is absent (caldav=None), return [] with a clear log."""
    client = CalDAVClient(url="https://caldav.example.com", username="u", password="p")
    with patch("timeopt.caldav_client.caldav", None):
        result = client.get_events("2026-04-10")
    assert result == []
