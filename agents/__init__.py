"""
Unified OSWorld agent module.

Usage:
    from agents import create_agent

    agent = create_agent("claude-sonnet-4-5", platform="ubuntu")
    agent.reset()
    reasoning, actions = agent.predict(instruction="Open Firefox", obs={"screenshot": screenshot_bytes})
"""

from .registry import create_agent, list_models

__all__ = ["create_agent", "list_models"]
