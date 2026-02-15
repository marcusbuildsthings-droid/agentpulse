"""AgentPulse — Lightweight monitoring for indie AI agents."""

__version__ = "0.2.0"

from agentpulse.client import AgentPulse, pulse

# Auto-patching for popular AI SDKs
try:
    from agentpulse.anthropic_patch import patch_anthropic
    __all__ = ["AgentPulse", "pulse", "patch_anthropic"]
except ImportError:
    __all__ = ["AgentPulse", "pulse"]
