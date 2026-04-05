# Server Mode Notes

This plugin now uses a Docker-based server deployment instead of a desktop AppImage flow.

## Why

- Headless environments fail when the desktop AppImage requires X11 / DISPLAY.
- Docker deployment is better suited for server-style setup and repeatable automation.

## Current Setup Behavior

- Pull `mintplexlabs/anythingllm:latest`
- Start container `personal-rag-server`
- Persist data under `~/personal-rag/storage`
- Expose web UI at `http://localhost:3001`

## Important Limitation

The original fixed API key insertion flow was tied to desktop-local SQLite manipulation.
In Docker mode, initial admin setup and API issuance may need to happen through the app itself.
