#!/usr/bin/env python3
"""Run the complete week-one baseline acceptance and assemble its evidence."""
from __future__ import print_function

import datetime
import json
import os
import subprocess
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))
from environment_fingerprint import capture_environment, validate_environment  # noqa


def write_json(path, value):
    with open(path, 'w') as output:
        json.dump(value, output, indent=2, sort_keys=True)
        output.write('\n')


def git_output(*arguments):
    return subprocess.check_output(
        ['git'] + list(arguments), cwd=ROOT,
        universal_newlines=True).strip()


def stream_command(command, log_path, environment=None):
    with open(log_path, 'w') as log:
        process = subprocess.Popen(
            command, cwd=ROOT, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, universal_newlines=True, bufsize=1)
        for line in iter(process.stdout.readline, ''):
            sys.stdout.write(line)
            sys.stdout.flush()
            log.write(line)
            log.flush()
        process.stdout.close()
        return process.wait()


def load_json(path, default):
    try:
        with open(path, 'r') as source:
            return json.load(source)
    except (IOError, ValueError):
        return default


def finish(evidence, git_head, stage, exit_code, test_report, issues):
    result_path = os.path.join(evidence, 'result.json')
    result = load_json(result_path, {})
    integration_passed = result.get('status') == 'passed'
    passed = (exit_code == 0 and test_report.get('status') == 'passed'
              and integration_passed)
    if not passed and not issues:
        issues.append({
            'id': 'W1-{}'.format(stage.upper().replace('-', '_')),
            'severity': 'P0', 'stage': stage,
            'summary': 'week-one baseline acceptance failed',
            'exit_code': exit_code})
    result.update({
        'status': 'passed' if passed else 'failed',
        'git_head': git_head,
        'evidence_kind': 'week1-baseline',
        'completed_utc': datetime.datetime.utcnow().isoformat() + 'Z',
        'week1': {
            'stage': 'complete' if passed else stage,
            'unit_tests': test_report,
            'integration_status': 'passed' if integration_passed else 'failed',
            'issues_file': 'issues.json'}})
    write_json(os.path.join(evidence, 'test-report.json'), test_report)
    write_json(os.path.join(evidence, 'issues.json'), issues)
    write_json(result_path, result)
    return 0 if passed else 1


def main():
    if len(sys.argv) != 1:
        print('usage: {} (no arguments)'.format(sys.argv[0]), file=sys.stderr)
        return 2
    git_head = git_output('rev-parse', 'HEAD')
    dirty = git_output('status', '--porcelain')
    if dirty:
        print('[验收失败] 工作区不干净；拒绝生成当前 HEAD 验收证据',
              file=sys.stderr)
        return 2

    run_id = '{}-{}-week1-baseline'.format(
        datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ'),
        git_head[:12])
    evidence = os.path.join(ROOT, 'artifacts', 'acceptance', run_id)
    os.makedirs(evidence)
    issues = []
    test_report = {
        'status': 'not_run', 'git_head': git_head,
        'command': '{} -m unittest discover -s tests -v'.format(
            sys.executable)}

    print('[1/3] 捕获并校验固定目标环境')
    try:
        environment = capture_environment()
        environment_errors = validate_environment(environment)
        environment['validation'] = {
            'passed': not environment_errors, 'errors': environment_errors}
        write_json(os.path.join(evidence, 'environment.json'), environment)
    except Exception as exc:
        environment_errors = [str(exc)]
        write_json(os.path.join(evidence, 'environment.json'), {
            'validation': {'passed': False, 'errors': environment_errors}})
    if environment_errors:
        issues.extend({
            'id': 'W1-ENVIRONMENT', 'severity': 'P0',
            'stage': 'environment', 'summary': error}
            for error in environment_errors)
        return finish(evidence, git_head, 'environment', 1,
                      test_report, issues)

    print('[2/3] 运行全部 Python 单元测试')
    test_command = [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v']
    test_code = stream_command(
        test_command, os.path.join(evidence, 'unit-tests.log'),
        dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
    test_report.update({
        'status': 'passed' if test_code == 0 else 'failed',
        'exit_code': test_code, 'log': 'unit-tests.log'})
    if test_code != 0:
        return finish(evidence, git_head, 'unit-tests', test_code,
                      test_report, issues)

    print('[3/3] 运行 MATLAB ERT/GCC 与运行时合同验收')
    integration_environment = dict(
        os.environ, HIL_DEPLOY_MODE='development',
        HIL_SKIP_REALTIME_GATE='1',
        HIL_ACCEPTANCE_EVIDENCE_DIR=evidence)
    integration_code = stream_command(
        [sys.executable, 'scripts/accept_runtime_contract.py'],
        os.path.join(evidence, 'integration.log'),
        integration_environment)
    final_code = finish(
        evidence, git_head, 'integration', integration_code,
        test_report, issues)
    if final_code == 0:
        print('[验收通过] 第一周工程基线已恢复')
    else:
        print('[验收失败] 查看 {}'.format(
            os.path.join(evidence, 'result.json')), file=sys.stderr)
    print('证据目录：{}'.format(evidence))
    return final_code


if __name__ == '__main__':
    sys.exit(main())
