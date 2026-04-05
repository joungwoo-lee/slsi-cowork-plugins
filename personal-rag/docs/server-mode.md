# Server Mode Notes

This plugin uses a non-Docker headless backend deployment instead of a desktop AppImage flow.

## Why

- Headless environments fail when the desktop AppImage requires X11 / DISPLAY.
- The intended server mode here is host-based backend execution, not Docker container deployment.
- This keeps the workflow aligned with the server-only concept in `개인rag서버용.md`.

## Current Setup Behavior

- Clone `Mintplex-Labs/anything-llm` into `~/anythingllm-server`
- Install backend dependencies in `server/`
- Initialize Prisma and local SQLite storage
- Start the backend with `nohup yarn start`
- Insert fixed API key `my-secret-rag-key-2026`
- Create workspace `my_rag`

## Important Notes

- This is a non-Docker setup.
- The workflow expects `yarn`, `git`, `sqlite3`, `curl`, and `openssl` on the host.
- Retrieval still uses the MCP connection against `http://localhost:3001/api`.
