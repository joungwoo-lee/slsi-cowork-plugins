"""Backward-compat shim package.

Re-exports every name the legacy ``scripts.*`` modules used to expose, but
delegates implementation to the modular ``retriever`` package. Keeping this
shim means existing imports in MCP handlers and external tooling continue to
work without modification while the real code lives next door.
"""
