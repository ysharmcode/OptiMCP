"""Function-schema export and framework adapters."""

import pytest

from optimcp.schemas import (
    anthropic_tool,
    check_consistency_schema,
    decision_spec_schema,
    openai_tool,
    solve_anthropic_tool,
    solve_openai_tool,
)


def test_openai_tool_is_check_consistency():
    tool = openai_tool()
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "check_consistency"
    assert "properties" in tool["function"]["parameters"]


def test_anthropic_tool_is_check_consistency():
    tool = anthropic_tool()
    assert tool["name"] == "check_consistency"
    assert "properties" in tool["input_schema"]


def test_check_consistency_schema_has_core_fields():
    schema = check_consistency_schema()
    assert set(schema["properties"]) >= {"document", "rules"}
    assert set(schema.get("$defs", {})) >= {"Expr", "Rule"}


def test_solve_decision_tool_still_available():
    assert solve_openai_tool()["function"]["name"] == "solve_decision"
    assert solve_anthropic_tool()["name"] == "solve_decision"


def test_decision_spec_schema_has_core_fields():
    schema = decision_spec_schema()
    assert set(schema["properties"]) >= {"variables", "objective", "constraints"}


def test_langchain_adapters_optional():
    pytest.importorskip("langchain_core")
    from optimcp.adapters.langchain import (
        build_check_consistency_tool,
        build_langchain_tool,
    )

    check_tool = build_check_consistency_tool()
    assert check_tool.name == "check_consistency"

    solve_tool = build_langchain_tool()
    assert solve_tool.name == "solve_decision"
