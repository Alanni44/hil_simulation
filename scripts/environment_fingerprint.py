#!/usr/bin/env python3
"""Capture and verify the pinned Ubuntu HIL target environment."""
from __future__ import print_function

import argparse
import datetime
import hashlib
import json
import os
import platform
import re
import subprocess
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE_PATH = os.path.join(ROOT, 'config', 'target-toolchain.json')


def _read_json(path):
    with open(path, 'r') as source:
        return json.load(source)


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _os_release(path='/etc/os-release'):
    values = {}
    with open(path, 'r') as source:
        for raw_line in source:
            line = raw_line.strip()
            if not line or '=' not in line:
                continue
            key, value = line.split('=', 1)
            values[key] = value.strip().strip('"')
    return values


def _command(arguments):
    return subprocess.check_output(
        arguments, stderr=subprocess.STDOUT,
        universal_newlines=True).strip()


def _matlab_version(executable):
    marker = 'HIL_MATLAB_VERSION:'
    output = _command([
        executable, '-nodisplay', '-nosplash', '-nodesktop', '-r',
        "fprintf('{}%s|%s\\n',version,version('-release'));exit(0);".format(
            marker)])
    matches = [line.strip()[len(marker):]
               for line in output.splitlines()
               if line.strip().startswith(marker)]
    if len(matches) != 1 or '|' not in matches[0]:
        raise RuntimeError('could not read MATLAB version from {}'.format(
            executable))
    version, release = matches[0].split('|', 1)
    # MATLAB's ``version`` includes the release in parentheses on R2018b;
    # store the numeric product version separately for exact comparison.
    version = version.split(' ', 1)[0]
    return {'version': version, 'release': 'R' + release,
            'executable': os.path.realpath(executable)}


def _python_dependencies(requirements_path):
    dependencies = {}
    with open(requirements_path, 'r') as source:
        for line_number, raw_line in enumerate(source, 1):
            line = raw_line.strip()
            if not line or line.startswith('#'):
                continue
            match = re.match(r'^([A-Za-z0-9_.-]+)==([^\s]+)$', line)
            if not match:
                raise RuntimeError(
                    'requirement line {} is not exactly pinned: {}'.format(
                        line_number, line))
            dependencies[match.group(1).lower()] = {
                'required': match.group(2), 'installed': None}

    for name in dependencies:
        try:
            import pkg_resources
            dependencies[name]['installed'] = (
                pkg_resources.get_distribution(name).version)
        except Exception:
            dependencies[name]['installed'] = None
    return dependencies


def capture_environment(baseline_path=BASELINE_PATH):
    baseline = _read_json(baseline_path)
    requirements_path = os.path.join(
        ROOT, baseline['python']['requirements'])
    matlab = _matlab_version(baseline['matlab']['executable'])
    release = _os_release()
    return {
        'captured_utc': datetime.datetime.utcnow().isoformat() + 'Z',
        'baseline_path': os.path.relpath(baseline_path, ROOT).replace(os.sep, '/'),
        'baseline_sha256': _sha256(baseline_path),
        'operating_system': {
            'id': release.get('ID'),
            'version_id': release.get('VERSION_ID'),
            'pretty_name': release.get('PRETTY_NAME')},
        'kernel': {
            'release': platform.release(),
            'version': platform.version(),
            'machine': platform.machine(),
            'preempt_rt': 'PREEMPT_RT' in platform.version().upper()},
        'python': {
            'version': platform.python_version(),
            'executable': os.path.realpath(sys.executable),
            'requirements_path': os.path.relpath(
                requirements_path, ROOT).replace(os.sep, '/'),
            'requirements_sha256': _sha256(requirements_path),
            'dependencies': _python_dependencies(requirements_path)},
        'gcc': {
            'version': _command(['gcc', '-dumpfullversion', '-dumpversion']),
            'banner': _command(['gcc', '--version']).splitlines()[0]},
        'matlab': matlab,
    }


def validate_environment(facts, baseline_path=BASELINE_PATH):
    baseline = _read_json(baseline_path)
    errors = []

    def require(name, actual, expected):
        if actual != expected:
            errors.append('{} must be {!r}, got {!r}'.format(
                name, expected, actual))

    require('operating_system.id', facts['operating_system']['id'],
            baseline['operating_system']['id'])
    require('operating_system.version_id',
            facts['operating_system']['version_id'],
            baseline['operating_system']['version_id'])
    require('kernel.release', facts['kernel']['release'],
            baseline['kernel']['release'])
    if (baseline['kernel'].get('requires_preempt_rt') and
            not facts['kernel']['preempt_rt']):
        errors.append('kernel must report PREEMPT_RT')
    require('python.version', facts['python']['version'],
            baseline['python']['version'])
    require('gcc.version', facts['gcc']['version'], baseline['gcc']['version'])
    require('matlab.release', facts['matlab']['release'],
            baseline['matlab']['release'])
    require('matlab.version', facts['matlab']['version'],
            baseline['matlab']['version'])
    require('matlab.executable', facts['matlab']['executable'],
            os.path.realpath(baseline['matlab']['executable']))
    for name, dependency in facts['python']['dependencies'].items():
        require('python.dependencies.{}'.format(name),
                dependency['installed'], dependency['required'])
    return errors


def verified_environment(baseline_path=BASELINE_PATH):
    facts = capture_environment(baseline_path)
    errors = validate_environment(facts, baseline_path)
    facts['validation'] = {'passed': not errors, 'errors': errors}
    if errors:
        raise RuntimeError('; '.join(errors))
    return facts


def write_json(path, value):
    with open(path, 'w') as output:
        json.dump(value, output, indent=2, sort_keys=True)
        output.write('\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    facts = capture_environment()
    errors = validate_environment(facts)
    facts['validation'] = {'passed': not errors, 'errors': errors}
    if args.output:
        write_json(args.output, facts)
    else:
        print(json.dumps(facts, indent=2, sort_keys=True))
    if args.verify and errors:
        for error in errors:
            print('[environment mismatch] {}'.format(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
