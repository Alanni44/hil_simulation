#!/usr/bin/env python3
"""Build a local SLX into the immutable HIL model registry.

This is the operator-facing counterpart to the authenticated remote
``load_model`` command.  It never downloads a model and therefore remains
usable when remote model administration is intentionally disabled.
"""
from __future__ import print_function

import argparse
import json
import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'python_services'))

from ws_server import build_model_from_slx  # noqa: E402


def main():
    parser = argparse.ArgumentParser(
        description='Archive, build, checksum, and activate a local HIL SLX model.')
    parser.add_argument('slx_path', help='path to the source .slx file')
    parser.add_argument('model_name', help='model name: [A-Za-z][A-Za-z0-9_]{0,63}')
    args = parser.parse_args()

    success, message, executable, build_id = build_model_from_slx(
        os.path.abspath(args.slx_path), args.model_name)
    result = {
        'status': 'success' if success else 'error',
        'message': message,
        'model_name': args.model_name,
        'build_id': build_id,
        'executable': executable,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
