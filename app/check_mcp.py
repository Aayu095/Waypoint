"""Full judge-path check for app/mcp_server.py (Phase 15).

Drives the MCP server EXACTLY as a stranger would from the README's
documented config — `python3 app/mcp_server.py` over stdio, from the
repo root — and asserts the whole surface:

  * initialize handshake (serverInfo, protocol version)
  * tools/list: exactly the 3 meta-tools, each WITH an input schema
  * find_tools t03 shape  -> exact 6-tool chain, 494 tokens
  * find_tools t04 shape  -> REFUSED at void_invoice / payments:admin
  * find_tools on the ingested filesystem catalog (FilePath ->
    WriteFileOutput, fs_agent) -> [read_file, write_file]
  * resolve_entity 'Acme Corp' -> CustomerRef
  * report_outcome success -> CO_USED_WITH weights rise by 1
  * report_outcome failure -> weights fall back by 1
  * PROTOCOL PURITY: every line the server writes to stdout parses as
    JSON-RPC 2.0 (a single stray print corrupts MCP — pass/fail gate)
  * results/agent-calls.jsonl gained one entry per tools/call

Run against a live node (./run.sh first):
    python3 app/check_mcp.py
Exits 0 only if every check passes.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "app"))
from client import run as db_run  # noqa: E402

CALL_LOG = ROOT / "results" / "agent-calls.jsonl"
T03_CHAIN = ["lookup_customer", "list_invoices", "get_invoice",
             "invoice_pdf", "find_contact", "send_email"]

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}"
          + (f" — {detail}" if detail else ""))


def log_lines():
    if not CALL_LOG.exists():
        return 0
    return sum(1 for _ in CALL_LOG.open(encoding="utf-8"))


def edge_weight(a, b):
    rows = db_run(
        "MATCH (x:Tool {key: $a})-[r:CO_USED_WITH]->(y:Tool {key: $b}) "
        "RETURN r.weight AS w", {"a": a, "b": b})
    if not rows or rows[0]["w"] is None:
        return 0
    return rows[0]["w"]


def main():
    log_before = log_lines()
    base_w = {(a, b): edge_weight(a, b)
              for a, b in zip(T03_CHAIN, T03_CHAIN[1:])}

    proc = subprocess.Popen(
        ["python3", "app/mcp_server.py"], cwd=ROOT,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, bufsize=1,
    )
    raw_lines = []
    _id = 0

    def send(msg):
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    def call(method, params):
        nonlocal _id
        _id += 1
        send({"jsonrpc": "2.0", "id": _id, "method": method,
              "params": params})
        while True:
            line = proc.stdout.readline()
            if not line:
                err = proc.stderr.read() if proc.stderr else ""
                raise SystemExit(f"server closed stdout on {method}; "
                                 f"stderr tail:\n{err[-1500:]}")
            raw_lines.append(line)
            msg = json.loads(line)  # purity asserted below for ALL lines
            if msg.get("id") == _id:
                if "error" in msg:
                    raise SystemExit(f"{method} error: {msg['error']}")
                return msg["result"]

    def tool_call(name, arguments):
        res = call("tools/call", {"name": name, "arguments": arguments})
        assert not res.get("isError"), f"{name} isError: {res}"
        return json.loads(res["content"][0]["text"])

    try:
        init = call("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "waypoint-check-mcp", "version": "0.1"},
        })
        check("initialize handshake",
              init.get("serverInfo", {}).get("name") == "waypoint"
              and init.get("protocolVersion") == "2024-11-05",
              f"serverInfo={init.get('serverInfo')}")
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        listed = call("tools/list", {})
        tools = listed["tools"]
        names = [t["name"] for t in tools]
        check("tools/list = exactly the 3 meta-tools",
              names == ["find_tools", "resolve_entity", "report_outcome"],
              f"{names}")
        check("every tool carries an inputSchema with properties+required",
              all(t.get("inputSchema", {}).get("type") == "object"
                  and t["inputSchema"].get("properties")
                  and t["inputSchema"].get("required") for t in tools))

        found = tool_call("find_tools", {
            "start_type": "CompanyName", "goal_type": "SentMail",
            "role": "finance_agent", "entity_name": "Acme Corp"})
        check("find_tools t03 -> exact 6-tool chain, 494 tok",
              found.get("chain") == T03_CHAIN
              and found.get("tokens_loaded") == 494
              and found.get("refused") is False,
              f"chain={found.get('chain')} tok={found.get('tokens_loaded')}")

        refused = tool_call("find_tools", {
            "start_type": "CompanyName", "goal_type": "VoidedInvoice",
            "role": "support_agent", "entity_name": "Sharma Traders"})
        check("find_tools t04 as support_agent -> REFUSED "
              "void_invoice / payments:admin",
              refused.get("refused") is True
              and refused.get("blocked_tool") == "void_invoice"
              and refused.get("missing_scope") == "payments:admin",
              f"blocked={refused.get('blocked_tool')}")

        fs = tool_call("find_tools", {
            "start_type": "FilePath", "goal_type": "WriteFileOutput",
            "role": "fs_agent"})
        check("find_tools filesystem copy task -> [read_file, write_file]",
              fs.get("chain") == ["read_file", "write_file"]
              and fs.get("refused") is False,
              f"chain={fs.get('chain')} tok={fs.get('tokens_loaded')}")

        ent = tool_call("resolve_entity", {"name": "Acme Corp"})
        check("resolve_entity 'Acme Corp' -> CustomerRef",
              bool(ent) and ent.get("ref") == "CustomerRef",
              f"{ent}")

        rep_ok = tool_call("report_outcome",
                           {"chain": T03_CHAIN, "success": True})
        want_up = {f"{a}->{b}": min(10, base_w[(a, b)] + 1)
                   for a, b in zip(T03_CHAIN, T03_CHAIN[1:])}
        check("report_outcome success -> 5 edges, weights +1",
              rep_ok.get("edges") == 5
              and rep_ok.get("weights") == want_up,
              f"weights={rep_ok.get('weights')}")

        rep_no = tool_call("report_outcome",
                           {"chain": T03_CHAIN, "success": False})
        want_dn = {k: max(-5, v - 1) for k, v in want_up.items()}
        check("report_outcome failure -> weights -1 per the rules",
              rep_no.get("edges") == 5
              and rep_no.get("weights") == want_dn,
              f"weights={rep_no.get('weights')}")
        check("DB cross-check: lookup_customer->list_invoices weight "
              "matches the tool result",
              edge_weight("lookup_customer", "list_invoices")
              == want_dn["lookup_customer->list_invoices"])
    finally:
        try:
            proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        proc.terminate()

    pure = True
    for line in raw_lines:
        try:
            m = json.loads(line)
            assert m.get("jsonrpc") == "2.0"
        except Exception:  # noqa: BLE001
            pure = False
    check(f"protocol purity: all {len(raw_lines)} stdout lines are "
          "valid JSON-RPC 2.0", pure and len(raw_lines) >= 8)

    gained = log_lines() - log_before
    check("agent-calls.jsonl gained one entry per tools/call (6)",
          gained >= 6, f"gained={gained}")

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILED:", "; ".join(failed))
        return 1
    print("MCP JUDGE-PATH: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
