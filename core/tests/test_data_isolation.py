"""Tests must never read or write the live databases, or start background jobs."""
import json
import os
import subprocess
import sys

import paths


def test_data_dir_is_a_temp_dir():
    core_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert paths.DATA_DIR == os.environ["AIPAYGEN_DATA_DIR"]
    assert not paths.DATA_DIR.startswith(core_dir)


def test_module_databases_live_in_data_dir(tmp_path):
    # Fresh interpreter: other tests repoint DB paths at their own temp files.
    probe = (
        "import json, api_keys, crypto_deposits, settlement, seller_marketplace, agent_memory, trading_engine\n"
        "print(json.dumps([api_keys.DB_PATH, crypto_deposits.DB_PATH, settlement.DB_PATH,"
        " seller_marketplace._DB_PATH, agent_memory.DB_PATH, trading_engine.DB_PATH]))\n"
    )
    core_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path), "AIPAYGEN_DATA_DIR": str(tmp_path)}
    out = subprocess.run([sys.executable, "-c", probe], cwd=core_dir, env=env,
                         capture_output=True, text=True, timeout=120, check=True).stdout
    for path in json.loads(out.strip().splitlines()[-1]):
        assert os.path.dirname(os.path.abspath(path)) == str(tmp_path), path


def test_importing_app_does_not_start_jobs():
    import app
    assert not app._scheduler.running


def test_static_assets_still_come_from_the_code_dir():
    # DATA_DIR is a temp dir in tests; fonts ship with the code, not the data volume.
    import app
    r = app.app.test_client().get("/assets/fonts/IBMPlexMono_100Thin.119294763c9a5ce5b6762fd8df1fb305.ttf")
    assert r.status_code == 200 and len(r.data) > 1000
