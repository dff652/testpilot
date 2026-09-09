"""CLI for explicit local registration and evidence-backed runs."""
import argparse
import json
from pathlib import Path
import sys

from .registry import load_checkout, register
from .runner.service import cancel_run, read_result, recover, run, supervise
from .storage import PilotError, read_json


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "_supervise":
        internal = argparse.ArgumentParser(prog="testpilot supervisor")
        internal.add_argument("--job", type=Path, required=True)
        internal.add_argument("--lock-fd", type=int, required=True)
        args = internal.parse_args(sys.argv[2:])
        try:
            return supervise(args.job, args.lock_fd)
        except (PilotError, OSError, KeyError, TypeError, ValueError):
            print("supervisor failed before final result persistence", file=sys.stderr)
            return 2
    parser = argparse.ArgumentParser(prog="testpilot")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("register", "run", "status", "cancel", "recover"):
        command = commands.add_parser(name)
        command.add_argument("--registry", type=Path, required=True)
        command.add_argument("--checkout-id", required=True)
        if name == "register":
            command.add_argument("--project-id", required=True)
            command.add_argument("--checkout", type=Path, required=True)
            source = command.add_mutually_exclusive_group(required=True)
            source.add_argument("--action", type=Path)
            source.add_argument("--adapter", choices=["agent-mail"])
            command.add_argument("--tool", action="append", default=[], metavar="NAME=ABSOLUTE_PATH")
            command.add_argument("--replace", action="store_true")
        if name == "run":
            command.add_argument("--action-id", required=True)
            command.add_argument("--run-id")
        if name in {"status", "cancel"}:
            command.add_argument("--run-id", required=True)
            command.add_argument("--attempt-id", required=True)
    args = parser.parse_args()
    try:
        if args.command == "register":
            tools = {}
            for item in args.tool:
                name, separator, path = item.partition("=")
                if not separator or not name or not path or name in tools:
                    raise PilotError("tool.invalid_assignment")
                tools[name] = path
            if args.adapter:
                from .adapters.agent_mail import build_action
                try:
                    action = build_action(args.checkout)
                except ValueError:
                    raise PilotError("adapter.invalid_native_action") from None
            else:
                action = read_json(args.action)
            output = register(args.registry, args.checkout_id, args.project_id, args.checkout,
                              action, tools, replace=args.replace)
        elif args.command == "run":
            output = run(args.registry, args.checkout_id, args.action_id, run_id=args.run_id)
        elif args.command == "status":
            output = read_result(load_checkout(args.registry, args.checkout_id), args.run_id, args.attempt_id)
        elif args.command == "cancel":
            output = cancel_run(args.registry, args.checkout_id, args.run_id, args.attempt_id)
        else:
            output = recover(args.registry, args.checkout_id)
    except PilotError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=True))
        return 2
    except (OSError, KeyError, TypeError, ValueError):
        print(json.dumps({"error": "input.invalid_or_unavailable"}))
        return 2
    print(json.dumps(output, ensure_ascii=True, sort_keys=True))
    if args.command == "run":
        return {"passed": 0, "blocked": 2, "timed_out": 124, "cancelled": 130}.get(output["status"], 1)
    if args.command == "recover" and output["status"] in {"blocked", "busy"}:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
