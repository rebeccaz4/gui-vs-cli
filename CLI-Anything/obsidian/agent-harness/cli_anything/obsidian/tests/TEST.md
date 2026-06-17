# Test Plan — cli-anything-obsidian

## Unit Tests (`test_core.py`)

Run without any backend:

```bash
python -m pytest cli_anything/obsidian/tests/test_core.py -v
```

Covers:
- Backend URL construction and auth headers
- API client error handling (connection, timeout, HTTP errors)
- JSON and text response parsing
- CLI argument parsing (--help for all groups)
- --json flag output
- --api-key and --host flags
- Session state management
- Vault commands with mocked API
- Search commands with mocked API
- Error handling (missing API key, connection errors)
- Core module function calls with mocked backend

## E2E Tests (`test_full_e2e.py`)

Requires Obsidian running with Local REST API plugin:

```bash
OBSIDIAN_API_KEY=your-key python -m pytest cli_anything/obsidian/tests/test_full_e2e.py -v
```

Covers:
- Server status check
- Vault list, create, read, append, delete lifecycle
- Simple search
- Automatic cleanup of test notes
