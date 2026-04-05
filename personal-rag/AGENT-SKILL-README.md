# Personal RAG Agent Skill

This plugin is organized so an agent can directly use `skills/personal-rag-skill/SKILL.md` as the main operating instruction file.

## What the agent should do

- Run `scripts/setup_rag.sh` for initial environment setup.
- Run `scripts/update_docs.sh` after files are added to `~/my_rag_docs`.
- Use the configured MCP connection to query workspace `my_rag`.

## Purpose

This file is only a short repository note. The actual agent skill is:

- `personal-rag/skills/personal-rag-skill/SKILL.md`
