"""Seed the Waypoint tool catalog into HydraDB (idempotent).

Graph model:
  Nodes: Tool{id,key,server,tokens,core}   (id from tools.json)
         DataType{name}                    (ids 10000+)
         Scope{name}                       (ids 20000+)
         MCPServer{name}                   (ids 30000+)
         Entity{name,kind,ref,entity_id}   (ids 9000+; entity_id is the
                                             resolved id from tasks.py)
  Edges: (Tool)-[:HOSTED_BY]->(MCPServer)
         (DataType)-[:INPUT_TO]->(Tool)        per consumes type
         (Tool)-[:OUTPUT]->(DataType)          per produces type
         (Tool)-[:REQUIRES]->(Tool)            per requires key
         (Tool)-[:REQUIRES_SCOPE]->(Scope)     per scope
         (Entity)-[:IS_TYPE]->(DataType)       matching entity ref

Seeding follows USING-HYDRADB.md: nodes first via UNWIND...MERGE (MERGE
dedupes on id), then edges via UNWIND...CREATE (dedupes on src/dst/type),
chunks of <=500 rows (batch cap is 1024). Re-running changes nothing.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from client import run  # noqa: E402
from tasks import ENTITIES  # noqa: E402

DATA = Path(__file__).parent.parent / "data" / "tools.json"
CHUNK = 500

DT_BASE, SCOPE_BASE, SERVER_BASE, ENTITY_BASE = 10000, 20000, 30000, 9000


def chunks(rows):
    for i in range(0, len(rows), CHUNK):
        yield rows[i:i + CHUNK]


def seed_nodes(label, rows, set_clause):
    q = f"UNWIND $rows AS row MERGE (n {{id: row.id}}) SET n:{label}, {set_clause}"
    for part in chunks(rows):
        run(q, {"rows": part})


def seed_edges(rel, rows):
    q = (f"UNWIND $rows AS row CREATE (a {{id: row.src}})"
         f"-[:{rel}]->(b {{id: row.dst}})")
    for part in chunks(rows):
        run(q, {"rows": part})


def build_rows(tools):
    by_key = {t["key"]: t for t in tools}
    dtypes = sorted({x for t in tools for x in t["consumes"] + t["produces"]})
    scopes = sorted({s for t in tools for s in t["scopes"]})
    servers = sorted({t["server"] for t in tools})
    dt_id = {name: DT_BASE + i for i, name in enumerate(dtypes)}
    scope_id = {name: SCOPE_BASE + i for i, name in enumerate(scopes)}
    server_id = {name: SERVER_BASE + i for i, name in enumerate(servers)}

    nodes = {
        "Tool": (
            [{"id": t["id"], "key": t["key"], "server": t["server"],
              "tokens": t["tokens"], "core": bool(t["core"])} for t in tools],
            "n.key = row.key, n.server = row.server, "
            "n.tokens = row.tokens, n.core = row.core",
        ),
        "DataType": (
            [{"id": dt_id[n], "name": n} for n in dtypes],
            "n.name = row.name",
        ),
        "Scope": (
            [{"id": scope_id[n], "name": n} for n in scopes],
            "n.name = row.name",
        ),
        "MCPServer": (
            [{"id": server_id[n], "name": n} for n in servers],
            "n.name = row.name",
        ),
        "Entity": (
            [{"id": ENTITY_BASE + i, "name": name, "kind": e["kind"],
              "ref": e["ref"], "entity_id": e["id"]}
             for i, (name, e) in enumerate(ENTITIES.items())],
            "n.name = row.name, n.kind = row.kind, n.ref = row.ref, "
            "n.entity_id = row.entity_id",
        ),
    }

    edges = {
        "HOSTED_BY": [{"src": t["id"], "dst": server_id[t["server"]]}
                      for t in tools],
        "INPUT_TO": [{"src": dt_id[c], "dst": t["id"]}
                     for t in tools for c in t["consumes"]],
        "OUTPUT": [{"src": t["id"], "dst": dt_id[p]}
                   for t in tools for p in t["produces"]],
        "REQUIRES": [{"src": t["id"], "dst": by_key[r]["id"]}
                     for t in tools for r in t["requires"]],
        "REQUIRES_SCOPE": [{"src": t["id"], "dst": scope_id[s]}
                           for t in tools for s in t["scopes"]],
        "IS_TYPE": [{"src": ENTITY_BASE + i, "dst": dt_id[e["ref"]]}
                    for i, e in enumerate(ENTITIES.values())],
    }
    return nodes, edges


def verify(expected_nodes, expected_edges):
    counts = {}
    for label in expected_nodes:
        counts[f"nodes:{label}"] = run(
            f"MATCH (n:{label}) RETURN count(*) AS c")[0]["c"]
    for rel in expected_edges:
        counts[f"edges:{rel}"] = run(
            f"MATCH (a)-[r:{rel}]->(b) RETURN count(*) AS c")[0]["c"]
    ok = True
    for label, (rows, _clause) in expected_nodes.items():
        got = counts[f"nodes:{label}"]
        flag = "OK " if got == len(rows) else "MISMATCH"
        ok &= got == len(rows)
        print(f"[{flag}] nodes {label}: db={got} expected={len(rows)}")
    for rel, rows in expected_edges.items():
        got = counts[f"edges:{rel}"]
        flag = "OK " if got == len(rows) else "MISMATCH"
        ok &= got == len(rows)
        print(f"[{flag}] edges {rel}: db={got} expected={len(rows)}")
    return ok


def main():
    tools = json.loads(DATA.read_text())
    nodes, edges = build_rows(tools)
    for label, (rows, set_clause) in nodes.items():
        seed_nodes(label, rows, set_clause)
        print(f"seeded nodes {label}: {len(rows)}")
    for rel, rows in edges.items():
        seed_edges(rel, rows)
        print(f"seeded edges {rel}: {len(rows)}")
    print("--- verify (queried back from DB) ---")
    ok = verify(nodes, edges)
    print("SEED VERIFY:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
