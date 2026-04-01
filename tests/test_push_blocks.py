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


def test_push_calendar_blocks_partial_create_failure(conn):
    """
    Test partial failure during CalDAV creates.
    When creates succeed for first 2 tasks but fail on 3rd,
    push_calendar_blocks should raise and DB should remain untouched.
    The first 2 CalDAV events are orphaned (known limitation).
    """
    import pytest

    # Seed with 3 tasks (will produce 3 blocks)
    tasks = [
        TaskInput(title="task a", raw="a", priority="high", urgent=True,
                  category="work", effort="small"),
        TaskInput(title="task b", raw="b", priority="medium", urgent=False,
                  category="work", effort="small"),
        TaskInput(title="task c", raw="c", priority="low", urgent=False,
                  category="work", effort="small"),
    ]
    for t in tasks:
        create_task(conn, t)

    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")
    assert len(proposal["blocks"]) == 3, "Expected 3 blocks from 3 tasks"

    caldav = MagicMock()
    # First 2 creates succeed, 3rd fails
    caldav.create_event.side_effect = ["uid-1", "uid-2", Exception("CalDAV create failed")]

    with pytest.raises(Exception, match="CalDAV create failed"):
        push_calendar_blocks(conn, proposal, date="2026-03-28", caldav_client=caldav)

    # Verify: create_event was called exactly 3 times (first 2 succeeded, 3rd failed)
    assert caldav.create_event.call_count == 3

    # Verify: DB has 0 blocks (unchanged — SQLite commit didn't happen)
    blocks = get_calendar_blocks(conn, "2026-03-28")
    assert blocks == []


def test_push_calendar_blocks_delete_failure_after_creates(conn):
    """
    Test failure during delete phase after creates succeed.
    Seed DB with existing blocks from a previous push.
    If delete_event raises, the function raises and old blocks remain in DB
    (since SQLite commit hasn't happened yet).
    """
    import pytest
    from timeopt.planner import push_calendar_blocks

    _seed(conn)

    # First push: creates succeed, blocks are saved
    proposal1 = get_plan_proposal(conn, events=[], date="2026-03-28")
    caldav1 = MagicMock()
    caldav1.create_event.side_effect = ["uid-old-1", "uid-old-2"]
    caldav1.delete_event = MagicMock()
    push_calendar_blocks(conn, proposal1, date="2026-03-28", caldav_client=caldav1)

    # Verify first push saved blocks
    blocks_after_first = get_calendar_blocks(conn, "2026-03-28")
    assert len(blocks_after_first) == 2
    old_block_uids = {b["caldav_uid"] for b in blocks_after_first}
    assert old_block_uids == {"uid-old-1", "uid-old-2"}

    # Second push: creates succeed, but delete_event raises on first call
    proposal2 = get_plan_proposal(conn, events=[], date="2026-03-28")
    caldav2 = MagicMock()
    caldav2.create_event.side_effect = ["uid-new-1", "uid-new-2"]
    caldav2.delete_event.side_effect = Exception("CalDAV delete failed")

    with pytest.raises(Exception, match="CalDAV delete failed"):
        push_calendar_blocks(conn, proposal2, date="2026-03-28", caldav_client=caldav2)

    # Verify: delete_event was called at least once (raises on first call)
    assert caldav2.delete_event.call_count >= 1

    # Verify: DB still has old blocks (SQLite commit didn't happen due to exception)
    blocks_after_delete_failure = get_calendar_blocks(conn, "2026-03-28")
    assert len(blocks_after_delete_failure) == 2
    assert {b["caldav_uid"] for b in blocks_after_delete_failure} == old_block_uids


def test_push_calendar_blocks_double_push_idempotency_orphans_first(conn):
    """
    Test pushing the same plan twice (with fresh caldav mocks).
    The second push should replace the first push's blocks in the DB.
    However, the first push's CalDAV events become orphaned (known limitation):
    they are not deleted by the second push because push_calendar_blocks
    only deletes the old events it knows about (from its own previous push stored in DB).
    If you push twice without intermediate DB updates, each push is independent.
    """
    _seed(conn)

    # First push
    proposal = get_plan_proposal(conn, events=[], date="2026-03-28")
    caldav1 = MagicMock()
    caldav1.create_event.side_effect = ["uid-push1-1", "uid-push1-2"]
    caldav1.delete_event = MagicMock()
    push_calendar_blocks(conn, proposal, date="2026-03-28", caldav_client=caldav1)

    blocks_after_first = get_calendar_blocks(conn, "2026-03-28")
    assert len(blocks_after_first) == 2
    first_uids = {b["caldav_uid"] for b in blocks_after_first}
    assert first_uids == {"uid-push1-1", "uid-push1-2"}

    # Second push (fresh caldav, independent)
    caldav2 = MagicMock()
    caldav2.create_event.side_effect = ["uid-push2-1", "uid-push2-2"]
    caldav2.delete_event = MagicMock()
    push_calendar_blocks(conn, proposal, date="2026-03-28", caldav_client=caldav2)

    blocks_after_second = get_calendar_blocks(conn, "2026-03-28")
    assert len(blocks_after_second) == 2
    second_uids = {b["caldav_uid"] for b in blocks_after_second}
    assert second_uids == {"uid-push2-1", "uid-push2-2"}

    # Verify: first push's UIDs are not in DB anymore
    assert first_uids != second_uids
    assert "uid-push1-1" not in second_uids

    # Verify: the second push called delete_event for the first push's UIDs
    # (because they were in the DB when the second push started)
    assert caldav2.delete_event.call_count == 2

    # Note: uid-push1-1 and uid-push1-2 are orphaned in CalDAV because
    # the second push doesn't know about them (they're not in DB anymore,
    # they're only in Yandex Calendar). This is the known limitation.
