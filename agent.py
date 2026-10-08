#!/usr/bin/env python3
"""A small command-line coding agent built on the IU REALLMS API.

Features
  * bash tool: the model can run shell commands in your working directory
  * chat loop: ask questions, get answers, multi-step tool use until done
  * REALLMS API: OpenAI-compatible endpoint, key read from REALLMS_API_KEY
  * Risk-aware approval (my added feature): safe, read-only commands run
    automatically; anything risky (rm, sudo, redirects, git push, ...) pauses
    and asks you to approve, deny, or approve-all for the session.
  * Slash commands: /save, /reset, /model <name>, /auto, /quit
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime

from openai import OpenAI

BASE_URL = "https://reallms.rescloud.iu.edu/direct/v1"
DEFAULT_MODEL = "Qwen3-Coder-Next"
MAX_OUTPUT_CHARS = 8000
COMMAND_TIMEOUT_S = 60
MAX_STEPS = 15  # tool-use rounds per user message

SYSTEM_PROMPT = (
    "You are a concise command-line coding agent. You have a `bash` tool that "
    "runs shell commands in the user's current working directory. Use it to "
    "inspect files, run code, and verify your work rather than guessing. "
    "Prefer small, safe commands. Explain what you did briefly."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command and return its stdout, stderr and exit code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The shell command to run."}
                },
                "required": ["command"],
            },
        },
    }
]

# ---- risk classification -------------------------------------------------

SAFE_COMMANDS = {
    "ls", "pwd", "cat", "head", "tail", "wc", "echo", "grep", "rg", "find",
    "tree", "file", "stat", "date", "whoami", "which", "python", "python3",
    "pip", "git", "uname", "df", "du", "env", "sort", "uniq", "diff",
}
RISKY_PATTERNS = [
    r"\brm\b", r"\bsudo\b", r"\bmv\b", r"\bchmod\b", r"\bchown\b", r"\bdd\b",
    r"\bkill(all)?\b", r"\bcurl\b", r"\bwget\b", r"\bssh\b", r"\bscp\b",
    r"\bgit\s+(push|reset|clean|checkout|rebase)\b", r"\bpip3?\s+(install|uninstall)\b",
    r">", r"\|\s*(sh|bash)\b", r"\bmkfs\b", r"\bshutdown\b", r"\breboot\b",
]


def classify(command: str) -> str:
    """Return 'safe' or 'risky'."""
    if any(re.search(p, command) for p in RISKY_PATTERNS):
        return "risky"
    # Every command in a chain (; && || |) must start with a known-safe program.
    parts = re.split(r"&&|\|\||;|\|", command)
    for part in parts:
        tokens = part.strip().split()
        if not tokens or tokens[0] not in SAFE_COMMANDS:
            return "risky"
    return "safe"


# ---- tool execution ------------------------------------------------------


def run_bash(command: str) -> str:
    try:
        proc = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_S
        )
        out = f"exit code: {proc.returncode}\n"
        if proc.stdout:
            out += f"stdout:\n{proc.stdout}"
        if proc.stderr:
            out += f"stderr:\n{proc.stderr}"
    except subprocess.TimeoutExpired:
        out = f"error: command timed out after {COMMAND_TIMEOUT_S}s"
    if len(out) > MAX_OUTPUT_CHARS:
        out = out[:MAX_OUTPUT_CHARS] + "\n...[output truncated]"
    return out


class Agent:
    def __init__(self, model: str):
        key = os.environ.get("REALLMS_API_KEY")
        if not key:
            sys.exit("Set REALLMS_API_KEY first:  export REALLMS_API_KEY='your-key'")
        self.client = OpenAI(base_url=BASE_URL, api_key=key)
        self.model = model
        self.auto_approve = False
        self.reset()

    def reset(self):
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    def approve(self, command: str) -> bool:
        """Ask the user before running risky commands."""
        if classify(command) == "safe" or self.auto_approve:
            return True
        print(f"\n\033[33m⚠ risky command:\033[0m {command}")
        answer = input("  run it? [y]es / [n]o / [a]lways this session: ").strip().lower()
        if answer in ("a", "always"):
            self.auto_approve = True
            return True
        return answer in ("y", "yes")

    def handle_tool_call(self, call) -> str:
        if call.function.name != "bash":
            return f"error: unknown tool {call.function.name}"
        try:
            command = json.loads(call.function.arguments)["command"]
        except (json.JSONDecodeError, KeyError):
            return "error: could not parse tool arguments"
        print(f"\033[36m$ {command}\033[0m")
        if not self.approve(command):
            return "The user denied this command. Try a different approach or ask them."
        result = run_bash(command)
        print(result.rstrip())
        return result

    def chat(self, user_text: str):
        self.messages.append({"role": "user", "content": user_text})
        for _ in range(MAX_STEPS):
            resp = self.client.chat.completions.create(
                model=self.model, messages=self.messages, tools=TOOLS
            )
            msg = resp.choices[0].message
            entry = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.function.name, "arguments": c.function.arguments},
                    }
                    for c in msg.tool_calls
                ]
            self.messages.append(entry)

            if msg.content:
                print(f"\n{msg.content}\n")
            if not msg.tool_calls:
                return
            for call in msg.tool_calls:
                self.messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": self.handle_tool_call(call)}
                )
        print("(stopped: hit the max tool-use steps for one message)")

    def save(self) -> str:
        name = f"conversation-{datetime.now():%Y%m%d-%H%M%S}.json"
        with open(name, "w") as f:
            json.dump(self.messages, f, indent=2)
        return name


def main():
    agent = Agent(os.environ.get("REALLMS_MODEL", DEFAULT_MODEL))
    print(f"REALLMS agent ({agent.model}). Commands: /save /reset /model <name> /auto /quit")
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        if text in ("/quit", "/exit"):
            break
        if text == "/reset":
            agent.reset()
            print("conversation cleared")
        elif text == "/save":
            print(f"saved to {agent.save()}")
        elif text == "/auto":
            agent.auto_approve = not agent.auto_approve
            print(f"auto-approve risky commands: {agent.auto_approve}")
        elif text.startswith("/model"):
            parts = text.split(maxsplit=1)
            if len(parts) == 2:
                agent.model = parts[1]
            print(f"model: {agent.model}")
        else:
            try:
                agent.chat(text)
            except Exception as e:  # network / API errors shouldn't kill the session
                print(f"API error: {e}")


if __name__ == "__main__":
    main()
