"""Declarative DSL for tool orchestration recipes."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from coolbox.proto import toolbus_pb2

from .bus import ToolBus


class RecipeExecutionError(RuntimeError):
    """Base error raised when a recipe cannot be executed."""


class RecipeSignatureError(RecipeExecutionError):
    """Raised when a signed recipe fails verification."""


class GuardViolation(RecipeExecutionError):
    """Raised when a guard clause rejects a clause result."""


@dataclass(slots=True)
class ToolRecipeClause:
    """A clause within a recipe supporting when/map/reduce/guard."""

    name: str | None
    when: Any = None
    map_steps: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    reduce_spec: Mapping[str, Any] | str | None = None
    guard: Any = None

    def should_run(self, scope: Mapping[str, Any]) -> bool:
        if self.when is None:
            return True
        return bool(_evaluate_expression(self.when, scope))

    async def execute(self, bus: ToolBus, scope: MutableMapping[str, Any]) -> Mapping[str, Any]:
        step_results: list[Mapping[str, Any]] = []
        clause_scope = dict(scope)
        clause_scope.update({
            "clause": self.name,
            "steps": step_results,
        })
        for raw_step in self.map_steps:
            rendered_step = _render_template(raw_step, clause_scope)
            clause_scope["step"] = rendered_step
            result = await _execute_step(bus, rendered_step)
            step_results.append(result)
        aggregate = _apply_reduce(self.reduce_spec, step_results, clause_scope)
        guard_scope = dict(clause_scope)
        guard_scope.update({
            "steps": step_results,
            "aggregate": aggregate,
        })
        if self.guard is not None:
            if not bool(_evaluate_expression(self.guard, guard_scope)):
                raise GuardViolation(f"Guard for clause '{self.name or '<unnamed>'}' rejected the results")
        return {
            "name": self.name,
            "steps": step_results,
            "aggregate": aggregate,
        }


@dataclass(slots=True)
class ToolRecipe:
    """Executable recipe composed of ordered clauses."""

    name: str
    version: int
    clauses: Sequence[ToolRecipeClause]
    metadata: Mapping[str, Any] = field(default_factory=dict)
    signature: Mapping[str, str] | None = None
    source: Path | None = None

    async def execute(
        self,
        bus: ToolBus,
        *,
        context: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> list[Mapping[str, Any]]:
        """Execute the recipe and return clause summaries."""

        context_scope = dict(context or {})
        payload_scope = dict(payload or {})
        summaries: list[Mapping[str, Any]] = []
        base_scope: MutableMapping[str, Any] = {
            "context": context_scope,
            "payload": payload_scope,
            "results": summaries,
            "metadata": self.metadata,
        }
        for clause in self.clauses:
            if not clause.should_run(base_scope):
                continue
            result = await clause.execute(bus, base_scope)
            summaries.append(result)
        return summaries

    def to_document(self) -> Mapping[str, Any]:
        """Return a JSON-serialisable mapping representing the recipe."""

        return {
            "name": self.name,
            "version": self.version,
            "metadata": dict(self.metadata),
            "clauses": [
                {
                    key: value
                    for key, value in {
                        "name": clause.name,
                        "when": clause.when,
                        "map": clause.map_steps,
                        "reduce": clause.reduce_spec,
                        "guard": clause.guard,
                    }.items()
                    if value is not None
                }
                for clause in self.clauses
            ],
        }


class ToolRecipeSigner:
    """Sign and verify recipe documents using HMAC-SHA256."""

    def __init__(self, secrets: Mapping[str, bytes | str], *, algorithm: str = "HS256") -> None:
        if algorithm != "HS256":
            raise ValueError("Only HS256 is supported")
        processed: dict[str, bytes] = {}
        for key, secret in secrets.items():
            if isinstance(secret, str):
                processed[str(key)] = secret.encode("utf-8")
            else:
                processed[str(key)] = bytes(secret)
        self._secrets = processed
        self.algorithm = algorithm

    def sign(self, document: Mapping[str, Any], *, key_id: str) -> Mapping[str, str]:
        key_id = str(key_id)
        secret = self._resolve_secret(key_id)
        digest = hmac.new(secret, _canonical_bytes(document), hashlib.sha256).digest()
        return {
            "algorithm": self.algorithm,
            "key_id": key_id,
            "value": base64.urlsafe_b64encode(digest).decode("ascii"),
        }

    def verify(self, document: Mapping[str, Any], signature: Mapping[str, Any]) -> None:
        algorithm = str(signature.get("algorithm", ""))
        if algorithm != self.algorithm:
            raise RecipeSignatureError(f"Unsupported signature algorithm: {algorithm}")
        key_id = signature.get("key_id")
        if key_id is None:
            raise RecipeSignatureError("Signature missing key identifier")
        expected = self.sign(document, key_id=str(key_id))
        provided = signature.get("value")
        if provided is None:
            raise RecipeSignatureError("Signature missing value")
        if not hmac.compare_digest(expected["value"], str(provided)):
            raise RecipeSignatureError("Recipe signature verification failed")

    def _resolve_secret(self, key_id: str) -> bytes:
        try:
            return self._secrets[key_id]
        except KeyError as exc:  # pragma: no cover - defensive path
            raise RecipeSignatureError(f"No secret registered for key '{key_id}'") from exc


class ToolRecipeLoader:
    """Load and validate recipes stored as signed JSON documents."""

    def __init__(
        self,
        *,
        signer: ToolRecipeSigner | None = None,
        require_signature: bool = True,
    ) -> None:
        self._signer = signer
        self._require_signature = require_signature

    def load(self, path: str | Path) -> ToolRecipe:
        target = Path(path)
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, Mapping):
            raise RecipeExecutionError("Recipe file must contain a JSON object")
        signature = data.get("signature")
        document = {k: v for k, v in data.items() if k != "signature"}
        if self._signer:
            if not isinstance(signature, Mapping):
                raise RecipeSignatureError("Signed recipes must include a signature block")
            self._signer.verify(document, signature)
        elif self._require_signature:
            raise RecipeSignatureError("Signature validation is required but no signer was provided")
        recipe = _parse_recipe_document(document)
        recipe.source = target
        recipe.signature = signature if isinstance(signature, Mapping) else None
        return recipe

    def dump(self, recipe: ToolRecipe, path: str | Path, *, key_id: str | None = None) -> None:
        document = recipe.to_document()
        payload = dict(document)
        if self._signer and key_id is not None:
            payload["signature"] = self._signer.sign(document, key_id=key_id)
        elif self._require_signature:
            raise RecipeSignatureError("Signature required but no key identifier provided")
        Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------
async def _execute_step(bus: ToolBus, step: Mapping[str, Any]) -> Mapping[str, Any]:
    mode = str(step.get("mode", "invoke"))
    tool_value = step.get("tool")
    if not tool_value:
        raise RecipeExecutionError("Map step must declare a tool identifier")
    tool = str(tool_value)
    metadata = {
        str(key): str(value)
        for key, value in dict(step.get("metadata", {})).items()
    }
    if mode == "invoke":
        payload = _encode_json(step.get("payload"))
        request = toolbus_pb2.InvokeRequest(
            header=toolbus_pb2.Header(
                request_id=_generate_id(step),
                tool=tool,
                metadata=metadata,
            ),
            payload=payload,
        )
        response = await bus.invoke(request)
        return _normalize_invoke_response(tool, response)
    if mode == "stream":
        payload = _encode_json(step.get("payload"))
        request = toolbus_pb2.StreamRequest(
            header=toolbus_pb2.Header(
                request_id=_generate_id(step),
                tool=tool,
                metadata=metadata,
            ),
            payload=payload,
        )
        chunks: list[Any] = []
        status = toolbus_pb2.StatusCode.STATUS_OK
        error: str | None = None
        async for chunk in bus.stream(request):
            if chunk.end_of_stream:
                status = chunk.status
                error = chunk.error or None
                break
            chunks.append(_decode_payload(chunk.payload))
        return {
            "tool": tool,
            "mode": mode,
            "status": status,
            "error": error,
            "chunks": chunks,
        }
    if mode == "subscribe":
        topics = [str(value) for value in step.get("topics", (tool,))]
        limit = int(step.get("limit", 1))
        request = toolbus_pb2.SubscribeRequest(
            header=toolbus_pb2.Header(
                request_id=_generate_id(step),
                tool=tool,
                metadata=metadata,
            ),
            topics=topics,
        )
        subscription = await bus.subscribe(request)
        events: list[Mapping[str, Any]] = []
        try:
            async for event in subscription:
                events.append(
                    {
                        "topic": event.topic,
                        "metadata": dict(event.metadata),
                        "payload": _decode_payload(event.payload),
                    }
                )
                if len(events) >= limit:
                    break
        finally:
            await subscription.close()
        return {
            "tool": tool,
            "mode": mode,
            "status": toolbus_pb2.StatusCode.STATUS_OK,
            "error": None,
            "events": events,
        }
    raise RecipeExecutionError(f"Unsupported map mode: {mode}")


def _apply_reduce(
    reduce_spec: Mapping[str, Any] | str | None,
    step_results: Sequence[Mapping[str, Any]],
    scope: Mapping[str, Any],
) -> Any:
    if reduce_spec is None:
        return [result.get("payload", result) for result in step_results]
    if isinstance(reduce_spec, str):
        reduce_spec = {"op": reduce_spec}
    op = str(reduce_spec.get("op", "collect"))
    if op == "collect":
        return [result.get("payload", result) for result in step_results]
    if op == "stack":
        return list(step_results)
    if op == "merge":
        merged: dict[str, Any] = {}
        for result in step_results:
            payload = result.get("payload")
            if isinstance(payload, Mapping):
                merged.update(payload)
        return merged
    if op == "first":
        return step_results[0] if step_results else None
    if op == "last":
        return step_results[-1] if step_results else None
    if op == "sum":
        field = reduce_spec.get("field")
        total = 0.0
        for result in step_results:
            value = result
            if field:
                value = _resolve_path(result, str(field))
            if isinstance(value, (int, float)):
                total += float(value)
        return total
    if op == "expr":
        expr = reduce_spec.get("expr")
        expr_scope = dict(scope)
        expr_scope.update({"steps": step_results})
        return _evaluate_expression(expr, expr_scope)
    raise RecipeExecutionError(f"Unsupported reduce operation: {op}")


def _normalize_invoke_response(tool: str, response: toolbus_pb2.InvokeResponse) -> Mapping[str, Any]:
    payload = _decode_payload(response.payload)
    return {
        "tool": tool,
        "mode": "invoke",
        "status": response.status,
        "error": response.error or None,
        "payload": payload,
        "request_id": response.request_id,
    }


def _render_template(template: Any, scope: Mapping[str, Any]) -> Any:
    if isinstance(template, Mapping):
        if "$expr" in template:
            return _evaluate_expression(template["$expr"], scope)
        return {key: _render_template(value, scope) for key, value in template.items()}
    if isinstance(template, (list, tuple)):
        return [_render_template(value, scope) for value in template]
    return template


def _evaluate_expression(expr: Any, scope: Mapping[str, Any]) -> Any:
    if isinstance(expr, (str, int, float, bool)) or expr is None:
        return expr
    if isinstance(expr, Mapping):
        if "var" in expr:
            return _resolve_path(scope, str(expr["var"]))
        if "value" in expr:
            return expr["value"]
        if "not" in expr:
            return not bool(_evaluate_expression(expr["not"], scope))
        if "all" in expr:
            return all(bool(_evaluate_expression(entry, scope)) for entry in expr["all"])
        if "any" in expr:
            return any(bool(_evaluate_expression(entry, scope)) for entry in expr["any"])
        if "eq" in expr:
            left, right = expr["eq"]
            return _evaluate_expression(left, scope) == _evaluate_expression(right, scope)
        if "ne" in expr:
            left, right = expr["ne"]
            return _evaluate_expression(left, scope) != _evaluate_expression(right, scope)
        if "gt" in expr:
            left, right = expr["gt"]
            return _evaluate_expression(left, scope) > _evaluate_expression(right, scope)
        if "lt" in expr:
            left, right = expr["lt"]
            return _evaluate_expression(left, scope) < _evaluate_expression(right, scope)
        if "ge" in expr:
            left, right = expr["ge"]
            return _evaluate_expression(left, scope) >= _evaluate_expression(right, scope)
        if "le" in expr:
            left, right = expr["le"]
            return _evaluate_expression(left, scope) <= _evaluate_expression(right, scope)
        if "contains" in expr:
            collection, member = expr["contains"]
            container = _evaluate_expression(collection, scope)
            needle = _evaluate_expression(member, scope)
            return needle in container if container is not None else False
        if "exists" in expr:
            return _resolve_path(scope, str(expr["exists"])) is not None
        if "len" in expr:
            value = _evaluate_expression(expr["len"], scope)
            return len(value) if value is not None else 0
    if isinstance(expr, Sequence):
        return [_evaluate_expression(entry, scope) for entry in expr]
    raise RecipeExecutionError(f"Unsupported expression type: {type(expr)!r}")


def _resolve_path(data: Any, path: str) -> Any:
    if not path:
        return data
    current = data
    for part in path.split("."):
        if isinstance(current, Mapping):
            current = current.get(part)
        elif isinstance(current, Sequence) and part.isdigit():
            idx = int(part)
            current = current[idx] if 0 <= idx < len(current) else None
        else:
            current = getattr(current, part, None)
        if current is None:
            break
    return current


def _encode_json(payload: Any) -> bytes:
    if payload is None:
        return b""
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def _decode_payload(payload: bytes) -> Any:
    if not payload:
        return None
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            return base64.b64encode(payload).decode("ascii")


def _canonical_bytes(document: Mapping[str, Any]) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _parse_recipe_document(document: Mapping[str, Any]) -> ToolRecipe:
    name = str(document.get("name"))
    version = int(document.get("version", 1))
    metadata = document.get("metadata", {})
    if not isinstance(metadata, Mapping):
        raise RecipeExecutionError("Recipe metadata must be a mapping")
    clauses_raw = document.get("clauses", [])
    if not isinstance(clauses_raw, Iterable):
        raise RecipeExecutionError("Recipe clauses must be a sequence")
    clauses: list[ToolRecipeClause] = []
    for entry in clauses_raw:
        if not isinstance(entry, Mapping):
            raise RecipeExecutionError("Recipe clause must be a mapping")
        map_steps = entry.get("map", [])
        if not isinstance(map_steps, Iterable):
            raise RecipeExecutionError("Clause 'map' must be a sequence")
        normalized_steps: list[Mapping[str, Any]] = []
        for step in map_steps:
            if not isinstance(step, Mapping):
                raise RecipeExecutionError("Each map step must be a mapping")
            normalized_steps.append(dict(step))
        clause = ToolRecipeClause(
            name=str(entry.get("name")) if entry.get("name") is not None else None,
            when=entry.get("when"),
            map_steps=tuple(normalized_steps),
            reduce_spec=entry.get("reduce"),
            guard=entry.get("guard"),
        )
        clauses.append(clause)
    return ToolRecipe(name=name, version=version, clauses=tuple(clauses), metadata=dict(metadata))


def _generate_id(step: Mapping[str, Any]) -> str:
    seed = json.dumps(step, sort_keys=True).encode("utf-8")
    return hashlib.sha1(seed).hexdigest()


__all__ = [
    "GuardViolation",
    "RecipeExecutionError",
    "RecipeSignatureError",
    "ToolRecipe",
    "ToolRecipeClause",
    "ToolRecipeLoader",
    "ToolRecipeSigner",
]
