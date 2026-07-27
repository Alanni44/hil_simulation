"""Development-only core process launcher.

Production deployment is deliberately implemented through systemd from
``ws_server``; isolating this helper makes accidental production Popen use
auditable.
"""
from __future__ import print_function
import os
import subprocess


def start(executable, runtime_log):
    environment = dict(os.environ)
    environment['HIL_ALLOW_NONRT'] = '1'
    return subprocess.Popen([executable], stdout=runtime_log, stderr=subprocess.STDOUT,
                            close_fds=True, env=environment)
