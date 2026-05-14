"""Shim: re-export ``retriever.graph``."""
from retriever.graph import *  # noqa: F401,F403
from retriever.graph import (  # noqa: F401
    close_graph,
    graph_path,
    open_graph,
    rebuild_from_sqlite,
    run_query,
)
