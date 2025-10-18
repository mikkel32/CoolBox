from typing import Tuple, Union

Address = Union[int, Tuple[str, int]]

def listen(address: Address) -> None: ...

def wait_for_client() -> None: ...

def is_client_connected() -> bool: ...

__all__ = ["listen", "wait_for_client", "is_client_connected", "Address"]
