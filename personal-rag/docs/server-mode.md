# Server Mode Notes

This plugin uses a Docker-based server deployment instead of a desktop AppImage flow.

## Why

- Headless environments fail when the desktop AppImage requires X11 / DISPLAY.
- Docker deployment is better suited for server-style setup and repeatable automation.

## Current Setup Behavior

- Pull `mintplexlabs/anythingllm:latest`
- Start container `personal-rag-server`
- Persist data under `~/personal-rag/storage`
- Expose web UI at `http://localhost:3001`
- Insert fixed API key `my-secret-rag-key-2026` into the local `api_keys` table

## Fixed API Key

The setup script enforces a fixed API key by inserting it directly into the local SQLite database after the server initializes.
This keeps the plugin aligned with the required fixed-key workflow.
