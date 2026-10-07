#!/usr/bin/env python3

"""
A script to refresh or regenerate the tokens of Configured Worker Pools.

Refreshing keeps a token's secret and sets its expiry afresh (removing it,
without '--ttl-hours'); regenerating issues a new secret, which the Agents
still using the old one can no longer register with. Either is confirmed
first, saying what the expiry will be. Each target -- a Worker Pool's ID,
its name, or a glob pattern matching names -- is resolved, in the order
given, to a Configured Worker Pool, recording any that cannot be acted on as
'failed' (not found, not a Configured Worker Pool) or 'skipped' (already
shut down). What remains is acted on one pool at a time, the new token
printed and recorded. The rules for what cannot be acted on, confirming and
stopping on a session failure are action_runner.py's.
"""

from datetime import timedelta
from typing import cast

from yellowdog_client.model import (
    ConfiguredWorkerPool,
    WorkerPool,
    WorkerPoolSummary,
    WorkerPoolToken,
)

from yellowdog_cli.utils.action_runner import (
    Item,
    Unit,
    Unresolved,
    carry_out,
    confirm_items,
    resolve_targets,
)
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import ET_WORKER_POOLS, RN_CONFIGURED_POOL
from yellowdog_cli.utils.entity_utils import (
    describe_glob_scope,
    expand_name_globs,
    get_worker_pool_by_id,
    get_worker_pool_id_by_name,
    get_worker_pool_summaries,
)
from yellowdog_cli.utils.glob_utils import contains_glob_chars
from yellowdog_cli.utils.misc_utils import is_http_not_found, shown_expiry
from yellowdog_cli.utils.printing import (
    print_dry_run,
    print_info,
    print_quiet_result,
)
from yellowdog_cli.utils.results import record_action
from yellowdog_cli.utils.wrapper import main_wrapper
from yellowdog_cli.utils.ydid_utils import YDIDType, get_ydid_type

# The '--json' records' actions and outcomes
_REFRESH = "refresh"
_REFRESHED = "refreshed"
_REGENERATE = "regenerate"
_REGENERATED = "regenerated"


def _action(ctx: RunContext) -> str:
    return _REGENERATE if ctx.args.regenerate else _REFRESH


def _recorder(ctx: RunContext):
    """
    The Record action_runner calls, naming this run's action.
    """

    def record(
        entity: object, entity_type: str, outcome: str, error: str | None
    ) -> None:
        record_action(entity, entity_type, _action(ctx), outcome, error)

    return record


@main_wrapper
def main(ctx: RunContext):
    act_on_tokens(ctx, ctx.args.worker_pools)


def act_on_tokens(ctx: RunContext, targets: list[str]):
    """
    Refresh, or with '--regenerate' regenerate, the tokens of the Configured
    Worker Pools named, or matching the glob patterns given.
    """
    record = _recorder(ctx)
    items = resolve_targets(
        _expand_globs(ctx, targets),
        resolve=lambda target: _resolve(ctx, target),
        describe=lambda target: (target, ET_WORKER_POOLS),
        record=record,
        verb=f"{_action(ctx)} the token of",
        order=lambda items: items,
    )

    if not items:
        print_info(f"No Worker Pool tokens {_past_tense(ctx)}")
        return

    if ctx.args.dry_run:
        for item in items:
            print_dry_run(
                f"Would {_action(ctx)} the token of Configured Worker Pool"
                f" {_label(item.value)}"
            )
            record(item.entity, item.entity_type, f"would {_action(ctx)}", None)
        return

    if not confirm_items(_confirmation(ctx, items), items, record):
        print_info(f"No Worker Pool tokens {_past_tense(ctx)}")
        return

    carry_out(
        [
            Unit(
                items=[item],
                act=lambda item=item: _act(ctx, item.value),
                failure=lambda e, item=item: (
                    f"Unable to {_action(ctx)} the token of Configured Worker Pool"
                    f" {_label(item.value)}: {e}"
                ),
            )
            for item in items
        ],
        record,
    )


def _past_tense(ctx: RunContext) -> str:
    return _REGENERATED if ctx.args.regenerate else _REFRESHED


