from __future__ import annotations

import os
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = EVAL_DIR.parent
TASK_GEN_DIR = PROJECT_ROOT / "task_generator"
TASKS_DIR = TASK_GEN_DIR / "tasks"
VERIFIERS_DIR = PROJECT_ROOT / "verifiers"

DISPLAY_WIDTH = 1920
DISPLAY_HEIGHT = 1080

THUNDERBIRD_PROFILE_FILENAME = "thunderbird-profile.tar.gz"
OBS_SCENE_COLLECTION_REMOTE = "/home/user/.config/obs-studio/basic/scenes/Untitled.json"

DEFAULT_MODEL = os.getenv("EVAL_MODEL", "gpt-5.4")
DEFAULT_MAX_ITERATIONS = int(os.getenv("EVAL_MAX_ITERATIONS", "40"))
DEFAULT_SANDBOX_TIMEOUT = int(os.getenv("EVAL_SANDBOX_TIMEOUT", "200"))

JUDGE_MODEL = os.getenv("JUDGE_MODEL", "gpt-5.4")
MAX_JUDGE_SCREENSHOTS = 15
