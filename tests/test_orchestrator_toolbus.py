import asyncio
import json
from typing import Any

from coolbox.console.events import TaskEvent
from coolbox.proto import toolbus_pb2
from coolbox.setup.orchestrator import SetupOrchestrator, SetupStage


def test_orchestrator_publishes_dashboard_events(tmp_path):
    async def runner():
        orchestrator = SetupOrchestrator(root=tmp_path)
        request = toolbus_pb2.SubscribeRequest(
            header=toolbus_pb2.Header(
                request_id="sub-1",
                tool="setup.events",
            ),
            topics=("setup.events",),
        )
        subscription = await orchestrator.tool_bus.subscribe(request)
        received: list[dict[str, Any]] = []

        async def consume():
            async for event in subscription:
                received.append(
                    {
                        "topic": event.topic,
                        "metadata": dict(event.metadata),
                        "payload": json.loads(event.payload.decode("utf-8")),
                    }
                )
                break

        consumer = asyncio.create_task(consume())
        orchestrator._publish(TaskEvent("demo", SetupStage.PREFLIGHT, status="started"))
        await asyncio.wait_for(consumer, timeout=1.0)
        await subscription.close()
        assert received
        event: dict[str, Any] = received[0]
        assert event["topic"] == "setup.events"
        assert event["metadata"]["source"] == "orchestrator"
        assert event["payload"]["type"] == "TaskEvent"

    asyncio.run(runner())
