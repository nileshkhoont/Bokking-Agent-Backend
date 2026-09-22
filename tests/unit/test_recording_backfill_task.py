from datetime import UTC, datetime, timedelta

import pytest

from app.core.constants import CallStatus, CallType, Direction
from app.integrations.edesy.schemas import EdesyCallSummary
from app.models.call import Call
from app.models.person import Person
from app.workers.tasks import recording_backfill_task
from app.workers.tasks.recording_backfill_task import backfill_missing_recordings_once


@pytest.mark.asyncio
async def test_no_candidates_never_calls_edesy(monkeypatch):
    """Nothing missing a recording -> must not even attempt an Edesy call."""
    called = False

    async def fail_if_called(limit: int = 50):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(recording_backfill_task.edesy_client, "list_calls", fail_if_called)

    filled = await backfill_missing_recordings_once()
    assert filled == 0
    assert called is False


@pytest.mark.asyncio
async def test_fills_only_the_matching_answered_call(monkeypatch):
    """Regression test for the 2026-09-22 finding: Edesy's recording isn't always ready the
    instant call.ended fires, so this sweep must pick up a call left with recording_url=None and
    fill it once Edesy actually has it — while leaving unrelated/ineligible calls untouched.
    """
    person = Person(phone_number="+15551250000")
    await person.insert()

    target = Call(
        person_id=str(person.id),
        call_type=CallType.inbound,
        direction=Direction.inbound,
        call_status=CallStatus.answered,
        edesy_call_id="sid-fill-me",
        recording_url=None,
    )
    await target.insert()

    already_has_one = Call(
        person_id=str(person.id),
        call_type=CallType.inbound,
        direction=Direction.inbound,
        call_status=CallStatus.answered,
        edesy_call_id="sid-already-has-recording",
        recording_url="https://recordings.example/already-there",
    )
    await already_has_one.insert()

    missed_call = Call(
        person_id=str(person.id),
        call_type=CallType.inbound,
        direction=Direction.inbound,
        call_status=CallStatus.missed,
        edesy_call_id="sid-missed",
        recording_url=None,
    )
    await missed_call.insert()

    too_old = Call(
        person_id=str(person.id),
        call_type=CallType.inbound,
        direction=Direction.inbound,
        call_status=CallStatus.answered,
        edesy_call_id="sid-too-old",
        recording_url=None,
    )
    await too_old.insert()
    too_old.created_at = datetime.now(UTC) - timedelta(hours=recording_backfill_task.GIVE_UP_AFTER_HOURS + 1)
    await too_old.save()

    async def fake_list_calls(limit: int = 50):
        return [
            EdesyCallSummary(
                conversationId="conv-1", callSid="sid-fill-me", recordingUrl="https://recordings.example/conv-1"
            ),
            EdesyCallSummary(
                conversationId="conv-2", callSid="sid-too-old", recordingUrl="https://recordings.example/conv-2"
            ),
            EdesyCallSummary(conversationId="conv-3", callSid="sid-unrelated", recordingUrl=None),
        ]

    monkeypatch.setattr(recording_backfill_task.edesy_client, "list_calls", fake_list_calls)

    filled = await backfill_missing_recordings_once()
    assert filled == 1

    updated_target = await Call.get(target.id)
    assert updated_target.recording_url == "https://recordings.example/conv-1"

    unchanged_already_has_one = await Call.get(already_has_one.id)
    assert unchanged_already_has_one.recording_url == "https://recordings.example/already-there"

    unchanged_too_old = await Call.get(too_old.id)
    assert unchanged_too_old.recording_url is None


@pytest.mark.asyncio
async def test_edesy_failure_is_swallowed_not_raised(monkeypatch):
    """No EDESY_API_KEY in the test environment — the sweep must degrade gracefully, never crash
    the Beat schedule or the in-process scheduler.
    """
    person = Person(phone_number="+15551260000")
    await person.insert()
    call = Call(
        person_id=str(person.id),
        call_type=CallType.outbound_admin_scheduled,
        direction=Direction.outbound,
        call_status=CallStatus.answered,
        edesy_call_id="sid-no-credentials",
        recording_url=None,
    )
    await call.insert()

    filled = await backfill_missing_recordings_once()
    assert filled == 0

    unchanged = await Call.get(call.id)
    assert unchanged.recording_url is None
