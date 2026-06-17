"""Parity tests — guarantee the CLI exposes every safari-mcp tool 1:1.

These tests verify that the Click CLI surface matches the bundled MCP tool
registry exactly. If these pass, you can trust the CLI to have the same
feature surface as the underlying safari-mcp server.

The tests iterate over every tool in ``resources/tools.json`` and check:
    1. The tool is reachable as ``safari tool <short-name>``
    2. Every parameter from the MCP schema has a matching Click option
    3. Required parameters are marked required in Click
    4. Boolean parameters are flag-style
    5. Enum parameters expose the same choices
    6. The number of CLI options matches the number of MCP parameters

Run:
    python -m pytest cli_anything/safari/tests/test_parity.py -v
"""

from __future__ import annotations

from click.testing import CliRunner

from cli_anything.safari.safari_cli import cli, tool_group
from cli_anything.safari.utils.tool_registry import load_registry


def _cli_name_for(param_name: str) -> str:
    """Match the same normalization the registry applies."""
    import re
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", param_name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", s)
    return s.replace("_", "-").lower()


class TestParityToolCoverage:
    """Every tool in the registry must be reachable as a Click subcommand."""

    def setup_method(self):
        self.registry = load_registry()

    def test_registry_not_empty(self):
        assert len(self.registry) > 0, "tools.json is empty"

    def test_registry_tool_count_matches_expected(self):
        # safari-mcp v2.7.8 exposes 84 tools. Update this when bumping upstream.
        assert len(self.registry) == 84, (
            f"Expected 84 tools from safari-mcp, got {len(self.registry)}. "
            f"Re-run scripts/extract_tools.py if safari-mcp was upgraded."
        )

    def test_every_tool_reachable_via_tool_group(self):
        """For each tool in the registry, `safari tool <short-name>` exists."""
        runner = CliRunner()
        missing = []
        for tool in self.registry:
            result = runner.invoke(
                cli, ["tool", tool.short_name, "--help"],
                catch_exceptions=False,
            )
            if result.exit_code != 0:
                missing.append(tool.short_name)
        assert not missing, f"Tools missing from CLI: {missing}"

    def test_tool_group_has_exactly_registry_count(self):
        """The number of Click subcommands must equal the registry size."""
        ctx_commands = tool_group.commands
        assert len(ctx_commands) == len(self.registry), (
            f"tool group has {len(ctx_commands)} commands, "
            f"registry has {len(self.registry)} tools"
        )

    def test_no_unexpected_tools_in_cli(self):
        """Every Click subcommand under `tool` must come from the registry."""
        registry_short_names = {t.short_name for t in self.registry}
        cli_names = set(tool_group.commands.keys())
        extras = cli_names - registry_short_names
        assert not extras, f"Unexpected tools in CLI (not in registry): {extras}"


