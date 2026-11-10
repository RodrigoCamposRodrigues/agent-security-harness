"""OWASP IDs the cases may cite, so a typo in a case file fails loudly and the
report can list what this project does not cover, and why."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    list: Literal["LLM 2026", "Agentic 2026"]
    in_scope: bool
    reason: str = ""


def _llm(id_, name, reason=""):
    return Category(id_, name, "LLM 2026", not reason, reason)


def _asi(id_, name, reason=""):
    return Category(id_, name, "Agentic 2026", not reason, reason)


_ALL = [
    _llm("LLM01", "Prompt Injection"),
    _llm("LLM02", "Sensitive Information Disclosure"),
    _llm("LLM03", "Excessive Agency"),
    _llm("LLM04", "Supply Chain", "Both targets use fixed, pinned dependencies; attacking them is not an agent behaviour."),
    _llm("LLM05", "Data and Model Poisoning", "No training or fine-tuning happens; the attacker cannot touch model weights."),
    _llm("LLM06", "Unbounded Consumption"),
    _llm("LLM07", "Misinformation"),
    _llm("LLM08", "Hidden Context Exposure"),
    _llm("LLM09", "Vector and Embedding Weaknesses", "Neither target uses retrieval or a vector store."),
    _llm("LLM10", "Improper Output Handling", "No downstream system executes or renders the agents' output as code."),
    _asi("ASI01", "Agent Goal Hijack"),
    _asi("ASI02", "Tool Misuse and Exploitation"),
    _asi("ASI03", "Identity and Privilege Abuse"),
    _asi("ASI04", "Agentic Supply Chain Vulnerabilities", "Tools are built in; no third-party tools or MCP servers are loaded."),
    _asi("ASI05", "Unexpected Code Execution", "Neither agent has a tool that runs code."),
    _asi("ASI06", "Memory and Context Poisoning", "Neither agent keeps memory between runs; each run starts from a fresh world."),
    _asi("ASI07", "Insecure Inter-Agent Communication", "Each target is a single agent; there is no agent-to-agent channel."),
    _asi("ASI08", "Cascading Failures", "Single agent with no downstream agents to cascade into."),
    _asi("ASI09", "Human-Agent Trust Exploitation"),
    _asi("ASI10", "Rogue Agents", "Out of scope: the threat model is an outside attacker, not a misaligned agent."),
]

CATEGORIES: dict[str, Category] = {c.id: c for c in _ALL}
