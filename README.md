# ai-hallucination-firewall

![Python](https://img.shields.io/badge/Python_3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![Pre-commit](https://img.shields.io/badge/pre--commit-FAB040?style=flat-square&logo=precommit&logoColor=black)

Pre-commit verification proxy that catches hallucinated code in AI-generated output before it reaches your codebase.

## What It Detects

| Issue | Example |
|-------|---------|
| Hallucinated functions | Calling `str.to_camel()` (doesn't exist) |
| Invalid imports | `from os import quantum_sort` |
| Wrong signatures | `json.dumps(data, compress=True)` |
| Deprecated APIs | Using removed stdlib functions |
| Nonexistent packages | `pip install fast-quantum-ml` |

## Supported Languages

- Python
- JavaScript
- TypeScript

## Installation

```bash
pip install ai-hallucination-firewall
```

### As Pre-commit Hook

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/tranhoangtu-it/ai-hallucination-firewall
    hooks:
      - id: ai-hallucination-check
```

## Usage

```bash
# Scan a file
ai-firewall check path/to/file.py

# Scan a directory
ai-firewall check src/
```

## VS Code Extension

A companion VS Code extension provides real-time detection as you code. See [vscode-extension/](./vscode-extension/) for details.

## Tech Stack

- **Parser**: tree-sitter (AST analysis)
- **Validation**: PyPI/npm registry checks
- **Integration**: pre-commit hooks, CLI, API server

## License

See [LICENSE](./LICENSE) for details.
