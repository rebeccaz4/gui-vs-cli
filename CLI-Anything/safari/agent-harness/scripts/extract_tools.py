#!/usr/bin/env python3
"""Extract MCP tool schemas from safari-mcp's index.js.

This script parses the JavaScript source of safari-mcp offline (no Node.js,
no subprocess, no MCP spawn) and produces a JSON tool registry that is
bundled with cli-anything-safari. Bundling ensures:
    1. True feature parity — every tool exposed by safari-mcp is reachable
    2. --help works without touching the network or spawning safari-mcp
    3. The CLI doesn't disrupt concurrent safari-mcp instances (singleton killer)

Usage:
    python scripts/extract_tools.py /path/to/safari-mcp/index.js \\
        cli_anything/safari/resources/tools.json

Re-run this whenever safari-mcp upgrades to refresh the bundled schema.

The parser is hand-written (no external deps) and uses a depth-aware
scanner for Zod modifier chains so nested schemas don't confuse it.
It handles the specific Zod patterns safari-mcp uses:
    - z.string() / z.number() / z.boolean() / z.array(...) / z.enum([...])
    - z.coerce.number() (mapped to number)
    - z.object({...}) / z.literal("...") / z.record(...)
    - .optional() / .default(...) / .nullable() modifiers
    - .describe("...") metadata
    - nested z.array(z.object({...})).describe("outer") patterns
"""

import json
import re
import sys
from pathlib import Path


def extract_tools(source: str) -> list[dict]:
    """Scan the source for all server.tool(...) invocations and return their schemas."""
    tools: list[dict] = []
    idx = 0
    while True:
        start = source.find("server.tool(", idx)
        if start == -1:
            break
        tool = _parse_tool_block(source, start)
        if tool:
            tools.append(tool)
            idx = tool.pop("_end")
        else:
            idx = start + len("server.tool(")
    return tools


def _parse_tool_block(source: str, start: int) -> dict | None:
    pos = start + len("server.tool(")
    pos = _skip_ws(source, pos)

    # Name
    if pos >= len(source) or source[pos] != '"':
        return None
    name_end = _find_string_end(source, pos)
    if name_end == -1:
        return None
    name = _decode_js_string(source[pos + 1:name_end])
    pos = _skip_ws_comma(source, name_end + 1)

    # Description
    if pos >= len(source) or source[pos] != '"':
        return None
    desc_end = _find_string_end(source, pos)
    if desc_end == -1:
        return None
    description = _decode_js_string(source[pos + 1:desc_end])
    pos = _skip_ws_comma(source, desc_end + 1)

    # Schema object
    if pos >= len(source) or source[pos] != "{":
        return None
    schema_end = _find_brace_end(source, pos)
    if schema_end == -1:
        return None
    schema_src = source[pos:schema_end + 1]
    params = _parse_schema_block(schema_src)
    pos = schema_end + 1

    properties: dict[str, dict] = {}
    required: list[str] = []
    for p in params:
        properties[p["name"]] = _param_to_jsonschema(p)
        if p["required"]:
            required.append(p["name"])

    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
        "_end": pos,
    }


# ── String helpers (JS string decoding, not Python unicode_escape) ──
def _decode_js_string(inner: str) -> str:
    """Decode a JS string literal's escape sequences safely.

    We cannot use ``bytes.decode('unicode_escape')`` because it assumes
    latin-1 input, which corrupts multi-byte UTF-8 characters. Instead we
    handle the JS escapes we actually care about and leave the rest alone.
    """
    def _replace(m: re.Match) -> str:
        esc = m.group(0)
        if esc == '\\"':
            return '"'
        if esc == "\\'":
            return "'"
        if esc == "\\\\":
            return "\\"
        if esc == "\\n":
            return "\n"
        if esc == "\\r":
            return "\r"
        if esc == "\\t":
            return "\t"
        if esc == "\\b":
            return "\b"
        if esc == "\\f":
            return "\f"
        if esc == "\\/":
            return "/"
        if esc.startswith("\\u"):
            try:
                return chr(int(esc[2:], 16))
            except ValueError:
                return esc
        if esc.startswith("\\x"):
            try:
                return chr(int(esc[2:], 16))
            except ValueError:
                return esc
        return esc
    return re.sub(
        r'\\(?:["\'\\/bfnrt]|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2})',
        _replace,
        inner,
    )


def _skip_ws(src: str, pos: int) -> int:
    while pos < len(src) and src[pos] in " \t\r\n":
        pos += 1
    return pos


def _skip_ws_comma(src: str, pos: int) -> int:
    pos = _skip_ws(src, pos)
    if pos < len(src) and src[pos] == ",":
        pos += 1
    return _skip_ws(src, pos)


