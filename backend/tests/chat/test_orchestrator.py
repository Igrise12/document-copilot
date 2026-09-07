import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.auth.current_user import CurrentUser
from app.chat.orchestrator import stream_turn
from app.grounding.models import Citation, GroundedAnswer, SourcePassage

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
THREAD_ID = UUID("00000000-0000-0000-0000-000000000002")
USER_MESSAGE_ID = UUID("00000000-0000-0000-0000-000000000003")
REQUEST_ID = UUID("00000000-0000-0000-0000-000000000004")
CHUNK_ID = UUID("00000000-0000-0000-0000-000000000005")


class FakeRequest:
    def __init__(self, disconnected: bool = False, states: list[bool] | None = None) -> None:
        self.disconnected = disconnected
        self.states = states or []

    async def is_disconnected(self) -> bool:
        if self.states:
            return self.states.pop(0)
        return self.disconnected


class FakeRetriever:
    def __init__(self, passages: list[SourcePassage]) -> None:
        self.passages = passages

    async def search(self, *args) -> list[SourcePassage]:
        return self.passages


class FakeAgent:
    def __init__(self, answer: GroundedAnswer, *, block: bool = False) -> None:
        self.answer = answer
        self.prompt = ""
        self.block = block
        self.cancelled = False

    async def run(self, prompt: str, **kwargs):
        self.prompt = prompt
        try:
            if self.block:
                await asyncio.Event().wait()
            return SimpleNamespace(output=self.answer, usage=SimpleNamespace(requests=1, input_tokens=10, output_tokens=5))
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class FailingAgent:
    async def run(self, prompt: str, **kwargs):
        raise RuntimeError("Ollama is unavailable")


def passage() -> SourcePassage:
    return SourcePassage(
        chunk_id=CHUNK_ID,
        document_id=uuid4(),
        document_name="filing.pdf",
        text="Revenue was $100.",
        page_numbers=(3,),
        section="Revenue",
    )


def answer(**changes) -> GroundedAnswer:
    values = {
        "answer": "Revenue was $100.",
        "citations": (
            Citation(
                chunk_id=CHUNK_ID,
                document_name="filing.pdf",
                excerpt="Revenue was $100.",
                page_numbers=(3,),
                section="Revenue",
            ),
        ),
    }
    values.update(changes)
    return GroundedAnswer(**values)


@pytest.fixture
def user() -> CurrentUser:
    return CurrentUser(USER_ID, "analyst@driftwoodcapital.com")


async def collect_events(*args, **kwargs) -> list[str]:
    return [event async for event in stream_turn(*args, **kwargs)]


@pytest.fixture(autouse=True)
def record_events(monkeypatch):
    async def fake_record(*_args) -> None:
        return None

    monkeypatch.setattr("app.chat.orchestrator.record_activity", fake_record)
    monkeypatch.setattr("app.chat.orchestrator.completed_history", AsyncMock(return_value=[]))


@pytest.mark.anyio
async def test_stream_persists_validated_answer(monkeypatch, user) -> None:
    completed = []
    agent = FakeAgent(answer())

    async def fake_history(*args) -> list[tuple[str, str]]:
        return [("user", "Earlier question")]

    async def fake_complete(*args) -> UUID:
        completed.append(args)
        return uuid4()

    activity: list[str] = []

    async def fake_record(_owner_id, event_type, *_args) -> None:
        activity.append(event_type)

    monkeypatch.setattr("app.chat.orchestrator.answer_agent", agent)
    monkeypatch.setattr("app.chat.orchestrator.completed_history", fake_history)
    monkeypatch.setattr("app.chat.orchestrator.complete_turn", fake_complete)
    monkeypatch.setattr("app.chat.orchestrator.record_activity", fake_record)

    events = await collect_events(
        FakeRequest(), user, THREAD_ID, USER_MESSAGE_ID, REQUEST_ID, "What was revenue?", None, FakeRetriever([passage()])
    )

    assert 'event: answer' in "".join(events)
    assert 'event: citations' in "".join(events)
    assert 'event: complete' in "".join(events)
    assert completed[0][3] == answer()
    assert str(CHUNK_ID) in agent.prompt
    assert activity == ["answer_completed"]


@pytest.mark.anyio
async def test_empty_retrieval_skips_the_agent(monkeypatch, user) -> None:
    completed = []

    async def fake_complete(*args) -> UUID:
        completed.append(args)
        return uuid4()

    monkeypatch.setattr("app.chat.orchestrator.complete_turn", fake_complete)

    events = await collect_events(
        FakeRequest(), user, THREAD_ID, USER_MESSAGE_ID, REQUEST_ID, "What was revenue?", None, FakeRetriever([])
    )

    assert 'event: complete' in "".join(events)
    assert completed[0][3].insufficient_evidence is True
    assert '"insufficient_evidence":true' in "".join(events)


@pytest.mark.anyio
@pytest.mark.anyio
async def test_disconnected_stream_never_persists_an_answer(monkeypatch, user) -> None:
    failures = []

    async def fake_complete(*args) -> UUID:
        raise AssertionError("cancelled answer must not be persisted")

    async def fake_finish(*args) -> None:
        failures.append(args)

    monkeypatch.setattr("app.chat.orchestrator.complete_turn", fake_complete)
    monkeypatch.setattr("app.chat.orchestrator.finish_failed_turn", fake_finish)

    await collect_events(
        FakeRequest(disconnected=True), user, THREAD_ID, USER_MESSAGE_ID, REQUEST_ID, "What was revenue?", None, FakeRetriever([])
    )

    assert failures[0][3:] == ("cancelled", "client_disconnected")


@pytest.mark.anyio
async def test_disconnect_during_generation_cancels_the_agent(monkeypatch, user) -> None:
    failures = []
    agent = FakeAgent(answer(), block=True)

    async def fake_history(*args) -> list[tuple[str, str]]:
        return []

    async def fake_finish(*args) -> None:
        failures.append(args)

    monkeypatch.setattr("app.chat.orchestrator.answer_agent", agent)
    monkeypatch.setattr("app.chat.orchestrator.completed_history", fake_history)
    monkeypatch.setattr("app.chat.orchestrator.finish_failed_turn", fake_finish)

    await collect_events(
        FakeRequest(states=[False, False, True]),
        user,
        THREAD_ID,
        USER_MESSAGE_ID,
        REQUEST_ID,
        "What was revenue?",
        None,
        FakeRetriever([passage()]),
    )

    assert agent.cancelled is True
    assert failures[0][3:] == ("cancelled", "client_disconnected")


@pytest.mark.anyio
async def test_upstream_error_is_not_persisted(monkeypatch, user) -> None:
    failures = []

    async def fake_history(*args) -> list[tuple[str, str]]:
        return []

    async def fake_complete(*args) -> UUID:
        raise AssertionError("failed answer must not be persisted")

    async def fake_finish(*args) -> None:
        failures.append(args)

    monkeypatch.setattr("app.chat.orchestrator.answer_agent", FailingAgent())
    monkeypatch.setattr("app.chat.orchestrator.completed_history", fake_history)
    monkeypatch.setattr("app.chat.orchestrator.complete_turn", fake_complete)
    monkeypatch.setattr("app.chat.orchestrator.finish_failed_turn", fake_finish)

    events = await collect_events(
        FakeRequest(), user, THREAD_ID, USER_MESSAGE_ID, REQUEST_ID, "What was revenue?", None, FakeRetriever([passage()])
    )

    assert 'event: error' in "".join(events)
    assert failures[0][3:5] == ("failed", "generation_failed")
