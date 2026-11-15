"""Waypoint live demo server (stdlib only).

Serves app/demo.html at / and JSON APIs backed by the LIVE HydraDB node:

  GET  /api/tasks     -> the 20 benchmark tasks + ROLES
  POST /api/find_tools {"task_id": "t03", "role": "finance_agent"}
                      -> meta_tools.find_tools run live (role defaults to
                         the task's stated role; override it to demo the
                         permission checkpoint, e.g. t04 as support_agent)
  GET  /api/benchmark -> results/benchmark.json
  GET  /api/learning  -> {"v1": results/learning.json, "v2": results/learning2.json}
  GET  /api/loadtest  -> results/loadtest.json (404 until the load test runs)
  GET  /api/loadtest2 -> results/loadtest2.json (Phase 5, snapshot cache)
  GET  /api/agent_feed -> last 20 external agent calls logged by the MCP
                         server (results/agent-calls.jsonl), newest first
  GET  /api/graph     -> visualization graph pulled LIVE from HydraDB:
                         the 41 core tools + the DataTypes they consume /
                         produce + INPUT_TO/OUTPUT edges + per-tool scopes

Run:  python3 app/server.py            # http://localhost:8077
Requires the HydraDB node on :18443 (bash ~/workspace/hydradb-run/start-node.sh).
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))
from client import run as db_run  # noqa: E402
from meta_tools import find_tools  # noqa: E402
from tasks import TASKS, ROLES  # noqa: E402

HERE = Path(__file__).parent
RESULTS = HERE.parent / "results"
PORT = 8077

TASK_BY_ID = {t["id"]: t for t in TASKS}


def _graph_payload():
    """Visualization graph from the LIVE database (never from tools.json):
    core tools + the DataTypes they consume/produce + typed edges + the
    scopes each core tool requires. Counts come from the DB too."""
    tools = db_run("MATCH (t:Tool) RETURN t.key AS key, t.server AS server, "
                   "t.tokens AS tokens, t.core AS core, t.source AS source")
    inputs = db_run("MATCH (d:DataType)-[:INPUT_TO]->(t:Tool) "
                    "RETURN d.name AS dt, t.key AS tool")
    outputs = db_run("MATCH (t:Tool)-[:OUTPUT]->(d:DataType) "
                     "RETURN t.key AS tool, d.name AS dt")
    scopes = db_run("MATCH (t:Tool)-[:REQUIRES_SCOPE]->(s:Scope) "
                    "RETURN t.key AS tool, s.name AS scope")
    # Phase 7: the console shows the BENCHMARK catalog. Ingested customer
    # tools (source='ingested') are counted separately so the 329-tool
    # benchmark story stays exact after ingestion.
    catalog = [t for t in tools if t["source"] != "ingested"]
    ingested = len(tools) - len(catalog)
    core = {t["key"] for t in catalog if t["core"]}
    scope_of = {}
    for r in scopes:
        if r["tool"] in core:
            scope_of.setdefault(r["tool"], []).append(r["scope"])
    edges = []
    types = set()
    for r in inputs:
        if r["tool"] in core:
            edges.append({"from": f"type:{r['dt']}", "to": f"tool:{r['tool']}",
                          "kind": "in"})
            types.add(r["dt"])
    for r in outputs:
        if r["tool"] in core:
            edges.append({"from": f"tool:{r['tool']}",
                          "to": f"type:{r['dt']}", "kind": "out"})
            types.add(r["dt"])
    return {
        "tools": [{"key": t["key"], "server": t["server"],
                   "tokens": t["tokens"],
                   "scopes": sorted(scope_of.get(t["key"], []))}
                  for t in tools if t["key"] in core],
        "types": sorted(types),
        "edges": edges,
        "counts": {"total_tools": len(catalog), "core_tools": len(core),
                   "distractors": len(catalog) - len(core),
                   "ingested_tools": ingested,
                   "types": len(types), "edges": len(edges)},
    }


def _read_json(name):
    p = RESULTS / name
    if not p.exists():
        return None
    return json.loads(p.read_text())


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep stdout clean
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        self.path = parsed.path  # strip ?query (deep links)
        if self.path == "/":
            # Website first — it introduces the idea; the product (console)
            # lives at /console. Old deep links (/?task=...) still land on
            # the console so existing video links keep working.
            if "task=" in (parsed.query or ""):
                html = (HERE / "demo.html").read_bytes()
            else:
                html = (HERE.parent / "site" / "index.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
        elif self.path == "/console":
            html = (HERE / "demo.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
        elif self.path == "/api/tasks":
            self._send(200, {
                "tasks": [{"id": t["id"], "text": t["text"],
                           "entity": t["entity"], "role": t["role"],
                           "start": t["start"], "goal": t["goal"]}
                          for t in TASKS],
                "roles": sorted(ROLES.keys()),
                "role_scopes": ROLES,
            })
        elif self.path == "/api/graph":
            try:
                self._send(200, _graph_payload())
            except Exception as e:  # noqa: BLE001 - surface verbatim
                self._send(500, {"error": f"{type(e).__name__}: {e}"})
        elif self.path == "/api/benchmark":
            data = _read_json("benchmark.json")
            self._send(200 if data else 404,
                       data or {"error": "benchmark.json not found"})
        elif self.path == "/api/learning":
            v1 = _read_json("learning.json")
            v2 = _read_json("learning2.json")
            self._send(200, {"v1": v1, "v2": v2})
        elif self.path == "/api/loadtest":
            data = _read_json("loadtest.json")
            self._send(200 if data else 404,
                       data or {"error": "loadtest.json not found — "
                                         "run app/loadtest.py first"})
        elif self.path == "/api/loadtest2":
            data = _read_json("loadtest2.json")
            self._send(200 if data else 404,
                       data or {"error": "loadtest2.json not found — "
                                         "run app/loadtest2.py first"})
        elif self.path == "/api/agent_feed":
            # External agent calls, appended by app/mcp_server.py on every
            # tools/call. Newest first; [] until the first agent connects.
            entries = []
            p = RESULTS / "agent-calls.jsonl"
            if p.exists():
                lines = [ln for ln in p.read_text().splitlines()
                         if ln.strip()]
                for ln in lines[-20:]:
                    try:
                        entries.append(json.loads(ln))
                    except json.JSONDecodeError:
                        continue
                entries.reverse()
            self._send(200, entries)
        else:
            self._send(404, {"error": f"no route {self.path}"})

    def do_POST(self):
        if self.path != "/api/find_tools":
            self._send(404, {"error": f"no route {self.path}"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:  # noqa: BLE001
            self._send(400, {"error": f"bad request body: {e}"})
            return
        task = TASK_BY_ID.get(req.get("task_id"))
        if task is None:
            self._send(400, {"error": f"unknown task_id {req.get('task_id')}"})
            return
        role = req.get("role") or task["role"]
        if role not in ROLES:
            self._send(400, {"error": f"unknown role {role}"})
            return
        try:
            res = find_tools(task["start"], task["goal"], role,
                             entity_name=task["entity"])
        except Exception as e:  # noqa: BLE001 - surface verbatim
            self._send(500, {"error": f"{type(e).__name__}: {e}"})
            return
        self._send(200, {
            "task_id": task["id"], "task_text": task["text"],
            "role": role, "stated_role": task["role"],
            "expected_chain": task["chain"],
            **res,
        })


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Waypoint demo on http://localhost:{PORT} "
          f"(HydraDB must be live on :18443)")
    srv.serve_forever()
