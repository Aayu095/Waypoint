"""Waypoint ingestion CLI — the product's front door.

    python3 app/ingest.py <file-or-dir> [--server NAME]

Ingests MCP tool definitions into the LIVE HydraDB graph so any customer's
own tool catalog becomes routable by find_tools — no hand-built catalog
required. Input is MCP tools/list-shaped JSON: a list of
{name, description, inputSchema, outputSchema?, scopes?} (or an object
with a "tools" list). A directory means every *.json inside; the server
name defaults to each file's stem unless --server overrides it.

Type derivation from JSON Schema (deterministic):
  input property  -> $ref tail | array -> element type + "List" |
                     inline object -> property name | format -> format
                     name | scalar -> String/Integer/Number/Boolean
  tool output     -> outputSchema title | $ref | single-property object
                     -> that property's type | otherwise <Tool>Output

Graph writes mirror seed.py exactly (nodes: UNWIND + MERGE on id + SET;
edges: UNWIND + CREATE, which this DB dedupes on src/dst/type), so
ingestion is IDEMPOTENT: re-running adds zero nodes and zero edges.
Ingested tools are marked Tool.source = 'ingested' and core = True (they
are chain-bearing, so find_tools routes through them; the synthetic
benchmark catalog carries no source property and stays distinguishable —
its type vocabulary is disjoint from real catalogs, verified by the
Phase 7 regression run). Node ids for ingested data live in high bands
(Tool 100000+, DataType 200000+, Scope 300000+, MCPServer 400000+) so
they can never collide with the seeded catalog's ids.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from client import run  # noqa: E402
from catalog import est_tokens  # noqa: E402

CHUNK = 500
TOOL_BASE, DT_BASE, SCOPE_BASE, SERVER_BASE = 100000, 200000, 300000, 400000

_SCALARS = {"string": "String", "integer": "Integer",
            "number": "Number", "boolean": "Boolean"}


def camel(name):
    parts = re.split(r"[^0-9A-Za-z]+", str(name))
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def derive_type(prop_name, schema):
    """Named DataType for one input property's JSON Schema (or None)."""
    if not isinstance(schema, dict):
        return None
    if "$ref" in schema:
        return camel(schema["$ref"].split("/")[-1])
    t = schema.get("type")
    if t == "array":
        inner = derive_type(prop_name, schema.get("items") or {})
        if inner:
            return inner + "List"
        return (camel(prop_name) + "List") if prop_name else None
    if t == "object":
        return camel(prop_name) if prop_name else None
    if schema.get("format"):
        return camel(schema["format"])
    return _SCALARS.get(t)


def derive_output(tool_name, schema):
    """The single DataType a tool produces, from its outputSchema."""
    fallback = camel(tool_name) + "Output"
    if not isinstance(schema, dict):
        return fallback
    if schema.get("title"):
        return camel(schema["title"])
    if "$ref" in schema:
        return camel(schema["$ref"].split("/")[-1])
    t = schema.get("type")
    if t == "array":
        items = schema.get("items") or {}
        if "$ref" in items:
            return camel(items["$ref"].split("/")[-1]) + "List"
        return fallback
    if t == "object":
        props = schema.get("properties") or {}
        if len(props) == 1:
            (pn, ps), = props.items()
            return derive_type(pn, ps) or fallback
        return fallback
    if schema.get("format"):
        return camel(schema["format"])
    return fallback


def tool_spec(server, raw):
    """Normalise one tools/list entry into a graph-ready spec."""
    name = raw["name"]
    desc = raw.get("description") or f"Tool {name} on the {server} server."
    ins = (raw.get("inputSchema") or {}).get("properties") or {}
    consumes = []
    for prop, schema in ins.items():
        dt = derive_type(prop, schema)
        if dt and dt not in consumes:
            consumes.append(dt)
    produces = [derive_output(name, raw.get("outputSchema"))]
    scopes = raw.get("scopes") or [f"{server}:use"]
    return {"key": name, "server": server, "desc": desc,
            "tokens": est_tokens(desc), "consumes": consumes,
            "produces": produces, "scopes": list(scopes)}


def load_specs(path, server_override=None):
    """Read a file or directory of tools/list JSON -> [(server, raw)]."""
    path = Path(path)
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    if not files:
        raise SystemExit(f"no .json files under {path}")
    out = []
    for f in files:
        data = json.loads(f.read_text())
        if isinstance(data, dict) and "tools" not in data:
            continue  # not a tools/list file (e.g. a tasks.json beside it)
        tools = data["tools"] if isinstance(data, dict) else data
        server = server_override or f.stem
        for raw in tools:
            out.append((server, raw))
    return out


class Allocator:
    """Natural-key -> node id, allocating fresh ids above a band base."""

    def __init__(self, existing, base):
        self.map = dict(existing)
        self.next = max([base] + [v + 1 for v in existing.values()])

    def get(self, key):
        if key not in self.map:
            self.map[key] = self.next
            self.next += 1
        return self.map[key]


def _chunks(rows):
    for i in range(0, len(rows), CHUNK):
        yield rows[i:i + CHUNK]


def _merge_nodes(label, rows, set_clause):
    if not rows:
        return
    q = (f"UNWIND $rows AS row MERGE (n {{id: row.id}}) "
         f"SET n:{label}, {set_clause}")
    for part in _chunks(rows):
        run(q, {"rows": part})


