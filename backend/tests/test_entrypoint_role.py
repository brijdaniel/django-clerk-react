"""
Role-resolution tests for backend/entrypoint.sh.

The container image ships a single CMD (["api"]); the three ACA container apps
(api/worker/beat) are distinguished ONLY by the CONTAINER_ROLE env var, with the
first CLI arg as a fallback. The precedence rules are subtle:

  - first arg is a known role (api|worker|beat) → CONTAINER_ROLE wins, else the arg
  - first arg is empty                          → CONTAINER_ROLE wins, else "api"
  - first arg is anything else (pytest, sh, …)  → run it verbatim ("__command__")

These tests drive entrypoint.sh as a subprocess (mirroring test_worker_startup.py)
and assert which long-running process it would exec into, WITHOUT launching
gunicorn/celery. A shadowing PATH dir provides a stub `uv` (and stub arbitrary
commands) that echoes a recognisable marker and exits 0 instead of running the
real binary. Because every `uv`/command invocation is the stub:

  - the DB-wait loop (`uv run python -c ...`) succeeds immediately,
  - the api migrate-check (`uv run python manage.py migrate --check`) returns 0
    ("No pending migrations"),
  - the final `exec uv run python -m {gunicorn,celery} ...` execs the stub, which
    prints UV-EXEC + its argv,
  - the `exec "$@"` arbitrary-command branch execs the stub command, which prints
    CMD-EXEC + its argv.

No @pytest.mark.django_db — this is a pure shell-behaviour test.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ENTRYPOINT = Path(__file__).resolve().parent.parent / 'entrypoint.sh'


# A stub binary placed earlier on PATH than the real `uv`. It echoes a marker so
# the test can see what entrypoint.sh tried to exec, then exits 0 so the DB-wait
# loop and migrate-check both "succeed".
_UV_STUB = """#!/bin/bash
echo "UV-EXEC: $*"
exit 0
"""

# Stub for the arbitrary-command branch (exec "$@"). Named per-test.
_CMD_STUB = """#!/bin/bash
echo "CMD-EXEC: $0 $*"
exit 0
"""


def _run_entrypoint(tmp_path, *, container_role=None, args=(), extra_stubs=()):
    """Run entrypoint.sh with a shadowing PATH and return its stdout.

    container_role: value for CONTAINER_ROLE (None → unset).
    args:           argv passed to entrypoint.sh.
    extra_stubs:    names of extra commands to stub (for the arbitrary-command case).
    """
    bindir = tmp_path / 'bin'
    bindir.mkdir(exist_ok=True)

    uv = bindir / 'uv'
    uv.write_text(_UV_STUB)
    uv.chmod(0o755)

    for name in extra_stubs:
        stub = bindir / name
        stub.write_text(_CMD_STUB)
        stub.chmod(0o755)

    env = {
        # Shadow the real uv/commands first on PATH.
        'PATH': f'{bindir}:{os.environ.get("PATH", "")}',
        'DJANGO_SETTINGS_MODULE': 'app.settings',
    }
    if container_role is not None:
        env['CONTAINER_ROLE'] = container_role

    result = subprocess.run(
        ['bash', str(ENTRYPOINT), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f'entrypoint exited {result.returncode}:\n{result.stderr}'
    return result.stdout


# ---------------------------------------------------------------------------
# Role resolution: CONTAINER_ROLE x first-arg
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('container_role', ['api', 'worker', 'beat'])
@pytest.mark.parametrize('first_arg', ['api', 'worker', 'beat', ''])
def test_known_role_arg_and_empty_arg_defer_to_container_role(tmp_path, container_role, first_arg):
    """For known-role and empty first args, CONTAINER_ROLE wins and selects the process."""
    args = () if first_arg == '' else (first_arg,)
    out = _run_entrypoint(tmp_path, container_role=container_role, args=args)

    if container_role == 'api':
        assert 'gunicorn' in out
        assert 'celery' not in out
    elif container_role == 'worker':
        assert 'celery -A app.celery worker' in out
    elif container_role == 'beat':
        assert 'celery -A app.celery beat' in out


@pytest.mark.parametrize('first_arg,expected', [
    ('api', 'gunicorn'),
    ('worker', 'celery -A app.celery worker'),
    ('beat', 'celery -A app.celery beat'),
    ('', 'gunicorn'),  # empty arg + no CONTAINER_ROLE defaults to api
])
def test_first_arg_used_when_container_role_unset(tmp_path, first_arg, expected):
    """With CONTAINER_ROLE unset, the first arg (or the api default) selects the process."""
    args = () if first_arg == '' else (first_arg,)
    out = _run_entrypoint(tmp_path, container_role=None, args=args)
    assert expected in out


# ---------------------------------------------------------------------------
# Arbitrary command: first arg is NOT a known role
# ---------------------------------------------------------------------------

def test_pytest_arg_is_run_verbatim_not_hijacked(tmp_path):
    """`entrypoint.sh pytest ...` execs pytest as-is, even with CONTAINER_ROLE=worker.

    This guards `docker compose run backend ... pytest` against being hijacked
    into starting a celery worker.
    """
    out = _run_entrypoint(
        tmp_path,
        container_role='worker',  # must be ignored for an unknown command
        args=('pytest', '-q'),
        extra_stubs=('pytest',),
    )
    assert 'CMD-EXEC' in out
    assert 'pytest' in out
    assert 'gunicorn' not in out
    assert 'celery' not in out


def test_arbitrary_command_ignores_container_role_api(tmp_path):
    """Even with CONTAINER_ROLE=api, a non-role first arg is run verbatim."""
    out = _run_entrypoint(
        tmp_path,
        container_role='api',
        args=('printenv',),
        extra_stubs=('printenv',),
    )
    assert 'CMD-EXEC' in out
    assert 'printenv' in out
    assert 'gunicorn' not in out
