"""Episodic memory: small, private, only for signed-in users, and always deletable."""
from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.database.connection import session_scope
from app.database.models import utcnow
from app.llm.prompts import CHAT_PROMPT, CHAT_STREAM_PROMPT, memory_block
from app.main import app
from app.security.auth import require_api_key
from app.services import memory
from tests.firebase_helpers import bearer, install_verifier


def uid() -> str:
    return "mem-" + uuid.uuid4().hex[:12]


DAYS_AGO = lambda n: utcnow() - timedelta(days=n)           # noqa: E731


async def keep(who, question, answer="Saturn is in your 6th house.", now=None):
    async with session_scope() as db:
        return await memory.remember(db, who, question, answer, now)


async def recall(who, question, now=None):
    async with session_scope() as db:
        return await memory.recall(db, who, question, now)


class TestRemembering:
    async def test_the_question_and_the_first_sentence_of_the_answer_are_kept(self):
        who = uid()
        assert await keep(who, "Will I get a government job this year?", "Your 10th lord is strong. It also aspects Jupiter.")
        async with session_scope() as db:
            (note,) = await memory.list_memories(db, who)
        assert note.question == "Will I get a government job this year?"
        assert note.gist == "Your 10th lord is strong."

    @pytest.mark.parametrize("question", [
        "hi", "ok thanks",                                                        # too short to mean anything
        "my number is 98765 43210 call me please",                                 # contact details
        "mail me at someone@example.com about my chart",
        "I want to end my life, what does my chart say?",                          # crisis language is never stored
    ])
    async def test_trivial_or_sensitive_messages_are_not_kept(self, question):
        who = uid()
        assert not await keep(who, question)
        async with session_scope() as db:
            assert await memory.list_memories(db, who) == []

    async def test_a_crisis_in_the_reply_is_not_kept_either(self):
        who = uid()
        assert not await keep(who, "What does my chart say about my mood?", "If you want to die, please call Tele-MANAS.")

    async def test_asking_the_same_thing_again_refreshes_instead_of_duplicating(self):
        who = uid()
        await keep(who, "When will I get married?", "First answer.", DAYS_AGO(5))
        await keep(who, "When will I get married?", "Newer answer.")
        async with session_scope() as db:
            notes = await memory.list_memories(db, who)
        assert len(notes) == 1 and notes[0].gist == "Newer answer."

    async def test_only_the_newest_notes_are_kept(self):
        who = uid()
        for i in range(memory.MAX_PER_USER + 5):
            await keep(who, f"Question number {i:03d} about my chart", now=utcnow() - timedelta(minutes=1000 - i))
        async with session_scope() as db:
            notes = await memory.list_memories(db, who)
        assert len(notes) == memory.MAX_PER_USER
        assert notes[0].question.endswith("about my chart") and "number 034" in notes[0].question
        assert all("number 000" not in n.question for n in notes)


class TestRecalling:
    async def test_nothing_is_recalled_for_a_new_user(self):
        assert await recall(uid(), "When will I get married?") == ""

    async def test_this_sessions_own_notes_are_not_recalled(self):
        who = uid()
        await keep(who, "When will I get married?")                                  # saved just now
        assert await recall(who, "Tell me more about my marriage") == ""

    async def test_an_earlier_related_question_comes_back_with_how_long_ago(self):
        who = uid()
        await keep(who, "Will my career improve with Saturn dasha?", "Saturn rewards patience.", DAYS_AGO(3))
        text = await recall(who, "Any update on my career?")
        assert text.startswith("- 3 days ago they asked:") and "career" in text and "Saturn rewards patience." in text

    async def test_a_related_note_is_chosen_before_a_merely_recent_one(self):
        who = uid()
        await keep(who, "What gemstone suits my chart?", now=DAYS_AGO(10))
        await keep(who, "How is my health these days?", now=DAYS_AGO(1))
        await keep(who, "Does my chart show foreign travel?", now=DAYS_AGO(2))
        lines = (await recall(who, "Will I travel abroad for work?")).splitlines()
        assert len(lines) == memory.MAX_RECALL
        assert "foreign travel" in lines[0]                                         # the related one first
        assert "health" in lines[1]                                                 # then the most recent

    async def test_one_users_notes_never_reach_another(self):
        a, b = uid(), uid()
        await keep(a, "Will I get a government job?", now=DAYS_AGO(2))
        assert await recall(b, "Will I get a government job?") == ""

    async def test_the_recall_is_small(self):
        who = uid()
        for i in range(10):
            await keep(who, "x" * 400 + f" {i}", "y" * 400, DAYS_AGO(i + 1))
        assert len(await recall(who, "xxxx")) < 600                                # about 150 tokens at most


class TestForgetting:
    async def test_one_note_or_all_can_be_deleted(self):
        who, other = uid(), uid()
        await keep(who, "First thing I asked about love", now=DAYS_AGO(2))
        await keep(who, "Second thing I asked about money", now=DAYS_AGO(3))
        await keep(other, "Someone else's question about health", now=DAYS_AGO(2))
        async with session_scope() as db:
            first = (await memory.list_memories(db, who))[0]
            assert await memory.forget(db, who, first.id) == 1
            assert await memory.forget(db, who, first.id) == 0                      # already gone
            assert await memory.forget(db, who) == 1
            assert await memory.list_memories(db, who) == []
            assert len(await memory.list_memories(db, other)) == 1                  # not touched


