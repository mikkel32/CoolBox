import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List
import asyncio


def scan_ports(host: str, start: int, end: int,
               progress: Callable[[float | None], None] | None = None) -> List[int]:
    """Scan *host* from *start* to *end* and return a list of open ports.

    If *progress* is provided it will be called with values between 0 and 1
    as scanning progresses. When scanning completes ``progress(None)`` is
    called to signal completion.
    """
    open_ports = []
    total = end - start + 1

    def scan(port: int) -> int | None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((host, port)) == 0:
                return port
        return None

    with ThreadPoolExecutor(max_workers=min(100, total)) as executor:
        future_to_port = {executor.submit(scan, p): p for p in range(start, end + 1)}
        for i, future in enumerate(as_completed(future_to_port), 1):
            if progress is not None:
                progress(i / total)
            result = future.result()
            if result is not None:
                open_ports.append(result)

    if progress is not None:
        progress(None)
    return sorted(open_ports)


async def async_scan_ports(
    host: str,
    start: int,
    end: int,
    progress: Callable[[float | None], None] | None = None,
    concurrency: int = 100,
) -> List[int]:
    """Asynchronously scan *host* and return a list of open ports.

    ``concurrency`` limits the number of simultaneous connection attempts,
    preventing excessive resource usage when scanning large port ranges.
    """

    open_ports: list[int] = []
    total = end - start + 1
    completed = 0

    sem = asyncio.Semaphore(max(1, min(concurrency, total)))

    async def scan(port: int) -> int | None:
        nonlocal completed
        try:
            async with sem:
                conn = asyncio.open_connection(host, port)
                reader, writer = await asyncio.wait_for(conn, timeout=0.5)
                writer.close()
                await writer.wait_closed()
                return port
        except Exception:
            return None
        finally:
            completed += 1
            if progress is not None:
                progress(completed / total)

    tasks = [asyncio.create_task(scan(p)) for p in range(start, end + 1)]
    for task in asyncio.as_completed(tasks):
        result = await task
        if result is not None:
            open_ports.append(result)

    if progress is not None:
        progress(None)

    return sorted(open_ports)
