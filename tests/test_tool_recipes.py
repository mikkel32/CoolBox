import asyncio
import json
from pathlib import Path
from typing import Sequence

import pytest

from coolbox.tools import (
    GuardViolation,
    ToolBus,
    ToolRecipe,
    ToolRecipeClause,
    ToolRecipeLoader,
    ToolRecipeSigner,
)


def test_tool_recipe_execution(tmp_path: Path):
    bus = ToolBus()

    def echo(context, payload: bytes):
        data = json.loads(payload.decode("utf-8"))
        return {"echo": data["message"]}

    async def runner():
        bus.register_local("tools.echo", invoke=echo)
        document = {
            "name": "demo",
            "version": 1,
            "clauses": [
                {
                    "name": "echo",
                    "map": [
                        {
                            "tool": "tools.echo",
                            "payload": {"message": "hello"},
                        }
                    ],
                    "reduce": "collect",
                    "guard": {"eq": [{"var": "aggregate.0.echo"}, "hello"]},
                }
            ],
        }
        signer = ToolRecipeSigner({"local": b"secret"})
        path = tmp_path / "recipe.json"
        signed = dict(document)
        signed["signature"] = signer.sign(document, key_id="local")
        path.write_text(json.dumps(signed), encoding="utf-8")
        loader = ToolRecipeLoader(signer=signer)
        recipe = loader.load(path)
        summary = await recipe.execute(bus)
        assert summary[0]["aggregate"] == [{"echo": "hello"}]

    asyncio.run(runner())


def test_tool_recipe_guard_violation():
    bus = ToolBus()

    def handler(context, payload: bytes):
        return {"value": "mismatch"}

    async def runner():
        bus.register_local("tools.guard", invoke=handler)
        clause = ToolRecipeClause(
            name="guard",
            map_steps=(
                {"tool": "tools.guard", "payload": {"message": "expected"}},
            ),
            guard={"eq": [{"var": "aggregate.0.value"}, "expected"]},
        )
        recipe = ToolRecipe(name="guard", version=1, clauses=(clause,))
        with pytest.raises(GuardViolation):
            await recipe.execute(bus)

    asyncio.run(runner())


def test_tool_recipe_stream_and_subscribe(tmp_path: Path):
    bus = ToolBus()

    async def stream_handler(context, payload: bytes):
        data = json.loads(payload.decode("utf-8")) if payload else {}

        async def iterator():
            start = int(data.get("start", 0))
            for index in range(3):
                yield {"index": index, "value": start + index}

        return iterator()

    async def subscribe_handler(context, topics: Sequence[str]):
        async def iterator():
            for idx, topic in enumerate(topics):
                yield {
                    "topic": topic,
                    "payload": {"message": f"event-{idx}"},
                    "metadata": {"source": "subscription"},
                }

        return iterator()

    async def runner():
        bus.register_local(
            "tools.streamer",
            stream=stream_handler,
        )
        bus.register_local(
            "tools.events",
            subscribe=subscribe_handler,
        )
        document = {
            "name": "stream-subscribe",
            "version": 1,
            "clauses": [
                {
                    "name": "stream", "map": [
                        {
                            "tool": "tools.streamer",
                            "mode": "stream",
                            "payload": {"start": 5},
                        }
                    ],
                    "guard": {
                        "eq": [
                            {"var": "aggregate.0.chunks.0.value"},
                            5,
                        ]
                    },
                },
                {
                    "name": "subscribe",
                    "map": [
                        {
                            "tool": "tools.events",
                            "mode": "subscribe",
                            "topics": ["topic.a", "topic.b"],
                            "limit": 2,
                        }
                    ],
                    "guard": {
                        "all": [
                            {
                                "eq": [
                                    {"var": "aggregate.0.events.0.topic"},
                                    "topic.a",
                                ]
                            },
                            {
                                "eq": [
                                    {"var": "aggregate.0.events.1.metadata.source"},
                                    "subscription",
                                ]
                            },
                        ]
                    },
                },
            ],
        }
        signer = ToolRecipeSigner({"local": b"secret"})
        path = tmp_path / "recipe-stream.json"
        signed = dict(document)
        signed["signature"] = signer.sign(document, key_id="local")
        path.write_text(json.dumps(signed), encoding="utf-8")
        loader = ToolRecipeLoader(signer=signer)
        recipe = loader.load(path)
        summary = await recipe.execute(bus)
        assert len(summary) == 2
        stream_clause, subscribe_clause = summary
        assert stream_clause["aggregate"][0]["chunks"][1]["value"] == 6
        assert subscribe_clause["aggregate"][0]["events"][0]["payload"]["message"] == "event-0"

    asyncio.run(runner())