def _expand_globs(ctx: RunContext, targets: list[str]) -> list[str]:
    """
    The targets, each glob pattern replaced by the IDs of the Configured
    Worker Pools it matches that are not yet shut down: a pattern says which
    pools it means, so the others it matches are left out rather than failed.
    """
    expanded: list[str] = []
    for target in targets:
        if not contains_glob_chars(target):
            expanded.append(target)
            continue
        print_info(
            "Finding Configured Worker Pools"
            f" {describe_glob_scope([target], ctx.config.namespace)}"
        )
        summaries: list[WorkerPoolSummary] = expand_name_globs(
            [target],
            ctx.config.namespace,
            fetch=lambda namespace, prefix: get_worker_pool_summaries(
                ctx.client, namespace, prefix or None, partial_name_matches=True
            ),
        )
        matched = [
            cast(str, summary.id)
            for summary in summaries
            if _is_configured_type(summary.type)
            and not (summary.status is not None and summary.status.finished)
        ]
        if not matched:
            print_info(f"No active Configured Worker Pools match '{target}'")
        expanded.extend(matched)
    return expanded


def _is_configured_type(type_name: str | None) -> bool:
    return (type_name or "").split(".")[-1] == RN_CONFIGURED_POOL


def _resolve(ctx: RunContext, target: str) -> Item:
    """
    The Configured Worker Pool a target names, raising Unresolved if its
    token cannot be acted on. Anything else raised is a failure of the
    lookup itself.
    """
    if get_ydid_type(target) == YDIDType.WORKER_POOL:
        worker_pool_id: str | None = target
    else:
        worker_pool_id = get_worker_pool_id_by_name(
            ctx.client, target, ctx.config.namespace
        )
        if worker_pool_id is None:
            raise Unresolved(f"Cannot find Worker Pool '{target}'")
    try:
        worker_pool: WorkerPool = get_worker_pool_by_id(
            ctx.client, cast(str, worker_pool_id)
        )
    except Exception as e:
        if is_http_not_found(e):
            raise Unresolved(f"Cannot find Worker Pool {worker_pool_id}") from e
        raise
    if not isinstance(worker_pool, ConfiguredWorkerPool):
        raise Unresolved(
            f"Worker Pool {_label(worker_pool)} is not a Configured Worker Pool,"
            " so has no token",
            entity=worker_pool,
        )
    if worker_pool.status is not None and worker_pool.status.finished:
        raise Unresolved(
            f"Configured Worker Pool {_label(worker_pool)} is already"
            f" {worker_pool.status}",
            "skipped",
            worker_pool,
        )
    return Item(worker_pool, ET_WORKER_POOLS, worker_pool.id, worker_pool)


def _label(worker_pool: WorkerPool) -> str:
    if worker_pool.name:
        return f"'{worker_pool.namespace}/{worker_pool.name}' ({worker_pool.id})"
    return cast(str, worker_pool.id)


def _confirmation(ctx: RunContext, items: list[Item]) -> str:
    pools = ", ".join(_label(item.value) for item in items)
    hours = ctx.args.ttl_hours
    expiry = "never to expire" if hours is None else f"to expire in {hours:,d} hour(s)"
    if ctx.args.regenerate:
        return (
            f"Regenerate the tokens of {len(items)} Configured Worker Pool(s)"
            f" ({pools}), invalidating their current tokens, the new ones {expiry}?"
        )
    return (
        f"Refresh the tokens of {len(items)} Configured Worker Pool(s) ({pools}),"
        f" setting them {expiry}?"
    )


def _act(ctx: RunContext, worker_pool: ConfiguredWorkerPool):
    """
    Refresh or regenerate one pool's token; print and record the new one.
    """
    pools = ctx.client.worker_pool_client
    method = (
        pools.regenerate_configured_worker_pool_token_by_id
        if ctx.args.regenerate
        else pools.refresh_configured_worker_pool_token_by_id
    )
    token: WorkerPoolToken = method(cast(str, worker_pool.id), _token_ttl(ctx))
    expiry = None if token.expiryTime is None else token.expiryTime.isoformat()
    print_info(
        f"{_past_tense(ctx).capitalize()} the token of Configured Worker Pool"
        f" {_label(worker_pool)}"
    )
    print_info(f"                   Worker Pool Token = '{token.secret}'")
    print_info(
        f"                   Worker Pool Expiry Time = {shown_expiry(token.expiryTime)}"
    )
    # The token too, which '--json' otherwise silences with the prints above
    record_action(
        worker_pool,
        ET_WORKER_POOLS,
        _action(ctx),
        _past_tense(ctx),
        token=token.secret,
        expiryTime=expiry,
    )
    print_quiet_result(token.secret)


def _token_ttl(ctx: RunContext) -> timedelta | None:
    """
    The time to live '--ttl-hours' gives, counted from now. Without it the
    Platform gives the token no expiry at all, rather than a default one.
    """
    hours = ctx.args.ttl_hours
    return None if hours is None else timedelta(hours=hours)


# Entry point
if __name__ == "__main__":
    main()
