"""Tiny HTTP client for the local HydraDB node.

Talks to the standalone server (HTTP 18443, namespace `local`, graph
`default`, cell `cell-0`). The auth token is read from
~/workspace/hydradb-run/token.txt at runtime and never printed or stored
anywhere else.

Response envelope (verified in Phase 1): rows are lists of typed cells
{"type": ..., "value": ...}; a null cell has NO "value" key. run() unwraps
cells to plain Python values and returns a list of dicts keyed by column.
"""

import json
import urllib.request
import urllib.error
from pathlib import Path

URL = "http://localhost:18443/v1/graphs/default/query"
TOKEN_PATH = Path.home() / "workspace" / "hydradb-run" / "token.txt"
NAMESPACE = "local"
CELL_ID = "cell-0"


class CypherError(Exception):
    """Raised when the server rejects a query; carries the raw response."""

    def __init__(self, status, body):
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body[:500]}")


def _token():
    return TOKEN_PATH.read_text().strip()


def _cell_value(cell):
    if not isinstance(cell, dict):
        return cell
    if "value" not in cell:  # null cell: no value key at all
        return None
    return cell["value"]


def run(cypher, parameters=None):
    """Execute one Cypher statement; return rows as list[dict]."""
    payload = {"cell_id": CELL_ID, "query": cypher}
    if parameters is not None:
        payload["parameters"] = parameters
    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {_token()}",
            "X-Graph-Namespace": NAMESPACE,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise CypherError(e.code, e.read().decode(errors="replace")) from None
    columns = body.get("columns", [])
    rows = []
    for raw in body.get("rows", []):
        row = {}
        for i, col in enumerate(columns):
            row[col] = _cell_value(raw[i]) if i < len(raw) else None
        rows.append(row)
    return rows


def run_raw(cypher, parameters=None):
    """Like run() but returns the untouched response body (for path results
    and mutation envelopes where columns may be empty)."""
    payload = {"cell_id": CELL_ID, "query": cypher}
    if parameters is not None:
        payload["parameters"] = parameters
    req = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {_token()}",
            "X-Graph-Namespace": NAMESPACE,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise CypherError(e.code, e.read().decode(errors="replace")) from None


if __name__ == "__main__":
    # NOTE: count(n) is rejected by this dialect; count(*) works.
    print(run("MATCH (n:Tool) RETURN count(*) AS c"))
