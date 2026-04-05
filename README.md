# SLSI Cowork Plugins

Plugins that extend Claude Cowork / Claude Code style workflows for SLSI cowork environments.

This repository follows the general layout of Anthropic's `knowledge-work-plugins` project, but starts intentionally small with a single sample plugin.

## Structure

```text
sample-cowork-plugin/
├── .claude-plugin/plugin.json
├── .mcp.json
└── skills/
    └── sample-cowork-skill/
        └── SKILL.md
```

## Included Plugin

| Plugin | Purpose |
|--------|---------|
| `sample-cowork-plugin` | Minimal example plugin for SLSI Cowork environments |
| `rag-local-anythingllm` | Local AnythingLLM-based RAG workflow with setup, ingestion, and retrieval skill structure |

## Notes

- This repo is a starter template.
- Add more plugins, commands, and skills as needed.
- The sample skill is intentionally simple and demonstrates the expected file structure only.
