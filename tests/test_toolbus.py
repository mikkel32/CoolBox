import json
import asyncio

import pytest

from coolbox.tools import ToolBus
from coolbox.proto import toolbus_pb2


def test_toolbus_invoke_local():
    bus = ToolBus()

    def handler(context, payload: bytes):
        assert context.tool == "echo"
        data = json.loads(payload.decode("utf-8")) if payload else {}
        return {"received": data.get("message")}

    async def runner():
        bus.register_local("echo", invoke=handler)
        request = toolbus_pb2.InvokeRequest(
            header=toolbus_pb2.Header(request_id="req-1", tool="echo"),
            payload=json.dumps({"message": "hello"}).encode("utf-8"),
        )
        response = await bus.invoke(request)
        assert response.status == toolbus_pb2.StatusCode.STATUS_OK
        assert json.loads(response.payload.decode("utf-8")) == {"received": "hello"}

    asyncio.run(runner())


def test_toolbus_stream_local():
    bus = ToolBus()

    async def handler(context, payload: bytes):
        yield json.dumps({"chunk": 1}).encode("utf-8")
        yield json.dumps({"chunk": 2}).encode("utf-8")

    async def runner():
        bus.register_local("stream", stream=handler)
        request = toolbus_pb2.StreamRequest(
            header=toolbus_pb2.Header(request_id="req-2", tool="stream"),
            payload=b"{}",
        )
        chunks = []
        async for chunk in bus.stream(request):
            if chunk.end_of_stream:
                assert chunk.status == toolbus_pb2.StatusCode.STATUS_OK
                break
            chunks.append(json.loads(chunk.payload.decode("utf-8")))
        assert chunks == [{"chunk": 1}, {"chunk": 2}]

    asyncio.run(runner())


def test_toolbus_subscribe_local():
    bus = ToolBus()

    async def runner():
        request = toolbus_pb2.SubscribeRequest(
            header=toolbus_pb2.Header(request_id="req-3", tool="events"),
            topics=["events"],
        )
        subscription = await bus.subscribe(request)

        async def consume():
            events = []
            async for event in subscription:
                events.append(json.loads(event.payload.decode("utf-8")))
                if len(events) == 1:
                    break
            await subscription.close()
            return events

        consumer = asyncio.create_task(consume())
        bus.publish("events", {"message": "hello"})
        events = await consumer
        assert events == [{"message": "hello"}]

    asyncio.run(runner())
