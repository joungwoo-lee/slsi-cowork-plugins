# SLSI Cowork Plugins

Plugins that extend Claude Cowork / Claude Code style workflows for SLSI cowork environments.

This repository follows the general layout of Anthropic's `knowledge-work-plugins` project, but starts intentionally small with a sample plugin and a personal RAG plugin.

## Structure

```text
sample-cowork-plugin/
├── .claude-plugin/plugin.json
├── .mcp.json
└── skills/
    └── sample-cowork-skill/
        └── SKILL.md

personal-rag/
├── .claude-plugin/plugin.json
├── .mcp.json
├── references/
│   └── concept.md
├── scripts/
│   ├── setup_rag.sh
│   └── update_docs.sh
└── skills/
    └── personal-rag-skill/
        └── SKILL.md
```

## Included Plugin

| Plugin | Purpose |
|--------|---------|
| `sample-cowork-plugin` | Minimal example plugin for SLSI Cowork environments |
| `personal-rag` | Agent-usable personal local RAG workflow with setup, ingestion, and retrieval skill structure |
| `win-cert-setup` | Windows SSL certificate installation skill for enterprise CA trust issues in AI and CLI tools |
| `hybrid-retriever-modular-tools` | Skill that scaffolds and registers new pipeline modules in the `chain_react_ADK/hybrid_retriever_modular` project — author a node, drop it under `modules/`, and the UI palette + contract panel auto-update. |

## Notes

- This repo is a starter template.
- Add more plugins, commands, and skills as needed.
- The sample skill is intentionally simple and demonstrates the expected file structure only.