class TestParityParameters:
    """Every MCP parameter must map to a Click option with the right shape."""

    def setup_method(self):
        self.registry = load_registry()

    def test_every_param_has_cli_option(self):
        """For each MCP param, the Click command has a matching option."""
        missing = []
        for tool in self.registry:
            cmd = tool_group.commands.get(tool.short_name)
            assert cmd is not None, f"missing command for {tool.short_name}"
            cli_opt_names = set()
            for param in cmd.params:
                if hasattr(param, "opts"):
                    for opt in param.opts:
                        # Strip leading dashes and normalize
                        clean = opt.lstrip("-")
                        # Boolean flags come as "--flag/--no-flag" so the raw
                        # opt may already be "flag" or "no-flag".
                        if clean.startswith("no-"):
                            clean = clean[3:]
                        cli_opt_names.add(clean)
            for mcp_param in tool.params:
                expected = _cli_name_for(mcp_param.name)
                if expected not in cli_opt_names:
                    missing.append(f"{tool.name}.{mcp_param.name} → --{expected}")
        assert not missing, f"Missing CLI options for params:\n" + "\n".join(missing)

    def test_required_params_are_required_in_click(self):
        """Required MCP params must be required in Click — covers all types.

        Previously this test skipped object/array params on the theory
        that JSON-string inputs were always optional. That masked a real
        parser regression (safari_mock_route.response / safari_run_script.steps
        were wrongly marked optional). The fix in extract_tools.py is
        locked in by this test now covering all types.
        """
        drift = []
        for tool in self.registry:
            cmd = tool_group.commands.get(tool.short_name)
            if cmd is None:
                continue
            click_required_by_name = {}
            for cp in cmd.params:
                if hasattr(cp, "opts"):
                    for opt in cp.opts:
                        clean = opt.lstrip("-")
                        if clean.startswith("no-"):
                            clean = clean[3:]
                        click_required_by_name[clean] = getattr(cp, "required", False)
            for mp in tool.params:
                if not mp.required:
                    continue
                key = _cli_name_for(mp.name)
                if not click_required_by_name.get(key, False):
                    drift.append(
                        f"{tool.name}.{mp.name} ({mp.type}) is required "
                        f"in MCP but not in Click"
                    )
        assert not drift, "\n".join(drift)

    def test_enum_choices_match(self):
        """Enum params must expose the same choices."""
        drift = []
        for tool in self.registry:
            cmd = tool_group.commands.get(tool.short_name)
            if cmd is None:
                continue
            for mp in tool.params:
                if not mp.choices:
                    continue
                target_name = _cli_name_for(mp.name)
                for cp in cmd.params:
                    if not hasattr(cp, "opts"):
                        continue
                    opts_clean = [o.lstrip("-") for o in cp.opts]
                    if target_name not in opts_clean:
                        continue
                    click_type = getattr(cp, "type", None)
                    if not hasattr(click_type, "choices"):
                        drift.append(
                            f"{tool.name}.{mp.name} has choices "
                            f"{mp.choices} but Click option has no Choice type"
                        )
                        continue
                    if set(click_type.choices) != set(mp.choices):
                        drift.append(
                            f"{tool.name}.{mp.name} choices mismatch: "
                            f"registry={mp.choices} cli={click_type.choices}"
                        )
        assert not drift, "\n".join(drift)


