"""Function-schema export and framework adapters."""

import pytest

from optimcp.schemas import anthropic_tool, decision_spec_schema, openai_tool


def test_openai_tool_schema_shape():
    tool = openai_tool()
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "solve_decision"
    assert "properties" in tool["function"]["parameters"]


def test_anthropic_tool_schema_shape():
    tool = anthropic_tool()
    assert tool["name"] == "solve_decision"
    assert "properties" in tool["input_schema"]


def test_decision_spec_schema_has_core_fields():
    schema = decision_spec_schema()
    assert set(schema["properties"]) >= {"variables", "objective", "constraints"}


def test_langchain_adapter_optional():
    pytest.importorskip("langchain_core")
    from optimcp.adapters.langchain import build_langchain_tool

    tool = build_langchain_tool()
    assert tool.name == "solve_decision"
