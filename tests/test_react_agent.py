import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from react_agent import build_tool_registry, format_tools_for_prompt

def test_build_tool_registry():
    tools = build_tool_registry()
    assert isinstance(tools, dict)
    assert len(tools) > 10
    for name, tool in tools.items():
        assert "description" in tool
        assert "params" in tool

def test_tool_registry_includes_skills():
    tools = build_tool_registry()
    assert "execute_skill" in tools

def test_tool_registry_includes_memory():
    tools = build_tool_registry()
    assert "memory_recall" in tools
    assert "memory_store" in tools

def test_format_tools_for_prompt():
    tools = build_tool_registry()
    prompt = format_tools_for_prompt(tools)
    assert isinstance(prompt, str)
    assert "research" in prompt
    assert "execute_skill" in prompt
