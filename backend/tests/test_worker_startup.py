"""
Worker startup smoke test.

Imports app.celery in a fresh subprocess with no prior django.setup(), exactly
mirroring the 'celery -A app.celery worker' startup sequence. Any module-level
crash (AppRegistryNotReady, import errors, missing env vars) is caught here.

This test does NOT use @pytest.mark.django_db — Django must not be initialized
by pytest before the subprocess runs.
"""

import os
import subprocess
import sys


def test_celery_module_imports_cleanly():
    """
    Verify app.celery can be imported in a fresh Python subprocess.

    If this fails, 'celery -A app.celery worker' will also fail on startup,
    leaving all dispatched messages stuck in QUEUED indefinitely.
    """
    result = subprocess.run(
        [sys.executable, '-c', 'import app.celery; print("ok")'],
        cwd='/app',
        env={**os.environ, 'DJANGO_SETTINGS_MODULE': 'app.settings'},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"app.celery failed to import — worker startup would crash:\n{result.stderr}"
    )
