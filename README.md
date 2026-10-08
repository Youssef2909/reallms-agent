# REALLMS Command-Line Coding Agent

A small terminal coding agent that uses IU's REALLMS API (OpenAI-compatible).

## Features
- **bash tool**: the model can run shell commands in your current directory
- **Chat loop**: ask questions, the agent works in multiple steps until it answers
- **REALLMS API**: `https://reallms.rescloud.iu.edu/direct/v1`, key from `REALLMS_API_KEY`
- **Risk-aware approval (custom feature)**: read-only commands (`ls`, `cat`, `grep`, ...) run automatically; risky ones (`rm`, `sudo`, redirects, `git push`, `curl`, ...) pause and ask you to approve, deny, or approve everything for the session
- `/save` conversation to JSON, `/reset`, `/model <name>`, `/auto`, `/quit`

## Setup
```bash
pip install -r requirements.txt
export REALLMS_API_KEY='your-key-here'
python agent.py
```

Optional: `export REALLMS_MODEL=gpt-oss-120b` to change the default model (`Qwen3-Coder-Next`).
