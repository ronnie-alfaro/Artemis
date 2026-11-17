from __future__ import annotations

import asyncio
from uuid import uuid4

from test_karakeep import FakeKarakeep
from test_seerr import FakeSeerr
from test_usenet import FakeDownloads

from app.api.main import build_orchestrator
from app.application.skill_sessions import MemorySkillSessionStore
from app.domain.models import ApprovalStatus, Channel, IncomingMessage
from app.domain.skills import SkillPresentation


def test_switching_routes_plain_search_and_help_to_active_skill() -> None:
    async def scenario():
        bookmarks, downloads = FakeKarakeep(), FakeDownloads()
        runtime = build_orchestrator(karakeep_client=bookmarks, usenet_client=downloads)
        conversation = uuid4()

        async def send(content):
            result = await runtime.handle(IncomingMessage(
                conversation_id=conversation, channel=Channel(name="whatsapp"), content=content,
            ))
            assert all(execution.result for execution in result.executions)
            return result

        ambiguous = await send("busca Rocky")
        assert "¿En qué habilidad" in ambiguous.message.content
        assert not downloads.searches and not bookmarks.queries
        assert "Usenet activo" in (await send("utiliza usenet")).message.content
        assert (await send("busca Rocky")).executions[0].agent_name == "usenet"
        assert downloads.searches == [("Rocky", "")]
        help_text = (await send("ayuda")).message.content
        assert help_text.startswith("Usenet\n") and "baja el 2" in help_text
        assert "salir" in help_text
        # Explicit help for another skill does not change the active one.
        assert (await send("ayuda Karakeep")).message.content.startswith("Karakeep\n")
        assert (await send("estado de descarga")).executions[0].agent_name == "usenet"
        assert "Karakeep activo" in (await send("utiliza karakeep")).message.content
        assert (await send("busca docker")).executions[0].agent_name == "karakeep"
        assert bookmarks.queries == ["docker"]
        assert "Modo general" in (await send("salir")).message.content
        assert "¿En qué habilidad" in (await send("busca Rocky")).message.content
        general_help = (await send("ayuda")).message.content
        assert "Puedo ayudarte" in general_help
        assert "baja el 2" not in general_help

    asyncio.run(scenario())


def test_custom_name_unknown_skill_and_channel_isolation() -> None:
    async def scenario():
        fake = FakeKarakeep()
        runtime = build_orchestrator(karakeep_client=fake)
        runtime.registry.get("status").presentations["karakeep"] = SkillPresentation(
            name="Mis enlaces", description="Consulta mis bookmarks."
        )
        conversation = uuid4()

        async def send(content, channel="whatsapp", conversation_id=conversation, allowed=None):
            return await runtime.handle(IncomingMessage(
                conversation_id=conversation_id,
                channel=Channel(name=channel, allowed_capabilities=allowed or []), content=content,
            ))

        assert "Mis enlaces activo" in (await send("UTILIZA Mis enlaces")).message.content
        assert "no está disponible" in (await send("utiliza inexistente")).message.content
        assert (await send("busca docker")).executions[0].agent_name == "karakeep"
        assert "¿En qué habilidad" in (await send("busca docker", channel="rest")).message.content
        assert "¿En qué habilidad" in (await send(
            "busca docker", conversation_id=uuid4()
        )).message.content
        assert "no está disponible" in (await send(
            "utiliza usenet", conversation_id=uuid4(), allowed=["karakeep.bookmarks"]
        )).message.content
        assert fake.queries == ["docker"]
        # Revoking a binding invalidates the persisted selection before any skill runs.
        assert "ya no está asignada" in (await send(
            "busca docker", allowed=["assistant.status"]
        )).message.content
        assert "¿En qué habilidad" in (await send("busca docker")).message.content
        assert fake.queries == ["docker"]

    asyncio.run(scenario())


def test_switch_and_exit_cancel_approvals_but_same_skill_keeps_them() -> None:
    async def scenario():
        fake = FakeKarakeep()
        runtime = build_orchestrator(karakeep_client=fake)
        conversation = uuid4()

        async def send(content):
            return await runtime.handle(IncomingMessage(
                conversation_id=conversation, channel=Channel(name="whatsapp"), content=content,
            ))

        await send("utiliza karakeep")
        await send("guarda https://example.com")
        original = runtime.approvals.pending_for_conversation(conversation)[0]
        await send("utiliza karakeep")
        assert runtime.approvals.get(original.id).status is ApprovalStatus.PENDING
        await send("utiliza inexistente")
        assert runtime.approvals.get(original.id).status is ApprovalStatus.PENDING
        assert "cancelaron 1" in (await send("utiliza usenet")).message.content
        assert runtime.approvals.get(original.id).status is ApprovalStatus.REJECTED
        await send("confirmo")
        assert fake.created == []
        # A rejected save can be proposed again after returning to the skill.
        await send("utiliza karakeep")
        await send("guarda https://example.com")
        replacement = runtime.approvals.pending_for_conversation(conversation)[0]
        assert replacement.id != original.id
        assert "cancelaron 1" in (await send("salir")).message.content
        assert runtime.approvals.get(replacement.id).status is ApprovalStatus.REJECTED
        await send("confirmo")
        assert fake.created == []

    asyncio.run(scenario())