def _find_string_end(src: str, start: int) -> int:
    """Return index of the closing quote for a double-quoted string."""
    if src[start] != '"':
        return -1
    i = start + 1
    while i < len(src):
        if src[i] == "\\":
            i += 2
            continue
        if src[i] == '"':
            return i
        i += 1
    return -1


def _find_matching_paren(src: str, open_pos: int) -> int:
    """Find the index of the ')' matching the '(' at open_pos."""
    if open_pos >= len(src) or src[open_pos] != "(":
        return -1
    depth = 1
    i = open_pos + 1
    while i < len(src):
        c = src[i]
        if c == '"':
            end = _find_string_end(src, i)
            if end == -1:
                return -1
            i = end + 1
            continue
        if c == "'":
            i += 1
            while i < len(src) and src[i] != "'":
                i += 2 if src[i] == "\\" else 1
            i += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _find_brace_end(src: str, start: int) -> int:
    """Find the matching closing brace, respecting strings and nesting."""
    if src[start] != "{":
        return -1
    depth = 1
    i = start + 1
    while i < len(src):
        c = src[i]
        if c == '"':
            end = _find_string_end(src, i)
            if end == -1:
                return -1
            i = end + 1
            continue
        if c == "'":
            i += 1
            while i < len(src) and src[i] != "'":
                i += 2 if src[i] == "\\" else 1
            i += 1
            continue
        if c == "/" and i + 1 < len(src) and src[i + 1] == "/":
            while i < len(src) and src[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < len(src) and src[i + 1] == "*":
            i += 2
            while i + 1 < len(src) and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _parse_schema_block(src: str) -> list[dict]:
    """Parse `{ foo: z.string()..., bar: z.number()..., }` into field dicts."""
    inner = src[1:-1].strip()
    if not inner:
        return []
    fields = _split_top_level(inner, ",")
    params: list[dict] = []
    for field in fields:
        field = field.strip().rstrip(",").strip()
        if not field or field.startswith("//"):
            continue
        p = _parse_field(field)
        if p:
            params.append(p)
    return params


def _split_top_level(src: str, sep: str) -> list[str]:
    """Split on `sep` at depth 0 (outside brackets/parens/strings)."""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    i = 0
    while i < len(src):
        c = src[i]
        if c == '"':
            end = _find_string_end(src, i)
            if end == -1:
                buf.append(src[i:])
                break
            buf.append(src[i:end + 1])
            i = end + 1
            continue
        if c == "'":
            start = i
            i += 1
            while i < len(src) and src[i] != "'":
                i += 2 if src[i] == "\\" else 1
            if i >= len(src):
                # Unterminated single-quoted string; bail
                buf.append(src[start:])
                break
            buf.append(src[start:i + 1])
            i += 1
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    if buf:
        parts.append("".join(buf))
    return parts


_TYPE_MAP = {
    "string": "string",
    "number": "number",
    "boolean": "boolean",
    "array": "array",
    "object": "object",
    "enum": "string",      # enums become strings with choices
    "literal": "string",   # literals become strings with one choice
    "any": "string",
    "unknown": "string",
    "null": "null",
    "nullable": "string",
    "record": "object",
}


def _parse_field(field: str) -> dict | None:
    """Parse one field: `name: z.TYPE(...).modifier().describe(...)`."""
    m = re.match(r"(\w+)\s*:\s*(.*)", field, re.DOTALL)
    if not m:
        return None
    name = m.group(1)
    value = m.group(2).strip()

    # Extract root Zod type
    root_match = re.match(r"z\.(?:coerce\.)?(\w+)", value)
    if not root_match:
        return None
    zod_type = root_match.group(1)
    json_type = _TYPE_MAP.get(zod_type, "string")

    # Skip past the root call's parens so we can look at modifiers alone.
    root_args_text = ""
    modifier_text = ""
    after_root_start = root_match.end()
    if after_root_start < len(value) and value[after_root_start] == "(":
        close_pos = _find_matching_paren(value, after_root_start)
        if close_pos == -1:
            return None
        root_args_text = value[after_root_start + 1:close_pos]
        modifier_text = value[close_pos + 1:]
    else:
        # Root has no call (e.g. `z.string` without parens) — unusual but handled
        modifier_text = value[after_root_start:]

    # Parse modifier chain at top level only (nested modifiers inside
    # root_args_text are ignored, which is the fix for the old nested-describe bug).
    modifiers = _parse_modifier_chain(modifier_text)

    optional = "optional" in modifiers
    nullable = "nullable" in modifiers
    default_val = modifiers.get("default")
    description = modifiers.get("describe", "")

    # Enum / literal choices
    choices = None
    if zod_type == "enum":
        enum_match = re.match(r"\s*\[([^\]]*)\]", root_args_text, re.DOTALL)
        if enum_match:
            choices = []
            for s in enum_match.group(1).split(","):
                s = s.strip().strip('"').strip("'")
                if s:
                    choices.append(s)
    elif zod_type == "literal":
        lit_match = re.match(r'\s*"((?:[^"\\]|\\.)*)"', root_args_text)
        if lit_match:
            choices = [_decode_js_string(lit_match.group(1))]

    is_required = not (optional or nullable or default_val is not None)

    return {
        "name": name,
        "type": json_type,
        "description": description,
        "required": is_required,
        "default": default_val.strip() if default_val else None,
        "choices": choices,
    }


def _parse_modifier_chain(text: str) -> dict:
    """Parse `.foo(args).bar(args)...` returning {method: args_str}.

    Walks the chain sequentially. For each `.method(...)` found, records
    the argument text (inner of the parens). For `.describe(...)`, also
    decodes the string literal if the arg looks like `"..."`.
    """
    result: dict = {}
    i = 0
    while i < len(text):
        c = text[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c != ".":
            break  # end of modifier chain
        m = re.match(r"\.(\w+)\s*\(", text[i:])
        if not m:
            break
        method = m.group(1)
        arg_open = i + m.end() - 1  # position of '('
        arg_close = _find_matching_paren(text, arg_open)
        if arg_close == -1:
            break
        arg_content = text[arg_open + 1:arg_close]
        if method == "describe":
            # Handle both double- and single-quoted string literals.
            dq_match = re.match(
                r'\s*"((?:[^"\\]|\\.)*)"\s*',
                arg_content,
            )
            sq_match = re.match(
                r"\s*'((?:[^'\\]|\\.)*)'\s*",
                arg_content,
            )
            if dq_match:
                arg_content = _decode_js_string(dq_match.group(1))
            elif sq_match:
                arg_content = _decode_js_string(sq_match.group(1))
        result[method] = arg_content
        i = arg_close + 1
    return result


def _param_to_jsonschema(param: dict) -> dict:
    schema: dict = {"type": param["type"]}
    if param.get("description"):
        schema["description"] = param["description"]
    if param.get("choices"):
        schema["enum"] = param["choices"]
    default = param.get("default")
    if default is not None:
        schema["default"] = _coerce_default(default, param["type"])
    return schema


def _coerce_default(raw: str, json_type: str):
    """Coerce a Zod ``.default(...)`` raw text into the JSON Schema type.

    The parser captures defaults as raw JS text (e.g. ``"false"``,
    ``"42"``, ``"\"auto\""``). We convert to the matching Python/JSON
    primitive so the bundled JSON Schema is type-correct.
    """
    raw = raw.strip()
    if json_type == "boolean":
        if raw == "true":
            return True
        if raw == "false":
            return False
        return raw
    if json_type in ("number", "integer"):
        try:
            if "." in raw:
                return float(raw)
            return int(raw)
        except ValueError:
            return raw
    if json_type == "null" or raw == "null":
        return None
    # String / array / object — try to strip quotes for plain string defaults
    if (raw.startswith('"') and raw.endswith('"')) or (
        raw.startswith("'") and raw.endswith("'")
    ):
        return raw[1:-1]
    return raw


def _extract_pkg_version(index_js_path: Path) -> str:
    """Try to read version from sibling package.json."""
    pkg = index_js_path.parent / "package.json"
    if not pkg.is_file():
        return "unknown"
    try:
        data = json.loads(pkg.read_text())
        return data.get("version", "unknown")
    except Exception:
        return "unknown"


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "Usage: extract_tools.py <path/to/safari-mcp/index.js> [output.json]",
            file=sys.stderr,
        )
        return 2

    index_path = Path(sys.argv[1]).expanduser().resolve()
    if not index_path.is_file():
        print(f"Error: {index_path} not found", file=sys.stderr)
        return 1

    source = index_path.read_text()
    tools = extract_tools(source)

    out = {
        "source_version": _extract_pkg_version(index_path),
        "source_basename": index_path.name,  # no absolute path — privacy
        "tool_count": len(tools),
        "tools": tools,
    }

    if len(sys.argv) >= 3:
        out_path = Path(sys.argv[2]).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False))
        print(
            f"Extracted {len(tools)} tools from safari-mcp v{out['source_version']}",
            file=sys.stderr,
        )
        print(f"Wrote {out_path}", file=sys.stderr)
    else:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        print(
            f"Extracted {len(tools)} tools from safari-mcp v{out['source_version']}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
