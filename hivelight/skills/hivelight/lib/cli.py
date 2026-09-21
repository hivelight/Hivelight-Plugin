"""CLI front-end for the Hivelight client.

Lets Claude invoke operations from a shell without import gymnastics:

    python cli.py whoami
    python cli.py matters list
    python cli.py call GET /v1/matters --query name=John
    python cli.py setup

The CLI's purpose is convenience for shell-driven invocation. For richer
workflows (loops, chains, error handling), prefer importing the module:

    from hivelight import HivelightClient
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the local `hivelight` module importable when running from the lib dir
sys.path.insert(0, str(Path(__file__).parent))

from hivelight import (  # noqa: E402
    HivelightClient,
    HivelightError,
)


def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _parse_kv_list(items: list[str]) -> dict:
    """Parse repeated key=value tokens into a dict."""
    out: dict = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"Expected key=value, got: {item}")
        k, v = item.split("=", 1)
        out[k.strip()] = v
    return out


def cmd_setup(args) -> int:
    # Defer import — playwright is heavy
    from setup import run_setup  # type: ignore

    run_setup(sandbox_workspace_label=args.sandbox_workspace)
    return 0


def cmd_whoami(args) -> int:
    c = HivelightClient()
    try:
        # whoami doesn't require a workspace scope
        result = c.internal_call("GET", "/v1/users/whoami", requires_workspace=False)
        _print_json(result)
    except HivelightError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_call(args) -> int:
    c = HivelightClient()
    body = json.loads(args.json) if args.json else None
    path_params = _parse_kv_list(args.path_param)
    query = _parse_kv_list(args.query)
    try:
        result = c.call(
            args.method.upper(),
            args.path,
            public=args.public,
            path_params=path_params or None,
            query=query or None,
            json_body=body,
        )
        _print_json(result)
    except HivelightError as e:
        print(f"Error: {e}", file=sys.stderr)
        if e.body:
            print(f"Body: {json.dumps(e.body, indent=2, default=str)}", file=sys.stderr)
        return 1
    return 0


def cmd_matters(args) -> int:
    c = HivelightClient()
    try:
        if args.action == "list":
            _print_json(c.matters.list())
        elif args.action == "get":
            _print_json(c.matters.get(args.id))
        elif args.action == "create":
            _print_json(
                c.matters.create(
                    name=args.name,
                    owner_user_id=args.owner,
                    types=args.type or None,
                    jurisdictions=args.jurisdiction or None,
                )
            )
        elif args.action == "archive":
            _print_json(c.matters.archive(args.id))
        elif args.action == "delete":
            _print_json(c.matters.delete(args.id))
    except HivelightError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_workflows(args) -> int:
    c = HivelightClient()
    try:
        if args.action == "list":
            _print_json(c.workflows.list(type=args.type))
        elif args.action == "apply":
            _print_json(
                c.workflows.apply(workflow_id=args.workflow, matter_id=args.matter)
            )
        elif args.action == "create":
            _print_json(
                c.workflows.create(name=args.name, type=args.type or "ROADMAP")
            )
        elif args.action == "publish":
            _print_json(c.workflows.publish(args.id, audience=args.audience))
        elif args.action == "unpublish":
            _print_json(c.workflows.unpublish(args.id))
        elif args.action == "delete":
            _print_json(c.workflows.delete(args.id))
        elif args.action == "discard-draft":
            _print_json(c.workflows.discard_draft(args.id))
    except HivelightError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_milestones(args) -> int:
    c = HivelightClient()
    try:
        if args.action == "list":
            _print_json(c.milestones.list(matter_id=args.matter))
        elif args.action == "shift":
            _print_json(
                c.milestones.shift(
                    milestone_id=args.id,
                    matter_id=args.matter,
                    new_due_date=int(args.due_date),
                    new_target_date=int(args.target_date),
                    offset_days=int(args.offset_days),
                    include_following=not args.no_cascade_milestones,
                    shift_tasks=not args.no_cascade_tasks,
                )
            )
    except HivelightError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_tasks(args) -> int:
    c = HivelightClient()
    try:
        if args.action == "list":
            _print_json(
                c.tasks.list(
                    matter_id=args.matter,
                    milestone_id=args.milestone,
                    assignees=args.assignee or None,
                )
            )
        elif args.action == "get":
            _print_json(c.tasks.get(args.id))
        elif args.action == "create":
            _print_json(
                c.tasks.create(
                    name=args.name,
                    matter_id=args.matter,
                    milestone_id=args.milestone,
                )
            )
        elif args.action == "status":
            _print_json(c.tasks.set_status(args.id, status=args.status))
        elif args.action == "delete":
            _print_json(c.tasks.delete(args.id))
    except HivelightError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="hivelight", description="Hivelight skill CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # setup
    p_setup = sub.add_parser("setup", help="First-run browser-assisted auth")
    p_setup.add_argument("--sandbox-workspace")
    p_setup.set_defaults(func=cmd_setup)

    # whoami
    p_whoami = sub.add_parser("whoami", help="Show the authenticated user")
    p_whoami.set_defaults(func=cmd_whoami)

    # generic call
    p_call = sub.add_parser("call", help="Generic API call")
    p_call.add_argument("method")
    p_call.add_argument("path")
    p_call.add_argument("--public", action="store_true", help="Use the public API + x-api-key")
    p_call.add_argument("--json", help="JSON body string")
    p_call.add_argument(
        "--path-param", action="append", metavar="K=V", help="URL template substitution"
    )
    p_call.add_argument("--query", action="append", metavar="K=V", help="Query string param")
    p_call.set_defaults(func=cmd_call)

    # matters
    p_m = sub.add_parser("matters", help="Matter operations")
    p_m_sub = p_m.add_subparsers(dest="action", required=True)
    p_m_sub.add_parser("list").set_defaults(func=cmd_matters)
    p_m_get = p_m_sub.add_parser("get")
    p_m_get.add_argument("id")
    p_m_create = p_m_sub.add_parser("create")
    p_m_create.add_argument("--name", required=True)
    p_m_create.add_argument("--owner", required=True, help="Owner user id")
    p_m_create.add_argument("--type", action="append")
    p_m_create.add_argument("--jurisdiction", action="append")
    p_m_archive = p_m_sub.add_parser("archive"); p_m_archive.add_argument("id")
    p_m_delete = p_m_sub.add_parser("delete"); p_m_delete.add_argument("id")
    for sp in (p_m_get, p_m_create, p_m_archive, p_m_delete):
        sp.set_defaults(func=cmd_matters)

    # workflows
    p_w = sub.add_parser("workflows", help="Workflow operations")
    p_w_sub = p_w.add_subparsers(dest="action", required=True)
    p_w_list = p_w_sub.add_parser("list")
    p_w_list.add_argument("--type", choices=["ROADMAP", "TASK_LIST"])
    p_w_apply = p_w_sub.add_parser("apply")
    p_w_apply.add_argument("--workflow", required=True)
    p_w_apply.add_argument("--matter", required=True)
    p_w_create = p_w_sub.add_parser("create")
    p_w_create.add_argument("--name", required=True)
    p_w_create.add_argument("--type", choices=["ROADMAP", "TASK_LIST"], default="ROADMAP")
    p_w_pub = p_w_sub.add_parser("publish")
    p_w_pub.add_argument("id")
    p_w_pub.add_argument("--audience", choices=["WORKSPACE", "ORGANIZATION", "PUBLIC", "NONE"], default="WORKSPACE")
    p_w_unpub = p_w_sub.add_parser("unpublish"); p_w_unpub.add_argument("id")
    p_w_del = p_w_sub.add_parser("delete"); p_w_del.add_argument("id")
    p_w_dd = p_w_sub.add_parser("discard-draft"); p_w_dd.add_argument("id")
    for sp in (p_w_list, p_w_apply, p_w_create, p_w_pub, p_w_unpub, p_w_del, p_w_dd):
        sp.set_defaults(func=cmd_workflows)

    # milestones
    p_ms = sub.add_parser("milestones", help="Milestone operations")
    p_ms_sub = p_ms.add_subparsers(dest="action", required=True)
    p_ms_list = p_ms_sub.add_parser("list")
    p_ms_list.add_argument("--matter", required=True)
    p_ms_shift = p_ms_sub.add_parser("shift")
    p_ms_shift.add_argument("--id", required=True)
    p_ms_shift.add_argument("--matter", required=True)
    p_ms_shift.add_argument("--due-date", required=True, help="New due date (Unix ms)")
    p_ms_shift.add_argument("--target-date", required=True, help="New target date (Unix ms)")
    p_ms_shift.add_argument("--offset-days", required=True, help="Days to shift subsequent milestones")
    p_ms_shift.add_argument("--no-cascade-milestones", action="store_true")
    p_ms_shift.add_argument("--no-cascade-tasks", action="store_true")
    for sp in (p_ms_list, p_ms_shift):
        sp.set_defaults(func=cmd_milestones)

    # tasks
    p_t = sub.add_parser("tasks", help="Task operations")
    p_t_sub = p_t.add_subparsers(dest="action", required=True)
    p_t_list = p_t_sub.add_parser("list")
    p_t_list.add_argument("--matter")
    p_t_list.add_argument("--milestone")
    p_t_list.add_argument("--assignee", action="append")
    p_t_get = p_t_sub.add_parser("get"); p_t_get.add_argument("id")
    p_t_create = p_t_sub.add_parser("create")
    p_t_create.add_argument("--name", required=True)
    p_t_create.add_argument("--matter", required=True)
    p_t_create.add_argument("--milestone", required=True)
    p_t_status = p_t_sub.add_parser("status")
    p_t_status.add_argument("id")
    p_t_status.add_argument("--status", choices=["TODO", "INPROGRESS", "INREVIEW", "DONE"], required=True)
    p_t_del = p_t_sub.add_parser("delete"); p_t_del.add_argument("id")
    for sp in (p_t_list, p_t_get, p_t_create, p_t_status, p_t_del):
        sp.set_defaults(func=cmd_tasks)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
