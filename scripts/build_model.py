#!/usr/bin/env python3
"""Submit a local immutable package to the HIL build executor."""
from __future__ import print_function
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'python_services'))
from shared.model_package import package_sha256  # noqa
import ws_server  # noqa

parser = argparse.ArgumentParser(description='Build or deploy a verified local HIL package')
parser.add_argument('package_path')
parser.add_argument('--deploy', action='store_true')
parser.add_argument('--request-id', default='local-build')
args = parser.parse_args()
manifest = json.load(open(os.path.join(args.package_path, 'package_manifest.json')))
request = {'request_id': args.request_id, 'operation': 'deploy' if args.deploy else 'build',
           'model_ref': manifest['model_ref'], 'model_revision_ref': manifest['model_revision_ref'],
           'package_path': os.path.abspath(args.package_path), 'package_sha256': package_sha256(args.package_path)}
print(json.dumps(ws_server._build_or_deploy(request), indent=2, sort_keys=True))
