#!/usr/bin/env python3
"""Generate the static demo dataset for the no-auth MediaClaw demo site.

The dataset is a projection of the accepted Media Web Business Pages contract:
every payload is instantiated from the OpenAPI response schema and then merged
with the hand written business seed, so demo content can never drift away from
the shapes the production pages parse. Nothing here talks to a backend; the
output is consumed by `src/demo/demoBackend.ts` inside the browser.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = ROOT.parent
DEFAULT_CONTRACT = ROOT / "contracts/media_web_business_pages.openapi.yaml"
DEFAULT_TARGET = ROOT / "src/demo/generatedDemoDataset.json"
DEFAULT_CATALOG_TARGET = ROOT / "src/demo/generatedDemoCatalog.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from demo_seed import (  # noqa: E402  (seed lives next to this generator)
    BACKEND_OWNED_OPERATIONS,
    DEMO_NOW,
    LIST_SIZES,
    PARAMETER_PAYLOADS,
    SEED,
    WORD_POOLS,
)

TIMESTAMP_BASE = datetime.fromisoformat(DEMO_NOW)


class DatasetError(RuntimeError):
    pass


def stable_index(pointer: str, modulo: int) -> int:
    digest = hashlib.sha256(pointer.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % max(modulo, 1)


def pointer_field(pointer: str) -> str:
    for part in reversed(pointer.split(".")):
        if part and not part.isdigit() and not part.startswith("["):
            return part.split("[")[0]
    return pointer


def timestamp(pointer: str, *, span_hours: int = 720) -> str:
    offset = stable_index(pointer, span_hours)
    return (TIMESTAMP_BASE - timedelta(hours=offset, minutes=stable_index(pointer + "m", 60))).isoformat()


def identifier(pointer: str, pattern: str) -> str:
    field = pointer_field(pointer)
    prefix = re.sub(r"^public", "", field)
    prefix = re.sub(r"(Id|Ids)$", "", prefix)
    prefix = re.sub(r"(?<!^)(?=[A-Z])", "_", prefix).lower() or "demo"
    value = f"demo_{prefix}_{stable_index(pointer, 9000) + 1000}"
    if pattern and not re.match(pattern, value):
        value = f"demo{stable_index(pointer, 900000) + 100000}"
    return value


class Sampler:
    """Instantiates a JSON value for an OpenAPI schema node."""

    def __init__(self, schemas: dict[str, Any]) -> None:
        self.schemas = schemas

    def resolve(self, schema: dict[str, Any]) -> dict[str, Any]:
        if "$ref" in schema:
            name = schema["$ref"].split("/")[-1]
            resolved = self.schemas.get(name)
            if resolved is None:
                raise DatasetError(f"unknown schema reference: {name}")
            return self.resolve(resolved)
        return schema

    def sample(self, schema: dict[str, Any], pointer: str, override: Any = None) -> Any:
        schema = self.resolve(schema)
        if "allOf" in schema:
            merged: dict[str, Any] = {"type": "object", "properties": {}, "required": []}
            for part in schema["allOf"]:
                resolved = self.resolve(part)
                merged["properties"].update(resolved.get("properties", {}))
                merged["required"].extend(resolved.get("required", []))
            schema = merged
        for key in ("oneOf", "anyOf"):
            if key in schema:
                return self.sample(self.choose_branch(schema[key], override), pointer, override)

        declared = schema.get("type")
        types = declared if isinstance(declared, list) else [declared] if declared else []
        nullable = "null" in types
        concrete = [item for item in types if item != "null"]
        # 可空字段没有种子时一律给 null：演示站不编造头像、链接这类会真的发起请求的值。
        if override is None and nullable:
            return None
        kind = concrete[0] if concrete else self.infer_kind(schema, override)

        if kind == "object":
            return self.sample_object(schema, pointer, override)
        if kind == "array":
            return self.sample_array(schema, pointer, override)
        if override is not None:
            return override
        if kind == "boolean":
            return stable_index(pointer, 4) != 0
        if kind in {"integer", "number"}:
            return self.sample_number(schema, pointer, kind)
        return self.sample_string(schema, pointer, nullable)

    def choose_branch(self, branches: list[dict[str, Any]], override: Any) -> dict[str, Any]:
        """Union branches are discriminated by a literal field (block type, receipt kind)."""
        if isinstance(override, dict):
            for discriminator in ("type", "kind"):
                supplied = override.get(discriminator)
                if supplied is None:
                    continue
                for branch in branches:
                    resolved = self.resolve(branch)
                    declared = self.resolve(resolved.get("properties", {}).get(discriminator, {}))
                    allowed = declared.get("enum", [])
                    if declared.get("const") is not None:
                        allowed = [declared["const"]]
                    if supplied in allowed:
                        return branch
            for branch in branches:
                resolved = self.resolve(branch)
                declared = set(resolved.get("properties", {}))
                if declared and set(override) <= declared:
                    return branch
        return branches[0]

    def infer_kind(self, schema: dict[str, Any], override: Any) -> str:
        if "properties" in schema or "additionalProperties" in schema:
            return "object"
        if "items" in schema:
            return "array"
        if isinstance(override, dict):
            return "object"
        if isinstance(override, list):
            return "array"
        return "string"

    def sample_object(self, schema: dict[str, Any], pointer: str, override: Any) -> dict[str, Any]:
        if override is not None and not isinstance(override, dict):
            raise DatasetError(f"{pointer}: object override must be a mapping")
        properties = schema.get("properties")
        if not properties:
            # Free form map (StringValueMap and friends): the seed owns the content.
            return dict(override or {})
        required = set(schema.get("required", []))
        result: dict[str, Any] = {}
        for name, child in properties.items():
            child_override = (override or {}).get(name, None)
            optional = name not in required
            if optional and child_override is None and not self.keep_optional(child):
                continue
            result[name] = self.sample(child, f"{pointer}.{name}", child_override)
        unknown = set(override or {}) - set(properties)
        if unknown:
            raise DatasetError(f"{pointer}: seed declares fields outside the contract: {sorted(unknown)}")
        return result

    def keep_optional(self, child: dict[str, Any]) -> bool:
        resolved = self.resolve(child)
        declared = resolved.get("type")
        types = declared if isinstance(declared, list) else [declared]
        return "null" not in types

    def sample_array(self, schema: dict[str, Any], pointer: str, override: Any) -> list[Any]:
        items = schema.get("items", {"type": "string"})
        if override is not None:
            if not isinstance(override, list):
                raise DatasetError(f"{pointer}: array override must be a list")
            return [self.sample(items, f"{pointer}[{index}]", value) for index, value in enumerate(override)]
        # 没有种子的列表默认给 3 条，避免演示站出现整页空态。
        size = LIST_SIZES.get(pointer, max(schema.get("minItems", 0), 3))
        return [self.sample(items, f"{pointer}[{index}]") for index in range(size)]

    def sample_number(self, schema: dict[str, Any], pointer: str, kind: str) -> Any:
        minimum = schema.get("minimum", 0)
        maximum = schema.get("maximum", minimum + 40)
        span = max(int(maximum - minimum), 1)
        value = minimum + stable_index(pointer, span + 1)
        return int(value) if kind == "integer" else round(float(value), 2)

    def sample_string(self, schema: dict[str, Any], pointer: str, nullable: bool) -> Any:
        if "enum" in schema:
            choices = [item for item in schema["enum"] if item is not None]
            if not choices:
                return None
            return choices[stable_index(pointer, len(choices))]
        fmt = schema.get("format")
        if fmt == "date-time":
            return timestamp(pointer)
        if fmt == "uri":
            return f"https://demo.mediaclaw.example/{pointer_field(pointer)}/{stable_index(pointer, 9000) + 1000}"
        pattern = schema.get("pattern", "")
        if pattern:
            hex_digest = hashlib.sha256(pointer.encode("utf-8")).hexdigest()
            candidates = [
                "sha256:" + hex_digest,
                hex_digest,
                f"{stable_index(pointer, 4000) / 100:.2f}",
                "blk_" + hex_digest[:16],
                identifier(pointer, pattern),
            ]
            for candidate in candidates:
                if re.match(pattern, candidate):
                    return candidate
            raise DatasetError(f"{pointer}: cannot fabricate a value for /{pattern}/")
        field = pointer_field(pointer)
        pool = WORD_POOLS.get(field)
        if pool:
            return pool[stable_index(pointer, len(pool))]
        if nullable:
            return None
        return WORD_POOLS["_fallback"][stable_index(pointer, len(WORD_POOLS["_fallback"]))]


class Validator:
    """Rejects any payload the production pages could not parse."""

    def __init__(self, schemas: dict[str, Any]) -> None:
        self.schemas = schemas
        self.sampler = Sampler(schemas)

    def check(self, schema: dict[str, Any], value: Any, pointer: str) -> None:
        schema = self.sampler.resolve(schema)
        if "allOf" in schema:
            for part in schema["allOf"]:
                self.check(part, value, pointer)
            return
        for key in ("oneOf", "anyOf"):
            if key in schema:
                errors = []
                for index, part in enumerate(schema[key]):
                    try:
                        self.check(part, value, pointer)
                        return
                    except DatasetError as error:
                        errors.append(f"[{index}] {error}")
                raise DatasetError(f"{pointer}: no {key} branch matched ({'; '.join(errors)})")
        declared = schema.get("type")
        types = declared if isinstance(declared, list) else [declared] if declared else []
        if value is None:
            if types and "null" not in types:
                raise DatasetError(f"{pointer}: null is not allowed")
            return
        if "enum" in schema and value not in schema["enum"]:
            raise DatasetError(f"{pointer}: {value!r} is outside {schema['enum']}")
        concrete = [item for item in types if item != "null"]
        kind = concrete[0] if concrete else self.sampler.infer_kind(schema, value)
        if kind == "object":
            self.check_object(schema, value, pointer)
        elif kind == "array":
            self.check_array(schema, value, pointer)
        elif kind == "string":
            self.check_string(schema, value, pointer)
        elif kind in {"integer", "number"}:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise DatasetError(f"{pointer}: expected {kind}, found {type(value).__name__}")
            if kind == "integer" and not isinstance(value, int):
                raise DatasetError(f"{pointer}: expected integer, found {value!r}")
        elif kind == "boolean" and not isinstance(value, bool):
            raise DatasetError(f"{pointer}: expected boolean, found {value!r}")

    def check_object(self, schema: dict[str, Any], value: Any, pointer: str) -> None:
        if not isinstance(value, dict):
            raise DatasetError(f"{pointer}: expected object, found {type(value).__name__}")
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                raise DatasetError(f"{pointer}: missing required field {name}")
        additional = schema.get("additionalProperties", True)
        for name, child in value.items():
            if name in properties:
                self.check(properties[name], child, f"{pointer}.{name}")
                continue
            if additional is False:
                raise DatasetError(f"{pointer}: field {name} is not declared by the contract")
            if isinstance(additional, dict):
                self.check(additional, child, f"{pointer}.{name}")

    def check_array(self, schema: dict[str, Any], value: Any, pointer: str) -> None:
        if not isinstance(value, list):
            raise DatasetError(f"{pointer}: expected array, found {type(value).__name__}")
        items = schema.get("items")
        if items is None:
            return
        for index, child in enumerate(value):
            self.check(items, child, f"{pointer}[{index}]")

    def check_string(self, schema: dict[str, Any], value: Any, pointer: str) -> None:
        if not isinstance(value, str):
            raise DatasetError(f"{pointer}: expected string, found {type(value).__name__}")
        pattern = schema.get("pattern")
        if pattern and not re.match(pattern, value):
            raise DatasetError(f"{pointer}: {value!r} does not match /{pattern}/")
        if schema.get("format") == "date-time":
            try:
                datetime.fromisoformat(value)
            except ValueError as error:
                raise DatasetError(f"{pointer}: {value!r} is not a timestamp") from error


def load_contract(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    return yaml.safe_load(raw), hashlib.sha256(raw).hexdigest()


def response_schema(operation: dict[str, Any]) -> dict[str, Any] | None:
    responses = operation.get("responses", {})
    for status in ("200", "201", 200, 201):
        entry = responses.get(status)
        if not entry:
            continue
        content = entry.get("content", {}).get("application/json")
        if content and "schema" in content:
            return content["schema"]
    return None


def collect_operations(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    methods = {"get", "post", "put", "delete", "patch"}
    collected: dict[str, dict[str, Any]] = {}
    for path, item in document.get("paths", {}).items():
        for method, operation in item.items():
            if method not in methods:
                continue
            operation_id = operation.get("operationId")
            if not operation_id:
                raise DatasetError(f"{method.upper()} {path} has no operationId")
            collected[operation_id] = {
                "method": method.upper(),
                "path": path,
                "schema": response_schema(operation),
                "parameters": re.findall(r"\{([^{}]+)\}", path),
            }
    return collected


def build_dataset(document: dict[str, Any], digest: str) -> dict[str, Any]:
    schemas = document["components"]["schemas"]
    sampler = Sampler(schemas)
    validator = Validator(schemas)
    operations = collect_operations(document)

    unknown_seed = set(SEED) - set(operations)
    if unknown_seed:
        raise DatasetError(f"seed declares unknown operations: {sorted(unknown_seed)}")

    payloads: dict[str, Any] = {}
    for operation_id, operation in sorted(operations.items()):
        if operation_id in BACKEND_OWNED_OPERATIONS:
            continue
        schema = operation["schema"]
        if schema is None:
            continue
        entry: dict[str, Any] = {
            "method": operation["method"],
            "path": operation["path"],
        }
        default = align_revisions(sampler.sample(schema, operation_id, SEED.get(operation_id)))
        validator.check(schema, default, operation_id)
        entry["payload"] = default
        keyed = PARAMETER_PAYLOADS.get(operation_id)
        if keyed:
            parameter = operation["parameters"][-1] if operation["parameters"] else None
            if parameter is None:
                raise DatasetError(f"{operation_id}: keyed payloads need a path parameter")
            entry["parameter"] = parameter
            entry["payloads"] = {}
            for key, override in keyed.items():
                merged = merge(SEED.get(operation_id), override)
                payload = align_revisions(sampler.sample(schema, f"{operation_id}.{key}", merged))
                validator.check(schema, payload, f"{operation_id}[{key}]")
                entry["payloads"][key] = payload
        payloads[operation_id] = entry

    return {
        "schemaVersion": "media_web_business_pages_v2",
        "generatedFrom": "contracts/media_web_business_pages.openapi.yaml",
        "contractSha256": digest,
        "generatedAt": DEMO_NOW,
        "operations": payloads,
    }


def align_revisions(payload: Any) -> Any:
    """页面普遍要求顶层 revision 与内嵌对象的 revision 相同，生成的骨架必须对齐。"""
    if not isinstance(payload, dict) or "revision" not in payload:
        return payload
    for key, value in payload.items():
        if key == "revision" or not isinstance(value, dict):
            continue
        nested = value.get("revision")
        if isinstance(nested, int) and not isinstance(nested, bool):
            payload["revision"] = nested
            break
    return payload


def merge(base: Any, override: Any) -> Any:
    if base is None:
        return override
    if override is None:
        return base
    if isinstance(base, dict) and isinstance(override, dict):
        result = dict(base)
        for key, value in override.items():
            result[key] = merge(result.get(key), value)
        return result
    return override


def build_catalog() -> dict[str, Any]:
    """Compile the real capability catalog so the task drawer keeps production behaviour."""
    sys.path[:0] = [str(REPOSITORY_ROOT), str(REPOSITORY_ROOT / "openclaw-tag-router")]
    from openclaw_app.services.capability_registry import CapabilityRegistry  # noqa: E402

    registry = CapabilityRegistry.compile_all()
    return registry.serialize(
        visibilities=frozenset({"public", "ops"}),
        bots=frozenset({"Media bot", "任意 Bot"}),
    )


def render(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--catalog-target", type=Path, default=DEFAULT_CATALOG_TARGET)
    parser.add_argument("--check", action="store_true", help="fail when the committed files are stale")
    arguments = parser.parse_args()

    document, digest = load_contract(arguments.contract)
    dataset = render(build_dataset(document, digest))
    catalog = render(build_catalog())

    if arguments.check:
        stale = [
            path
            for path, expected in ((arguments.target, dataset), (arguments.catalog_target, catalog))
            if not path.exists() or path.read_text(encoding="utf-8") != expected
        ]
        if stale:
            print("demo dataset is stale: " + ", ".join(str(path) for path in stale), file=sys.stderr)
            return 1
        print("demo dataset matches the contract and seed")
        return 0

    arguments.target.parent.mkdir(parents=True, exist_ok=True)
    arguments.target.write_text(dataset, encoding="utf-8")
    arguments.catalog_target.write_text(catalog, encoding="utf-8")
    print(f"wrote {arguments.target.relative_to(ROOT)} and {arguments.catalog_target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
