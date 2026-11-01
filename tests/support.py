import json
import os
import shutil
import subprocess
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "tiny_package"
GUARD = Path(__file__).parent / "offline_guard"
LOCAL = json.dumps({"local": str(FIXTURE.resolve())})


def offline_environment(root: Path) -> dict:
    return {
        "DBT_INVOKE_TEST_OFFLINE": "1",
        "DBT_INVOKE_TEST_ATTEMPTS": str(root / "offline-attempts.txt"),
        "DBT_INVOKE_CACHE_DIR": str(root / "cache"),
        "PYTHONPATH": os.pathsep.join(filter(None, [str(GUARD.resolve()), os.environ.get("PYTHONPATH")])),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }


def git_package(root: Path) -> str:
    checkout = root / "git-fixture"
    shutil.copytree(FIXTURE, checkout)
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    for command in (
        ["init", "-b", "main"], ["config", "user.name", "Fixture"],
        ["config", "user.email", "fixture@example.test"], ["add", "."],
        ["commit", "-m", "Fixture macros"],
    ):
        subprocess.run(["git", *command], cwd=checkout, env=env, check=True, capture_output=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, env=env).decode().strip()
    return json.dumps({"git": checkout.as_uri(), "revision": revision})
