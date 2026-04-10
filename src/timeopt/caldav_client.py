import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import uuid as _uuid

logger = logging.getLogger(__name__)

try:
    import caldav
except ImportError:
    caldav = None  # type: ignore


@dataclass
class CalendarEvent:
    uid: str
    title: str
    start: str  # ISO8601 UTC
    end: str    # ISO8601 UTC


def _to_utc_iso(dt) -> str:
    """Convert a datetime (possibly naive) to UTC ISO8601 string."""
    if hasattr(dt, "astimezone"):
        return dt.astimezone(timezone.utc).isoformat()
    return str(dt)


def _build_ical(title: str, start: str, end: str, uid: str) -> str:
    from icalendar import Calendar, Event as ICALEvent  # type: ignore
    cal = Calendar()
    cal.add("prodid", "-//timeopt//EN")
    cal.add("version", "2.0")
    ev = ICALEvent()
    ev.add("summary", title)
    ev.add("dtstart", datetime.fromisoformat(start))
    ev.add("dtend", datetime.fromisoformat(end))
    ev.add("uid", uid)
    cal.add_component(ev)
    return cal.to_ical().decode()


class CalDAVClient:
    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        read_calendars: str = "all",
        tasks_calendar: str = "Timeopt",
    ):
        self._url = url
        self._username = username
        self._password = password
        self._read_calendars = read_calendars  # "all" or comma-separated names
        self._tasks_calendar = tasks_calendar

    def _read_calendar_names(self) -> set[str] | None:
        """Return set of calendar names to read, or None for all."""
        if self._read_calendars == "all":
            return None
        return {n.strip() for n in self._read_calendars.split(",")}

    def get_events(self, date: str, days: int = 1) -> list[CalendarEvent]:
        """
        Fetch events for the given date range.
        Returns [] on connection failure (warn, don't raise).
        """
        if caldav is None:
            logger.warning("get_events: caldav package is not installed — returning empty list")
            return []
        try:
            start = datetime.fromisoformat(f"{date}T00:00:00+00:00")
            end = start + timedelta(days=days)
            allowed = self._read_calendar_names()

            events: list[CalendarEvent] = []
            with caldav.DAVClient(
                url=self._url,
                username=self._username,
                password=self._password,
            ) as client:
                principal = client.principal()
                for cal in principal.calendars():
                    if allowed is not None and cal.name not in allowed:
                        continue
                    if cal.name == self._tasks_calendar:
                        continue  # never read our own write calendar
                    try:
                        for ev in cal.date_search(start=start, end=end):
                            vevent = ev.instance.vevent
                            events.append(CalendarEvent(
                                uid=vevent.uid.value,
                                title=vevent.summary.value,
                                start=_to_utc_iso(vevent.dtstart.value),
                                end=_to_utc_iso(vevent.dtend.value),
                            ))
                    except Exception:
                        logger.exception("error fetching events from calendar %s", cal.name)

            logger.info("get_events: %d events for %s", len(events), date)
            return events
        except Exception:
            logger.exception("get_events: CalDAV request failed for date=%s", date)
            return []

    def _ensure_tasks_calendar(self, principal):
        """Return the Timeopt calendar, creating it if absent."""
        for cal in principal.calendars():
            if cal.name == self._tasks_calendar:
                return cal
        logger.info("creating calendar: %s", self._tasks_calendar)
        return principal.make_calendar(name=self._tasks_calendar)

    def create_event(self, title: str, start: str, end: str) -> str:
        """
        Create a calendar event in the Timeopt calendar.
        Returns the CalDAV UID of the created event.
        Raises RuntimeError on connection or write failure.
        """
        if caldav is None:
            raise RuntimeError("caldav package is not installed")
        uid = str(_uuid.uuid4())
        ical = _build_ical(title, start, end, uid)
        try:
            with caldav.DAVClient(
                url=self._url, username=self._username, password=self._password
            ) as client:
                principal = client.principal()
                tasks_cal = self._ensure_tasks_calendar(principal)
                event = tasks_cal.save_event(ical)
                # Some servers return the uid directly; use our generated uid as fallback
                try:
                    server_uid = event.instance.vevent.uid.value
                except Exception:
                    server_uid = uid
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"CalDAV create_event failed for '{title}': {e}") from e
        logger.info("created event: %s uid=%s", title, server_uid)
        return server_uid

    def delete_event(self, caldav_uid: str) -> None:
        """Delete a Timeopt calendar event by its CalDAV UID."""
        try:
            with caldav.DAVClient(
                url=self._url, username=self._username, password=self._password
            ) as client:
                principal = client.principal()
                tasks_cal = self._ensure_tasks_calendar(principal)
                event = tasks_cal.event_by_uid(caldav_uid)
                event.delete()
            logger.info("deleted event uid=%s", caldav_uid)
        except Exception:
            logger.exception("failed to delete event uid=%s", caldav_uid)
