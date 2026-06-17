from __future__ import annotations

import json
import time
import traceback
from datetime import datetime

from evaluation.apps.registry import get_app_spec
from evaluation.apps.save import auto_save_app

from .agent_runner import run_agent_on_task
from .sandbox_session import setup_sandbox_session
from .verification import verify_task


def run_single_task(
    app_name,
    task,
    model_name,
    run_dir,
    run_id,
    max_iterations,
    sandbox_timeout,
    keep_alive=False,
    ready_check_only=False,
    env_backend="e2b",
    docker_image=None,
    docker_platform=None,
    docker_shm_size=None,
    docker_memory=None,
    docker_cpus=None,
    docker_ready_timeout=None,
    http_proxy=None,
    https_proxy=None,
    no_proxy=None,
):
    task_id = task["id"]
    task_text = task["task"]
    app_spec = get_app_spec(app_name)

    traj_dir = run_dir / "trajectories" / task_id
    traj_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 70}")
    print(f"  Task:  {task_id}")
    print(f"  App:   {app_name}")
    print(f"  Model: {model_name}")
    print(f"  Env:   {env_backend}")
    print(f"  Desc:  {task_text[:100]}...")
    print(f"{'=' * 70}")

    start_time = time.time()
    sandbox = None

    try:
        session = setup_sandbox_session(
            app_name,
            task,
            sandbox_timeout,
            run_id=run_id,
            run_mode="gui",
            env_backend=env_backend,
            docker_image=docker_image,
            docker_platform=docker_platform,
            docker_shm_size=docker_shm_size,
            docker_memory=docker_memory,
            docker_cpus=docker_cpus,
            docker_ready_timeout=docker_ready_timeout,
            http_proxy=http_proxy,
            https_proxy=https_proxy,
            no_proxy=no_proxy,
        )
        sandbox = session.sandbox
        stream_url = session.stream_url
        print(f"  Desktop: {stream_url}")

        if ready_check_only:
            print("  Ready checks passed; skipping agent run and verification")
            elapsed = time.time() - start_time
            result = {
                "task_id": task_id,
                "app": app_name,
                "model": model_name,
                "task": task_text,
                "env_backend": env_backend,
                "agent_done": False,
                "agent_steps": 0,
                "checks_passed": 0,
                "checks_total": 0,
                "reward": 1.0,
                "elapsed_seconds": round(elapsed, 1),
                "stream_url": stream_url,
                "ready_check_only": True,
                "timestamp": datetime.now().isoformat(),
            }
            traj_data = {**result, "verification_details": [], "trajectory": []}
            with open(traj_dir / "trajectory.json", "w") as handle:
                json.dump(traj_data, handle, indent=2, default=str)

            if keep_alive:
                print(f"\n  Desktop: {stream_url}")
                input("  Press Enter to kill sandbox...")

            return result

        agent_done, steps, trajectory = run_agent_on_task(
            sandbox,
            task_text,
            model_name,
            max_iterations,
            traj_dir,
        )
        print(f"  Agent finished in {steps} steps (done={agent_done})")

        if app_spec.save_shortcut:
            try:
                save_result = auto_save_app(
                    sandbox,
                    app_name,
                    app_spec.save_shortcut,
                    save_window_name=app_spec.save_window_name,
                )
                if save_result["ok"]:
                    print(f"  Auto-save: {save_result['message']}")
                else:
                    print(f"  Auto-save warning: {save_result['message']}")
                    if save_result["stderr"]:
                        print(f"  Auto-save stderr: {save_result['stderr']}")
            except Exception as exc:
                print(f"  Auto-save failed: {exc}")

        try:
            final_screenshot = sandbox.screenshot()
            screenshots_dir = traj_dir / "screenshots"
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            with open(screenshots_dir / "final_before_verify.png", "wb") as handle:
                handle.write(final_screenshot)
        except Exception:
            pass

        print("  Verifying...")
        passed, total, details = verify_task(
            sandbox,
            app_name,
            task["verification"],
            trajectory=trajectory,
            traj_dir=traj_dir,
        )

        for detail in details:
            if detail is None:
                continue
            status = "PASS" if detail["passed"] else "FAIL"
            command = detail["command"]
            if detail.get("judge") == "llm":
                reason = detail.get("reason", "")
                print(f"    {status}  [LLM] {detail.get('description', command)} — {reason}")
            elif "key" in detail:
                print(
                    f"    {status}  {command} -> {detail['key']}={detail['actual']} "
                    f"(expected {detail['expected']})"
                )
            else:
                print(f"    {status}  {detail.get('description', command)}")

        try:
            with open(traj_dir / "screenshots" / "final_after_verify.png", "wb") as handle:
                handle.write(sandbox.screenshot())
        except Exception:
            pass

        elapsed = time.time() - start_time
        reward = passed / total if total > 0 else 0.0
        print(f"  Result: {passed}/{total} — reward={reward:.2f} ({elapsed:.0f}s)")

        result = {
            "task_id": task_id,
            "app": app_name,
            "model": model_name,
            "task": task_text,
            "env_backend": env_backend,
            "agent_done": agent_done,
            "agent_steps": steps,
            "checks_passed": passed,
            "checks_total": total,
            "reward": reward,
            "elapsed_seconds": round(elapsed, 1),
            "stream_url": stream_url,
            "timestamp": datetime.now().isoformat(),
        }

        traj_data = {**result, "verification_details": details, "trajectory": trajectory}
        with open(traj_dir / "trajectory.json", "w") as handle:
            json.dump(traj_data, handle, indent=2, default=str)

        if keep_alive:
            print(f"\n  Desktop: {stream_url}")
            input("  Press Enter to kill sandbox...")

        return result

    except Exception as exc:
        elapsed = time.time() - start_time
        print(f"  ERROR: {exc}")
        traceback.print_exc()
        result = {
            "task_id": task_id,
            "app": app_name,
            "model": model_name,
            "task": task_text,
            "env_backend": env_backend,
            "agent_done": False,
            "agent_steps": 0,
            "checks_passed": 0,
            "checks_total": len(task.get("verification", [])),
            "reward": 0.0,
            "elapsed_seconds": round(elapsed, 1),
            "error": str(exc),
            "timestamp": datetime.now().isoformat(),
        }
        with open(traj_dir / "trajectory.json", "w") as handle:
            json.dump(result, handle, indent=2, default=str)
        return result

    finally:
        if sandbox:
            try:
                sandbox.kill()
            except Exception as exc:
                print(f"  WARNING: failed to kill sandbox for {task_id}: {exc}")
