from unittest.mock import MagicMock
from timeopt.core import create_task, TaskInput
from timeopt.planner import get_plan_proposal, push_calendar_blocks, get_calendar_blocks


def _seed(conn):
    tasks = [
        TaskInput(title="task a", raw="a", priority="high", urgent=True,
                  category="work", effort="small"),
        TaskInput(title="task b", raw="b", priority="medium", urgent=False,
                  category="work", effort="small"),
    ]
    for t in tasks:
        create_task(conn, t)


def test_push_calendar_blocks_saves_to_db(conn):
    _seed(conn)
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")
    caldav = MagicMock()
    caldav.create_event.side_effect = ["uid-1", "uid-2"]
    caldav.delete_event = MagicMock()

    push_calendar_blocks(conn, proposal, date="2026-03-28", caldav_client=caldav)
    blocks = get_calendar_blocks(conn, "2026-03-28")
    assert len(blocks) == len(proposal["blocks"])


def test_push_calendar_blocks_replaces_existing(conn):
    _seed(conn)
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")

    caldav = MagicMock()
    caldav.create_event.side_effect = ["uid-old-1", "uid-old-2"]
    push_calendar_blocks(conn, proposal, date="2026-03-28", caldav_client=caldav)

    # Re-push same date
    caldav2 = MagicMock()
    caldav2.create_event.side_effect = ["uid-new-1", "uid-new-2"]
    caldav2.delete_event = MagicMock()
    push_calendar_blocks(conn, proposal, date="2026-03-28", caldav_client=caldav2)

    blocks = get_calendar_blocks(conn, "2026-03-28")
    uids = {b["caldav_uid"] for b in blocks}
    assert "uid-new-1" in uids
    assert "uid-old-1" not in uids
    # delete was called for old uids
    caldav2.delete_event.assert_called()


def test_push_calendar_blocks_aborts_on_caldav_failure(conn):
    import pytest
    _seed(conn)
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")

    caldav = MagicMock()
    caldav.create_event.side_effect = Exception("CalDAV write failed")

    with pytest.raises(Exception, match="CalDAV write failed"):
        push_calendar_blocks(conn, proposal, date="2026-03-28", caldav_client=caldav)

    # DB must be untouched — no blocks saved
    blocks = get_calendar_blocks(conn, "2026-03-28")
    assert blocks == []