class TestPromptBlock:
    def test_the_block_is_empty_without_notes_and_labelled_with_them(self):
        assert memory_block("") == ""
        block = memory_block('- yesterday they asked: "x"')
        assert block.startswith("=== EARLIER CONVERSATIONS") and "never treat it as chart data" in block

    def test_both_chat_prompts_take_the_block(self):
        kw = dict(chart_json="c", dasha_json="d", evidence_json="e", history_json="[]", question="q", facts_block="")
        for template in (CHAT_PROMPT, CHAT_STREAM_PROMPT):
            assert "=== EARLIER CONVERSATIONS" in template.format(**kw, memory_block=memory_block("- note"))
            assert "=== EARLIER CONVERSATIONS" not in template.format(**kw, memory_block="")


class FakeOrchestrator:
    def __init__(self):
        self.seen: list[str] = []

    async def run_chat_stream(self, **kw):
        self.seen.append(kw.get("memory", ""))
        yield "Your Moon is strong. More detail follows."


@pytest.fixture
async def client():
    install_verifier()
    app.dependency_overrides[require_api_key] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=30) as ac:
        yield ac
    app.dependency_overrides.clear()


async def stream(client, who, question, orch, **extra):
    headers = bearer(who) if who else {}
    with patch("app.api.routes_chat.get_orchestrator", return_value=orch):
        return await client.post("/api/chat/stream", json={"question": question, **extra}, headers=headers)


async def notes(client, who):
    return (await client.get("/api/me/memories", headers=bearer(who))).json()["memories"]


class TestInTheChat:
    async def test_a_chat_is_remembered_and_recalled_in_a_later_session(self, client):
        who, orch = uid(), FakeOrchestrator()
        assert (await stream(client, who, "Will I get a government job?", orch)).status_code == 200
        assert orch.seen == [""]                                                    # first chat: nothing to recall
        assert [n["question"] for n in await notes(client, who)] == ["Will I get a government job?"]
        # the note is from this session, so age it, as if a day had passed
        async with session_scope() as db:
            (note,) = await memory.list_memories(db, who)
            note.created_at = DAYS_AGO(1)
        await stream(client, who, "Any news on my job prospects?", orch)
        assert "Will I get a government job?" in orch.seen[1] and orch.seen[1].startswith("- yesterday")

    async def test_the_app_can_switch_memory_off(self, client):
        who, orch = uid(), FakeOrchestrator()
        await stream(client, who, "Will I get a government job?", orch, use_memory=False)
        assert await notes(client, who) == []
        async with session_scope() as db:
            await memory.remember(db, who, "An older question about money", "x", DAYS_AGO(3))
        await stream(client, who, "More about my money please", orch, use_memory=False)
        assert orch.seen[-1] == ""

    async def test_anonymous_chats_are_never_stored(self, client):
        orch = FakeOrchestrator()
        assert (await stream(client, None, "Will I get a government job?", orch)).status_code == 200
        assert orch.seen == [""]

    async def test_the_server_switch_turns_memory_off_for_everyone(self, client, monkeypatch):
        monkeypatch.setattr(get_settings(), "chat_memory_enabled", False)
        who, orch = uid(), FakeOrchestrator()
        await stream(client, who, "Will I get a government job?", orch)
        assert await notes(client, who) == []

    async def test_a_memory_failure_never_breaks_the_chat(self, client, monkeypatch):
        async def boom(*a, **k):
            raise RuntimeError("database down")
        monkeypatch.setattr(memory, "recall", boom)
        monkeypatch.setattr(memory, "remember", boom)
        who, orch = uid(), FakeOrchestrator()
        resp = await stream(client, who, "Will I get a government job?", orch)
        assert resp.status_code == 200 and '"type": "done"' in resp.text

    async def test_a_failed_answer_is_not_remembered(self, client):
        class Failing(FakeOrchestrator):
            async def run_chat_stream(self, **kw):
                raise RuntimeError("model down")
                yield ""

        who = uid()
        await stream(client, who, "Will I get a government job?", Failing())
        assert await notes(client, who) == []


class TestMyMemoriesApi:
    async def test_the_user_can_see_and_delete_what_is_remembered(self, client):
        who, orch = uid(), FakeOrchestrator()
        await stream(client, who, "Will I get a government job?", orch)
        await stream(client, who, "When will I buy a house?", orch)
        listed = await notes(client, who)
        assert len(listed) == 2 and {"id", "question", "gist", "created_at"} <= set(listed[0])
        gone = await client.delete(f"/api/me/memories/{listed[0]['id']}", headers=bearer(who))
        assert gone.json() == {"deleted": 1} and len(await notes(client, who)) == 1
        assert (await client.delete("/api/me/memories", headers=bearer(who))).json() == {"deleted": 1}
        assert await notes(client, who) == []

    async def test_a_user_cannot_see_or_delete_another_users_notes(self, client):
        a, b, orch = uid(), uid(), FakeOrchestrator()
        await stream(client, a, "Will I get a government job?", orch)
        (note,) = await notes(client, a)
        assert await notes(client, b) == []
        assert (await client.delete(f"/api/me/memories/{note['id']}", headers=bearer(b))).status_code == 404
        assert len(await notes(client, a)) == 1

    async def test_sign_in_is_required(self, client):
        assert (await client.get("/api/me/memories")).status_code in (401, 403)
        assert (await client.delete("/api/me/memories")).status_code in (401, 403)