def _create_edges(rel, rows):
    if not rows:
        return
    q = (f"UNWIND $rows AS row CREATE (a {{id: row.src}})"
         f"-[:{rel}]->(b {{id: row.dst}})")
    for part in _chunks(rows):
        run(q, {"rows": part})


def graph_counts():
    counts = {}
    for label in ("Tool", "DataType", "Scope", "MCPServer", "Entity"):
        counts[f"nodes:{label}"] = run(
            f"MATCH (n:{label}) RETURN count(*) AS c")[0]["c"]
    for rel in ("HOSTED_BY", "INPUT_TO", "OUTPUT", "REQUIRES",
                "REQUIRES_SCOPE", "IS_TYPE", "CO_USED_WITH"):
        counts[f"edges:{rel}"] = run(
            f"MATCH (a)-[r:{rel}]->(b) RETURN count(*) AS c")[0]["c"]
    counts["ingested_tools"] = run(
        "MATCH (t:Tool) WHERE t.source = 'ingested' "
        "RETURN count(*) AS c")[0]["c"]
    return counts


def ingest(raw_specs):
    """Ingest [(server, raw-tool)] into the live graph. Returns a summary
    dict; safe to re-run (zero new nodes/edges on repeat)."""
    specs = [tool_spec(server, raw) for server, raw in raw_specs]

    existing_tools = run("MATCH (t:Tool) RETURN t.key AS key, "
                         "t.server AS server, t.id AS id")
    tool_ids = Allocator({(r["server"], r["key"]): r["id"]
                          for r in existing_tools}, TOOL_BASE)
    known_keys = {r["key"]: r["server"] for r in existing_tools}
    before_pairs = set(tool_ids.map)

    dt_ids = Allocator({r["name"]: r["id"] for r in run(
        "MATCH (d:DataType) RETURN d.name AS name, d.id AS id")}, DT_BASE)
    scope_ids = Allocator({r["name"]: r["id"] for r in run(
        "MATCH (s:Scope) RETURN s.name AS name, s.id AS id")}, SCOPE_BASE)
    server_ids = Allocator({r["name"]: r["id"] for r in run(
        "MATCH (s:MCPServer) RETURN s.name AS name, s.id AS id")},
        SERVER_BASE)

    # resolve tool keys (collision with another server's tool -> prefix)
    for spec in specs:
        key, server = spec["key"], spec["server"]
        if key in known_keys and known_keys[key] != server:
            key = f"{server}__{spec['key']}"
            spec["key"] = key
        known_keys.setdefault(key, server)
        spec["id"] = tool_ids.get((server, key))

    servers = sorted({s["server"] for s in specs})
    scopes = sorted({sc for s in specs for sc in s["scopes"]})
    dtypes = sorted({dt for s in specs for dt in s["consumes"] + s["produces"]})

    _merge_nodes("MCPServer",
                 [{"id": server_ids.get(n), "name": n} for n in servers],
                 "n.name = row.name")
    _merge_nodes("Scope",
                 [{"id": scope_ids.get(n), "name": n} for n in scopes],
                 "n.name = row.name")
    _merge_nodes("DataType",
                 [{"id": dt_ids.get(n), "name": n} for n in dtypes],
                 "n.name = row.name")
    _merge_nodes("Tool",
                 [{"id": s["id"], "key": s["key"], "server": s["server"],
                   "tokens": s["tokens"], "core": True,
                   "source": "ingested"} for s in specs],
                 "n.key = row.key, n.server = row.server, "
                 "n.tokens = row.tokens, n.core = row.core, "
                 "n.source = row.source")

    _create_edges("HOSTED_BY",
                  [{"src": s["id"], "dst": server_ids.get(s["server"])}
                   for s in specs])
    _create_edges("INPUT_TO",
                  [{"src": dt_ids.get(dt), "dst": s["id"]}
                   for s in specs for dt in s["consumes"]])
    _create_edges("OUTPUT",
                  [{"src": s["id"], "dst": dt_ids.get(dt)}
                   for s in specs for dt in s["produces"]])
    _create_edges("REQUIRES_SCOPE",
                  [{"src": s["id"], "dst": scope_ids.get(sc)}
                   for s in specs for sc in s["scopes"]])

    per_server = {}
    for s in specs:
        entry = per_server.setdefault(s["server"], {"tools": 0, "new": 0})
        entry["tools"] += 1
        entry["new"] += (s["server"], s["key"]) not in before_pairs
    return {"per_server": per_server, "tools": len(specs),
            "new_tools": sum(e["new"] for e in per_server.values()),
            "datatypes": len(dtypes), "scopes": len(scopes),
            "servers": servers}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", help="tools/list JSON file or directory of them")
    ap.add_argument("--server", default=None,
                    help="server name (default: file stem)")
    args = ap.parse_args(argv)

    before = graph_counts()
    summary = ingest(load_specs(args.path, args.server))
    after = graph_counts()
    for server, e in sorted(summary["per_server"].items()):
        print(f"server {server}: {e['tools']} tools ({e['new']} new)")
    print(f"tools: {before['nodes:Tool']} -> {after['nodes:Tool']} "
          f"(ingested total: {after['ingested_tools']})")
    print(f"datatypes: {before['nodes:DataType']} -> "
          f"{after['nodes:DataType']}; scopes: {before['nodes:Scope']} -> "
          f"{after['nodes:Scope']}; servers: {before['nodes:MCPServer']} "
          f"-> {after['nodes:MCPServer']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