class TestParityIntrospection:
    """The introspection commands (tools list/describe) reflect the registry."""

    def test_tools_count_command(self):
        runner = CliRunner()
        registry = load_registry()
        result = runner.invoke(cli, ["tools", "count"])
        assert result.exit_code == 0
        assert result.output.strip() == str(len(registry))

    def test_tools_list_outputs_every_tool(self):
        runner = CliRunner()
        registry = load_registry()
        result = runner.invoke(cli, ["tools", "list"])
        assert result.exit_code == 0
        for tool in registry:
            assert tool.short_name in result.output

    def test_tools_list_json_shape(self):
        import json
        runner = CliRunner()
        result = runner.invoke(cli, ["--json", "tools", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        registry = load_registry()
        assert len(data) == len(registry)
        for item in data:
            assert {"name", "short_name", "description", "param_count"} <= set(item)

    def test_tools_describe_known_tool(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["tools", "describe", "safari_scroll"])
        assert result.exit_code == 0
        assert "safari_scroll" in result.output
        assert "direction" in result.output
        assert "amount" in result.output

    def test_tools_describe_by_short_name(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["tools", "describe", "scroll"])
        assert result.exit_code == 0
        assert "safari_scroll" in result.output

    def test_tools_describe_unknown_rejects(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["tools", "describe", "does_not_exist"])
        assert result.exit_code != 0


class TestParityHighValueSchemas:
    """Spot-check schemas that had known drift bugs in previous revisions.

    Each test here is a regression lock: if the parser or upstream
    safari-mcp changes these shapes, the test fails loud and the
    contributor has to decide whether to update the pin or fix the parser.
    """

    def setup_method(self):
        self.registry = load_registry()

    def test_scroll_uses_direction_not_xy(self):
        tool = self.registry.get("safari_scroll")
        assert tool is not None
        names = {p.name for p in tool.params}
        assert "direction" in names
        assert "amount" in names
        assert "x" not in names  # previously (wrongly) wrapped as --x/--y
        assert "y" not in names

    def test_drag_uses_source_and_target(self):
        tool = self.registry.get("safari_drag")
        assert tool is not None
        names = {p.name for p in tool.params}
        assert "sourceSelector" in names
        assert "targetSelector" in names

    def test_mock_route_uses_url_pattern(self):
        tool = self.registry.get("safari_mock_route")
        assert tool is not None
        names = {p.name for p in tool.params}
        assert "urlPattern" in names

    def test_throttle_network_has_profile(self):
        tool = self.registry.get("safari_throttle_network")
        assert tool is not None
        names = {p.name for p in tool.params}
        assert "profile" in names

    # ── Nested-schema parser regression locks ────────────────────
    # These test the bugs fixed in extract_tools.py's depth-aware
    # modifier detection. If the parser regresses, `.describe("...")`
    # from a nested schema would leak into the outer field description,
    # and `.optional()` on nested fields would incorrectly mark the
    # outer param as optional.

    def test_mock_route_response_is_required_not_status_description(self):
        """safari_mock_route.response is required and takes a JSON object.

        Regression target: the parser used to pick the nested
        .describe("HTTP status code") from the inner `status` field
        instead of the outer .describe("Mock response to return"),
        and wrongly inferred optional from nested .optional() calls.
        """
        tool = self.registry.get("safari_mock_route")
        assert tool is not None
        response = tool.get_param("response")
        assert response is not None
        assert response.required, "response must be required"
        assert response.type == "object"
        assert "status code" not in (response.description or "").lower(), (
            "parser leaked nested .describe(); expected 'Mock response to return'"
        )
        assert "mock response" in (response.description or "").lower()

    def test_run_script_steps_is_required_and_described_correctly(self):
        """safari_run_script.steps is required (no top-level .optional).

        Regression target: the parser's old naive `.optional(` check
        would find the nested `args: z.record(...).optional()` and
        wrongly mark the outer `steps` as optional.
        """
        tool = self.registry.get("safari_run_script")
        assert tool is not None
        steps = tool.get_param("steps")
        assert steps is not None
        assert steps.required, "steps must be required"
        assert steps.type == "array"
        assert "array of steps" in (steps.description or "").lower()

    def test_fill_form_fields_description_is_outer_not_inner(self):
        """safari_fill_form.fields description must come from the
        OUTER .describe(), not the nested selector's .describe("CSS selector").
        """
        tool = self.registry.get("safari_fill_form")
        assert tool is not None
        fields = tool.get_param("fields")
        assert fields is not None
        assert fields.required
        assert fields.type == "array"
        assert fields.description != "CSS selector", (
            "parser leaked the nested selector description; should be "
            "the outer 'Array of {selector, value} pairs'"
        )
        assert "selector" in fields.description.lower()
        assert "value" in fields.description.lower()

    def test_fill_and_submit_fields_description_is_outer(self):
        tool = self.registry.get("safari_fill_and_submit")
        assert tool is not None
        fields = tool.get_param("fields")
        assert fields is not None
        assert fields.required
        assert fields.description != "CSS selector"

    def test_evaluate_param_is_script_not_code(self):
        """safari_evaluate's parameter is named ``script`` upstream.

        Regression test: every prior version of the docs and a
        TestCallForwarding test exemplar called it ``code`` by mistake,
        which would silently send the wrong arg through ``raw`` calls
        and fail with ``--code`` is unknown option through ``tool``.
        """
        tool = self.registry.get("safari_evaluate")
        assert tool is not None
        param_names = {p.name for p in tool.params}
        assert "script" in param_names, (
            f"safari_evaluate must take 'script', got params: {param_names}"
        )
        assert "code" not in param_names, (
            "Doc/test bug regression: safari_evaluate uses 'script' upstream"
        )
        script_param = tool.get_param("script")
        assert script_param is not None
        assert script_param.required
        assert script_param.type == "string"

    def test_run_script_param_is_steps(self):
        """safari_run_script takes 'steps' (array). Locks the rename
        regression alongside test_evaluate_param_is_script_not_code."""
        tool = self.registry.get("safari_run_script")
        assert tool is not None
        param_names = {p.name for p in tool.params}
        assert "steps" in param_names
