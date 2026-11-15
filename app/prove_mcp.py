"""Phase 7 proof driver for app/mcp_server.py.

Spawns the Waypoint MCP server over stdio and speaks newline-delimited
JSON-RPC 2.0 to it: initialize, notifications/initialized, tools/list,
then tools/call for find_tools (the t03 benchmark shape: CompanyName ->
SentMail as finance_agent, entity 'Acme Corp'), resolve_entity
('Acme Corp'), find_tools again in the t04 shape as support_agent
(the permission checkpoint must REFUSE at void_invoice), and
report_outcome on the returned chain. The full transcript — every line
sent and received — is written verbatim to
results/mcp-server-proof.txt, and the key results are asserted. Every
tools/call is also appended by the server to results/agent-calls.jsonl
(the console's LIVE AGENT FEED source).

Run:  python3 app/prove_mcp.py
"""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
TRANSCRIPT = HERE.parent / "results" / "mcp-server-proof.txt"

proc = subprocess.Popen(
    [sys.executable, str(HERE / "mcp_server.py")],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
    stderr=subprocess.PIPE, text=True, bufsize=1,
)

lines = []
_id = 0


def _log(direction, text):
    lines.append(f"{direction} {text}")


def send(msg):
    text = json.dumps(msg)
    _log(">>>", text)
    proc.stdin.write(text + "\n")
    proc.stdin.flush()


def call(method, params):
    global _id
    _id += 1
    send({"jsonrpc": "2.0", "id": _id, "method": method, "params": params})
    while True:
        line = proc.stdout.readline()
        if not line:
            err = proc.stderr.read() if proc.stderr else ""
            raise SystemExit(f"server closed stdout waiting for {method}. "
                             f"stderr tail:\n{err[-2000:]}")
        _log("<<<", line.strip())
        msg = json.loads(line)
        if msg.get("id") == _id:
            if "error" in msg:
                raise SystemExit(f"{method} JSON-RPC error: "
                                 f"{json.dumps(msg['error'])[:500]}")
            return msg["result"]


def tool_call(name, arguments):
    res = call("tools/call", {"name": name, "arguments": arguments})
    if res.get("isError"):
        raise SystemExit(f"tools/call {name} isError: "
                         f"{json.dumps(res)[:800]}")
    return json.loads(res["content"][0]["text"])


def main():
    init = call("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "waypoint-prove-mcp", "version": "0.1"},
    })
    print("initialize ok:", init.get("serverInfo"))
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    listed = call("tools/list", {})
    names = [t["name"] for t in listed["tools"]]
    print("tools/list:", names)
    assert names == ["find_tools", "resolve_entity", "report_outcome"]

    found = tool_call("find_tools", {
        "start_type": "CompanyName", "goal_type": "SentMail",
        "role": "finance_agent", "entity_name": "Acme Corp",
    })
    print("find_tools chain:", found.get("chain"),
          "tokens:", found.get("tokens_loaded"),
          "method:", found.get("method"))
    expected = ["lookup_customer", "list_invoices", "get_invoice",
                "invoice_pdf", "find_contact", "send_email"]
    assert found.get("chain") == expected, found
    assert found.get("refused") is False

    ent = tool_call("resolve_entity", {"name": "Acme Corp"})
    print("resolve_entity:", ent)
    assert ent and ent["ref"] == "CustomerRef", ent

    refused = tool_call("find_tools", {
        "start_type": "CompanyName", "goal_type": "VoidedInvoice",
        "role": "support_agent", "entity_name": "Sharma Traders",
    })
    print("find_tools t04 as support_agent refused:",
          refused.get("blocked_tool"), "/", refused.get("missing_scope"))
    assert refused.get("refused") is True, refused
    assert refused.get("blocked_tool") == "void_invoice", refused
    assert refused.get("missing_scope") == "payments:admin", refused

    rep = tool_call("report_outcome",
                    {"chain": found["chain"], "success": True})
    print("report_outcome:", rep)
    assert rep["edges"] == len(expected) - 1, rep

    proc.stdin.close()
    proc.terminate()
    lines.append("")
    lines.append("ASSERTIONS: initialize ok; tools/list = "
                 "[find_tools, resolve_entity, report_outcome]; "
                 "find_tools chain == t03 ground truth "
                 f"{expected}; resolve_entity('Acme Corp') ref == "
                 "CustomerRef; t04 as support_agent REFUSED at "
                 "void_invoice (missing payments:admin); "
                 "report_outcome edges == 5. ALL PASS.")
    TRANSCRIPT.write_text("\n".join(lines) + "\n")
    print(f"wrote {TRANSCRIPT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