def test_switch_discards_old_search_selections() -> None:
    async def scenario():
        downloads = FakeDownloads()
        runtime = build_orchestrator(usenet_client=downloads)
        conversation = uuid4()

        async def send(content):
            return await runtime.handle(IncomingMessage(
                conversation_id=conversation, channel=Channel(name="whatsapp"), content=content,
            ))

        await send("utiliza usenet")
        await send("busca Rocky")
        await send("utiliza karakeep")
        await send("utiliza usenet")
        await send("baja el 2")
        assert runtime.approvals.pending_for_conversation(conversation) == []
        assert downloads.started == []

    asyncio.run(scenario())


def test_selection_is_restored_by_new_orchestrator_and_exit_is_persisted() -> None:
    async def scenario():
        # The durable store has the same interface. A new router reads the saved selection.
        store = MemorySkillSessionStore()
        conversation = uuid4()
        fake = FakeKarakeep()
        first = build_orchestrator(karakeep_client=fake)
        first.skill_sessions.store = store

        async def send(runtime, content):
            return await runtime.handle(IncomingMessage(
                conversation_id=conversation, channel=Channel(name="whatsapp"), content=content,
            ))

        await send(first, "utiliza karakeep")
        second = build_orchestrator(karakeep_client=fake)
        second.skill_sessions.store = store
        assert (await send(second, "busca docker")).executions[0].agent_name == "karakeep"
        await send(second, "salir")
        third = build_orchestrator(karakeep_client=fake)
        third.skill_sessions.store = store
        assert "¿En qué habilidad" in (await send(third, "busca docker")).message.content

    asyncio.run(scenario())


def test_seerr_active_search_removes_search_command_from_query() -> None:
    class SearchSeerr(FakeSeerr):
        async def search_media(self, query):
            assert query == "Dune"
            return await super().search_media(query)

    async def scenario():
        runtime = build_orchestrator(seerr_client=SearchSeerr())
        conversation = uuid4()
        for text in ("utiliza seerr", "busca Dune"):
            response = await runtime.handle(IncomingMessage(
                conversation_id=conversation, channel=Channel(name="whatsapp"), content=text,
            ))
        assert response.executions[0].agent_name == "seerr"
        assert "Dune" in response.message.content

    asyncio.run(scenario())


def test_switch_waits_for_running_command_in_same_conversation() -> None:
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        class SlowKarakeep(FakeKarakeep):
            async def search_bookmarks(self, query):
                started.set()
                await release.wait()
                return await super().search_bookmarks(query)

        runtime = build_orchestrator(karakeep_client=SlowKarakeep())
        conversation = uuid4()

        async def send(content):
            return await runtime.handle(IncomingMessage(
                conversation_id=conversation, channel=Channel(name="whatsapp"), content=content,
            ))

        await send("utiliza karakeep")
        search = asyncio.create_task(send("busca docker"))
        await started.wait()
        switch = asyncio.create_task(send("utiliza usenet"))
        await asyncio.sleep(0)
        assert not switch.done()
        release.set()
        assert (await search).executions[0].agent_name == "karakeep"
        assert "Usenet activo" in (await switch).message.content
        assert (await send("ayuda")).message.content.startswith("Usenet\n")

    asyncio.run(scenario())


def test_reaction_choices_follow_skill_routing_and_preserve_write_confirmation():
    async def scenario():
        seerr = FakeSeerr()
        runtime = build_orchestrator(seerr_client=seerr, usenet_client=FakeDownloads())
        conversation = uuid4()

        async def send(content):
            return await runtime.handle(IncomingMessage(
                conversation_id=conversation, channel=Channel(name="whatsapp"), content=content,
            ))

        menu = await send("ayuda")
        choices = {option.command: option for option in menu.message.reaction_options}
        assert "utiliza seerr" in choices and "utiliza usenet" in choices
        await send(choices["utiliza seerr"].command)
        search = await send("busca Dune")
        assert search.message.reaction_options[0].command == "1"
        proposal = await send(search.message.reaction_options[0].command)
        assert "confirmo" in proposal.message.content
        assert seerr.created == 0
        # Choosing a result prepares the operation; it does not approve it.
        assert not proposal.message.reaction_options
        await send("salir")
        ambiguous = await send("busca Rocky")
        option = next(
            o for o in ambiguous.message.reaction_options if o.command == "utiliza usenet"
        )
        await send(option.command)
        results = await send("busca Rocky")
        assert results.message.reaction_options[0].command == "baja el 1"
        assert seerr.created == 0

    asyncio.run(scenario())
