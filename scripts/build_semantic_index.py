"""Audit graph scopes and explicitly build, publish or retire semantic candidates."""

import argparse
import asyncio
import json
import math
import sys
import time
from pathlib import Path
from typing import Literal

# Direct script execution must use the same package imports as python -m.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from gustobot.domain.linking import BuildIndexRequest
from gustobot.infrastructure.persistence.crud.semantic_index import BuildLeaseConflict


def create_service():
    from gustobot.application.services.knowledge_runtime import (
        create_semantic_indexing_service,
    )

    return create_semantic_indexing_service()


async def close_resources():
    from gustobot.application.services.knowledge_runtime import cleanup_runtime

    await cleanup_runtime()


def _kinds(kind: str) -> tuple[Literal["concept", "entity"], ...]:
    choices: dict[str, tuple[Literal["concept", "entity"], ...]] = {
        "concept": ("concept",),
        "entity": ("entity",),
        "all": ("concept", "entity"),
    }
    return choices[kind]


async def watch(
    service,
    *,
    kinds=("concept", "entity"),
    batch_size=64,
    poll_seconds=5,
    quiet_seconds=5,
    clock=time.monotonic,
    sleep=asyncio.sleep,
):
    """A scope lease is acquired by the ordinary builder after a stable revision window."""
    observed: dict[str, tuple[tuple[str, int | None], float]] = {}
    retry_after: dict[tuple[str, int | None], float] = {}
    while True:
        for selected_kind in kinds:
            scope = service.scope(selected_kind)
            status = await service.status(scope)
            if status.status in {"ready", "uninitialized"}:
                observed.pop(scope.key, None)
                continue
            revision = None
            if selected_kind == "entity":
                current = await service.graph_revision()
                if current.state != "ready":
                    continue
                revision = current.revision
            signature = (scope.key, revision)
            now = clock()
            if scope.key not in observed or observed[scope.key][0] != signature:
                observed[scope.key] = (signature, now)
            if now - observed[scope.key][1] < quiet_seconds or now < retry_after.get(signature, 0):
                continue
            try:
                receipt = await service.build(
                    BuildIndexRequest(
                        scope=scope,
                        batch_size=batch_size,
                        publish=True,
                        expected_active_generation=status.generation_id,
                    )
                )
                print(receipt.model_dump_json(), flush=True)
                if receipt.status in {"failed", "superseded"}:
                    retry_after[signature] = now + max(30, poll_seconds, quiet_seconds)
                else:
                    observed.pop(scope.key, None)
            except BuildLeaseConflict:
                retry_after[signature] = now + max(poll_seconds, quiet_seconds)
        await sleep(poll_seconds)


async def execute(args) -> int:
    try:
        service = create_service()
        if args.command == "bootstrap":
            report = await service.bootstrap(audit_only=not args.apply_scope)
            print(report.model_dump_json(), flush=True)
            return 1 if report.invalid or report.unknown_version or report.errors else 0
        if args.command == "retire":
            await service.retire(args.generation)
            print(json.dumps({"generation_id": args.generation, "status": "retired"}), flush=True)
            return 0
        if args.command == "calibrate":
            publication = await service.calibrate(
                args.generation,
                args.report,
                expected_active_generation=args.expected_active_generation,
            )
            print(publication.model_dump_json(), flush=True)
            return 0
        if args.command == "watch":
            await watch(
                service,
                kinds=_kinds(args.kind),
                batch_size=args.batch_size,
                poll_seconds=args.poll_seconds,
                quiet_seconds=args.quiet_seconds,
            )
            return 0
        failed = False
        for selected_kind in _kinds(args.kind):
            scope = service.scope(selected_kind)
            status = await service.status(scope)
            if args.command == "status":
                print(status.model_dump_json(), flush=True)
                continue
            receipt = await service.build(
                BuildIndexRequest(
                    scope=scope,
                    batch_size=args.batch_size,
                    publish=args.publish,
                    expected_active_generation=status.generation_id,
                )
            )
            print(receipt.model_dump_json(), flush=True)
            failed |= receipt.status in {"failed", "superseded"}
        return 1 if failed else 0
    except Exception as error:  # noqa: BLE001 - Report failure without provider secrets.
        print(
            f"Semantic index command failed ({type(error).__name__})", file=sys.stderr, flush=True
        )
        return 1
    finally:
        await close_resources()


def _batch_size(value):
    parsed = int(value)
    if not 1 <= parsed <= 1000:
        raise argparse.ArgumentTypeError("batch size must be between 1 and 1000")
    return parsed


def _seconds(value):
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("seconds must be finite and positive")
    return parsed


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    bootstrap = commands.add_parser(
        "bootstrap", help="Audit the current graph before establishing its scope"
    )
    mode = bootstrap.add_mutually_exclusive_group()
    mode.add_argument("--audit", action="store_true", help="Read-only audit (the default)")
    mode.add_argument(
        "--apply-scope",
        action="store_true",
        help="Establish scope after a successful complete audit",
    )
    build = commands.add_parser(
        "build", help="Build an unpublished generation unless --publish is explicit"
    )
    build.add_argument("--kind", choices=("concept", "entity", "all"), default="all")
    build.add_argument("--batch-size", type=_batch_size, default=64)
    build.add_argument("--publish", action="store_true")
    status = commands.add_parser("status", help="Read the current publication and graph revision")
    status.add_argument("--kind", choices=("concept", "entity", "all"), default="all")
    worker = commands.add_parser(
        "watch", help="Publish candidates after a stable graph revision window"
    )
    worker.add_argument("--kind", choices=("concept", "entity", "all"), default="all")
    worker.add_argument("--batch-size", type=_batch_size, default=64)
    worker.add_argument("--poll-seconds", type=_seconds, default=5)
    worker.add_argument("--quiet-seconds", type=_seconds, default=5)
    retire = commands.add_parser(
        "retire", help="Retire and delete a generation protected against active pointers"
    )
    retire.add_argument("--generation", required=True)
    calibrate = commands.add_parser(
        "calibrate", help="Attach a validated real-provider report to the exact active generation"
    )
    calibrate.add_argument("--generation", required=True)
    calibrate.add_argument("--report", type=Path, required=True)
    calibrate.add_argument("--expected-active-generation")
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        return asyncio.run(execute(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
