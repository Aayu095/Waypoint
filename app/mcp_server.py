"""Waypoint as an MCP server — the buyable form of the product.

    python3 app/mcp_server.py        # stdio, newline-delimited JSON-RPC 2.0

Any MCP client (Claude Code, Cursor, a custom agent) connects and gets
THREE tools instead of every tool definition in the customer's catalog:

  find_tools(start_type, goal_type, role, entity_name?)
      -> the exact, permission-checked tool chain for a task, resolved
         live from the HydraDB graph (meta_tools.find_tools)
  resolve_entity(name)
      -> an entity the agent already resolved, with its ref type
  report_outcome(chain, success)
      -> writes the outcome back, reweighting CO_USED_WITH edges

Stdlib only. stdout carries JSON-RPC and nothing else; all logging goes
to stderr. State lives in HydraDB (HTTP :18443) via meta_tools.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from meta_tools import find_tools, resolve_entity, report_outcome  # noqa: E402

# Every external tools/call is appended here as one JSON line; the demo
# server's /api/agent_feed serves it to the console's LIVE AGENT FEED, so
# a real agent's calls are visible in the product, not just in a terminal.
CALL_LOG = Path(__file__).parent.parent / "results" / "agent-calls.jsonl"


def _args_summary(name, args):
    if name == "find_tools":
        return {"start_type": args.get("start_type"),
                "goal_type": args.get("goal_type"),
                "role": args.get("role"),
                "entity_name": args.get("entity_name")}
    if name == "resolve_entity":
        return {"name": args.get("name")}
    if name == "report_outcome":
        return {"chain": list(args.get("chain") or []),
                "success": bool(args.get("success"))}
    return {}


def _result_summary(name, args, out, error=None):
    if error is not None:
        return {"error": error}
    if name == "find_tools":
        s = {"refused": bool(out.get("refused")),
             "chain": out.get("chain"),
             "tokens": out.get("tokens_loaded")}
        if out.get("refused"):
            s["blocked_tool"] = out.get("blocked_tool")
            s["missing_scope"] = out.get("missing_scope")
        if out.get("error"):
            s["error"] = out["error"]
        return s
    if name == "resolve_entity":
        if out is None:
            return {"resolved": None}
        return {"resolved": out.get("name"), "kind": out.get("kind"),
                "ref": out.get("ref")}
    if name == "report_outcome":
        return {"success": bool(args.get("success")),
                "edges": out.get("edges")}
    return {}


def _log_call(name, args, out, error=None):
    """Append one compact JSON line per external tools/call. Best-effort
    by design: any failure here is swallowed — logging must never break
    the MCP server or change a tool response."""
    try:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "tool": name,
            "args": _args_summary(name, args),
            "result": _result_summary(name, args, out, error),
        }
        CALL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with CALL_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:  # noqa: BLE001 - logging is never load-bearing
        pass

SERVER_INFO = {"name": "waypoint", "version": "0.1.0"}
DEFAULT_PROTOCOL = "2024-11-05"

TOOLS = [
    {
        "name": "find_tools",
        "description": (
            "Find the exact tool chain for a task. Give the data type the "
            "agent starts with and the data type the task must produce; "
            "Waypoint traverses the tool graph in HydraDB and returns "
            "only the tools needed, in order, with the tokens they cost. "
            "Traversal is permission-aware: if a chain tool requires a "
            "scope the role does not hold, the call is REFUSED, naming "
            "the blocked tool and the missing scope."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_type": {"type": "string",
                               "description": "Data type the agent starts with, e.g. CompanyName."},
                "goal_type": {"type": "string",
                              "description": "Data type the task must produce, e.g. SentMail."},
                "role": {"type": "string",
                         "description": "Calling role; its scopes gate the traversal."},
                "entity_name": {"type": "string",
                                "description": "Optional entity the task mentions (e.g. 'Acme Corp'); resolved in the graph and used to fill input gaps."},
            },
            "required": ["start_type", "goal_type", "role"],
        },
    },
    {
        "name": "resolve_entity",
        "description": (
            "Return an entity that was already resolved in the graph "
            "(name, id, kind, and the data type it provides), so the "
            "agent can skip a repeat lookup."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "Entity name, e.g. 'Acme Corp'."},
            },
            "required": ["name"],
        },
    },
    {
        "name": "report_outcome",
        "description": (
            "Report whether executing a chain succeeded. Writes the "
            "outcome back into the graph, reweighting the CO_USED_WITH "
            "edges between consecutive chain tools (+1 success, cap +10; "
            "-1 failure, floor -5), so routing improves with use."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "chain": {"type": "array", "items": {"type": "string"},
                          "description": "The executed tool chain, in order."},
                "success": {"type": "boolean",
                            "description": "True if the chain achieved the task."},
            },
            "required": ["chain", "success"],
        },
    },
]


def _call_tool(name, args):
    if name == "find_tools":
        return find_tools(args["start_type"], args["goal_type"],
                          args["role"], entity_name=args.get("entity_name"))
    if name == "resolve_entity":
        return resolve_entity(args["name"])
    if name == "report_outcome":
        return report_outcome(list(args["chain"]), bool(args["success"]))
    raise KeyError(f"unknown tool {name}")


def _result(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid,
            "error": {"code": code, "message": message}}


def handle(msg):
    """One parsed JSON-RPC message -> response dict, or None for
    notifications (which never get a response)."""
    method = msg.get("method")
    rid = msg.get("id")
    if method is None:
        return None
    if method.startswith("notifications/"):
        return None
    if rid is None:
        return None  # a notification by shape, whatever its name
    params = msg.get("params") or {}
    if method == "initialize":
        return _result(rid, {
            "protocolVersion": params.get("protocolVersion",
                                          DEFAULT_PROTOCOL),
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
    if method == "ping":
        return _result(rid, {})
    if method == "tools/list":
        return _result(rid, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name not in {t["name"] for t in TOOLS}:
            return _error(rid, -32602, f"unknown tool {name}")
        try:
            out = _call_tool(name, args)
        except Exception as e:  # noqa: BLE001 - tool errors are results
            _log_call(name, args, None,
                      error=f"{type(e).__name__}: {e}")
            return _result(rid, {
                "content": [{"type": "text",
                             "text": f"{type(e).__name__}: {e}"}],
                "isError": True,
            })
        _log_call(name, args, out)
        return _result(rid, {
            "content": [{"type": "text", "text": json.dumps(out)}],
            "isError": False,
        })
    return _error(rid, -32601, f"method not found: {method}")


def main():
    print("waypoint mcp server on stdio", file=sys.stderr)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            resp = _error(None, -32700, f"parse error: {e}")
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
            continue
        try:
            resp = handle(msg)
        except Exception as e:  # noqa: BLE001 - never die on one message
            resp = _error(msg.get("id"), -32603,
                          f"internal error: {type(e).__name__}: {e}")
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
