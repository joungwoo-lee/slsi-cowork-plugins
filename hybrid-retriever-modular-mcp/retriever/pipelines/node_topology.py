"""Node-centric topology adapter.

Haystack's serialised pipeline format separates component definitions from
connections (``{"components": {...}, "connections": [...]}``), which is faithful
to the runtime graph but awkward to read or visualise — to see what a node is
wired to you must scan a parallel ``connections`` list.

The node-centric format groups each component's module, params, and wiring in
one place:

    {
      "nodes": [
        {
          "name": "reranker",
          "module": "retriever.components.bge_reranker.BgeReranker",
          "params": {"model": "BAAI/bge-reranker-v2-m3"},
          "inputs":  [{"port": "documents", "from": "joiner.documents"}],
          "outputs": [{"port": "documents", "to":   "parent.documents"}]
        }
      ]
    }

A connection can be declared on either side (``inputs`` of the receiver OR
``outputs`` of the sender); duplicates are merged. ``to_haystack_dict`` produces
the standard ``{components, connections}`` dict the haystack ``Pipeline`` loader
accepts.
"""
from __future__ import annotations

from typing import Any


def is_node_centric(raw: dict[str, Any]) -> bool:
    """Return True if ``raw`` uses the node-centric schema."""
    return isinstance(raw, dict) and isinstance(raw.get("nodes"), list)


def to_haystack_dict(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert a node-centric topology dict into the haystack standard dict.

    Raises ``ValueError`` if the input is malformed (missing names, duplicate
    node names, or port references like ``foo.bar`` that don't match
    ``<name>.<port>``).
    """
    if not is_node_centric(raw):
        raise ValueError("topology is not node-centric (missing 'nodes' list)")

    components: dict[str, dict[str, Any]] = {}
    connections_set: set[tuple[str, str]] = set()
    ordered_connections: list[dict[str, str]] = []

    def _add_connection(sender: str, receiver: str) -> None:
        key = (sender, receiver)
        if key in connections_set:
            return
        connections_set.add(key)
        ordered_connections.append({"sender": sender, "receiver": receiver})

    def _split_endpoint(endpoint: str, side: str, node_name: str) -> tuple[str, str]:
        if not isinstance(endpoint, str) or "." not in endpoint:
            raise ValueError(
                f"node '{node_name}': {side} endpoint must be '<node>.<port>', got {endpoint!r}"
            )
        peer, port = endpoint.split(".", 1)
        if not peer or not port:
            raise ValueError(
                f"node '{node_name}': {side} endpoint malformed: {endpoint!r}"
            )
        return peer, port

    for idx, node in enumerate(raw["nodes"]):
        if not isinstance(node, dict):
            raise ValueError(f"node #{idx} is not an object")
        name = node.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"node #{idx} missing 'name'")
        if name in components:
            raise ValueError(f"duplicate node name: {name!r}")
        module = node.get("module") or node.get("type") or node.get("cls")
        if not isinstance(module, str) or not module:
            raise ValueError(f"node '{name}' missing 'module' (fully qualified class path)")
        params = node.get("params") or node.get("init_parameters") or {}
        if not isinstance(params, dict):
            raise ValueError(f"node '{name}' params must be an object")
        components[name] = {"type": module, "init_parameters": params}

        for edge in node.get("inputs") or []:
            if not isinstance(edge, dict):
                raise ValueError(f"node '{name}' has malformed input edge: {edge!r}")
            port = edge.get("port")
            source = edge.get("from") or edge.get("sender")
            if not isinstance(port, str) or not port:
                raise ValueError(f"node '{name}' input edge missing 'port'")
            if not isinstance(source, str) or not source:
                raise ValueError(f"node '{name}' input edge missing 'from'")
            _split_endpoint(source, "input", name)
            _add_connection(source, f"{name}.{port}")

        for edge in node.get("outputs") or []:
            if not isinstance(edge, dict):
                raise ValueError(f"node '{name}' has malformed output edge: {edge!r}")
            port = edge.get("port")
            target = edge.get("to") or edge.get("receiver")
            if not isinstance(port, str) or not port:
                raise ValueError(f"node '{name}' output edge missing 'port'")
            if not isinstance(target, str) or not target:
                raise ValueError(f"node '{name}' output edge missing 'to'")
            _split_endpoint(target, "output", name)
            _add_connection(f"{name}.{port}", target)

    return {
        "metadata": raw.get("metadata") or {},
        "max_runs_per_component": raw.get("max_runs_per_component", 100),
        "components": components,
        "connections": ordered_connections,
        "connection_type_validation": bool(raw.get("connection_type_validation", True)),
    }


def from_haystack_dict(haystack_dict: dict[str, Any]) -> dict[str, Any]:
    """Convert haystack standard dict to node-centric for visualisation.

    Reverse of :func:`to_haystack_dict`. Connections are recorded on the
    receiver side (each node's ``inputs``) so each edge appears exactly once.
    """
    components = haystack_dict.get("components") or {}
    connections = haystack_dict.get("connections") or []
    nodes: list[dict[str, Any]] = []
    inputs_by_node: dict[str, list[dict[str, str]]] = {name: [] for name in components}
    for edge in connections:
        sender = edge.get("sender")
        receiver = edge.get("receiver")
        if not sender or not receiver or "." not in receiver:
            continue
        recv_name, recv_port = receiver.split(".", 1)
        inputs_by_node.setdefault(recv_name, []).append(
            {"port": recv_port, "from": sender}
        )
    for name, comp in components.items():
        nodes.append({
            "name": name,
            "module": comp.get("type"),
            "params": comp.get("init_parameters") or {},
            "inputs": inputs_by_node.get(name, []),
        })
    return {
        "metadata": haystack_dict.get("metadata") or {},
        "max_runs_per_component": haystack_dict.get("max_runs_per_component", 100),
        "connection_type_validation": bool(haystack_dict.get("connection_type_validation", True)),
        "nodes": nodes,
    }
