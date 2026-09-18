from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
PIP_WRAPPER = REPOSITORY_ROOT / "scripts" / "with-isolated-pypi.sh"


class PipIsolationTests(unittest.TestCase):
    def test_child_receives_only_approved_pip_environment(self):
        hostile_environment = {
            "PIP_CONFIG_FILE": "/tmp/hostile-pip.conf",
            "PIP_INDEX_URL": "https://hostile.invalid/simple",
            "PIP_EXTRA_INDEX_URL": "https://hostile-extra.invalid/simple",
            "PIP_FIND_LINKS": "/tmp/hostile-wheels",
            "PIP_CONSTRAINT": "/tmp/hostile-constraints.txt",
            "PIP_REQUIRE_VIRTUALENV": "true",
            "PIP_TRUSTED_HOST": "hostile.invalid",
            "PIP_NO_INDEX": "true",
            "PIP_TARGET": "/tmp/hostile-target",
            "PIP_USER": "true",
            "PIP_BAD-NAME": "hostile-invalid-name",
        }
        environment = os.environ.copy()
        environment.update(hostile_environment)

        result = subprocess.run(
            [
                str(PIP_WRAPPER),
                sys.executable,
                "-c",
                (
                    "import json, os; "
                    "print(json.dumps({key: value for key, value in os.environ.items() "
                    "if key.startswith('PIP_')}, sort_keys=True))"
                ),
            ],
            check=True,
            capture_output=True,
            env=environment,
            text=True,
        )

        self.assertEqual(
            json.loads(result.stdout),
            {
                "PIP_CONFIG_FILE": "/dev/null",
                "PIP_EXTRA_INDEX_URL": "",
                "PIP_INDEX_URL": "https://pypi.org/simple",
            },
        )


if __name__ == "__main__":
    unittest.main()
