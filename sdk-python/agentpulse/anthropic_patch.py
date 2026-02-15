"""Auto-patch for Anthropic SDK to report usage to AgentPulse."""

from __future__ import annotations

import functools
import time
from typing import Any, Optional
import os

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


def patch_anthropic(pulse_client: Optional[Any] = None, agent_name: Optional[str] = None) -> None:
    """Auto-patch Anthropic SDK to report API calls to AgentPulse.
    
    Args:
        pulse_client: AgentPulse client instance (uses default if None)
        agent_name: Agent name for events (uses default if None)
    """
    if not HAS_ANTHROPIC:
        if pulse_client and pulse_client.debug:
            print("AgentPulse: Anthropic SDK not installed, skipping auto-patch")
        return

    if pulse_client is None:
        from agentpulse import pulse
        pulse_client = pulse
    
    if not pulse_client.enabled:
        return

    # Patch the messages.create method
    if hasattr(anthropic.Anthropic, 'messages'):
        original_create = anthropic.Anthropic.messages.create
        
        def patched_create(self, **kwargs):
            start_time = time.time()
            session_id = agent_name or pulse_client.agent_name or "anthropic-session"
            
            # Start session
            pulse_client.session_start(session_id, model=kwargs.get('model', 'unknown'))
            
            try:
                # Make the original API call
                response = original_create(self, **kwargs)
                
                # Extract usage data
                usage_data = {}
                if hasattr(response, 'usage') and response.usage:
                    usage_data = {
                        'input_tokens': getattr(response.usage, 'input_tokens', 0),
                        'output_tokens': getattr(response.usage, 'output_tokens', 0),
                    }
                
                # Calculate rough cost (Anthropic pricing as of 2026)
                model = kwargs.get('model', '')
                cost = 0.0
                if 'opus' in model.lower():
                    cost = usage_data.get('input_tokens', 0) * 0.015 / 1000 + usage_data.get('output_tokens', 0) * 0.075 / 1000
                elif 'sonnet' in model.lower():
                    cost = usage_data.get('input_tokens', 0) * 0.003 / 1000 + usage_data.get('output_tokens', 0) * 0.015 / 1000
                elif 'haiku' in model.lower():
                    cost = usage_data.get('input_tokens', 0) * 0.00025 / 1000 + usage_data.get('output_tokens', 0) * 0.00125 / 1000
                
                # Report completion event
                pulse_client.session_message(
                    session_id,
                    content=f"API call completed",
                    role="assistant",
                    model=kwargs.get('model'),
                    tokens_in=usage_data.get('input_tokens', 0),
                    tokens_out=usage_data.get('output_tokens', 0),
                    cost_usd=cost,
                    duration_ms=int((time.time() - start_time) * 1000)
                )
                
                return response
                
            except Exception as e:
                # Report error
                pulse_client.event(
                    "error",
                    agent=pulse_client.agent_name,
                    session=session_id,
                    data={
                        "error": str(e),
                        "model": kwargs.get('model'),
                        "duration_ms": int((time.time() - start_time) * 1000)
                    }
                )
                raise
        
        # Apply the patch
        anthropic.Anthropic.messages.create = patched_create
        
        if pulse_client.debug:
            print("AgentPulse: Successfully patched Anthropic SDK")


def unpatch_anthropic() -> None:
    """Remove AgentPulse patches from Anthropic SDK."""
    # This would require storing original methods, skip for now
    pass


# Auto-patch on import if enabled
if os.environ.get("AGENTPULSE_AUTOPATCH", "").lower() in ("1", "true", "yes"):
    patch_anthropic()