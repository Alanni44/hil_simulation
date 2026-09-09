#!/usr/bin/env python3
"""Create a verified ``hil_model_package.zip`` for a GitLab Release.

The HIL service deliberately accepts only a fully declared model package.  This
tool assembles that package from an approved top-level SLX, its explicit
contract, and declared dependency files; validates it with the same validator
used by the service; then writes a ZIP containing exactly one package root.

It never uploads to GitLab and it does not alter its input files.
"""
from __future__ import print_function

import argparse
import json
import os
import shutil
import sys
import tempfile
import zipfile


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'python_services'))
from shared.model_package import (  # noqa: E402
    DEPENDENCY_KINDS, PackageError, package_sha256, sha256_file, validate_package,
)


def _regular_file(path, label):
    path = os.path.abspath(path)
    if not os.path.isfile(path) or os.path.islink(path):
        raise PackageError('{} must be a regular file: {}'.format(label, path))
    return path


def _dependency_spec(value):
    try:
        kind, path = value.split(':', 1)
    except ValueError:
        raise argparse.ArgumentTypeError('dependency must be KIND:PATH')
    if kind not in DEPENDENCY_KINDS:
        raise argparse.ArgumentTypeError(
            'dependency kind must be one of {}'.format(', '.join(DEPENDENCY_KINDS)))
    if not path:
        raise argparse.ArgumentTypeError('dependency path cannot be empty')
    return kind, path


def _copy_file(source, destination):
    if os.path.exists(destination):
        raise PackageError('two package files would have the same name: {}'.format(destination))
    shutil.copyfile(source, destination)


def create_release_package(model_path, contract_path, model_ref, model_revision_ref,
                           matlab_version, dependencies, output_path):
    """Write a validated ZIP and return its package/package hashes.

    ``dependencies`` is an iterable of ``(kind, source_path)`` pairs.
    """
    model_path = _regular_file(model_path, 'model')
    contract_path = _regular_file(contract_path, 'contract')
    model_name, extension = os.path.splitext(os.path.basename(model_path))
    if extension.lower() != '.slx' or not model_name:
        raise PackageError('model must have a non-empty .slx filename')
    for value, label in ((model_ref, 'model_ref'),
                         (model_revision_ref, 'model_revision_ref'),
                         (matlab_version, 'matlab_version')):
        if not isinstance(value, str) or not value:
            raise PackageError('{} must be a non-empty string'.format(label))
    output_path = os.path.abspath(output_path)
    output_parent = os.path.dirname(output_path)
    if not os.path.isdir(output_parent):
        raise PackageError('output directory does not exist: {}'.format(output_parent))

    with tempfile.TemporaryDirectory(prefix='hil-release-package-') as temporary:
        package_root = os.path.join(temporary, model_name)
        os.mkdir(package_root)
        _copy_file(model_path, os.path.join(package_root, os.path.basename(model_path)))
        _copy_file(contract_path, os.path.join(package_root, 'hil_contract.json'))

        dependency_records = []
        if dependencies:
            dependency_root = os.path.join(package_root, 'dependencies')
            os.mkdir(dependency_root)
            for kind, source_path in dependencies:
                source_path = _regular_file(source_path, 'dependency')
                filename = os.path.basename(source_path)
                destination = os.path.join(dependency_root, filename)
                _copy_file(source_path, destination)
                dependency_records.append({'path': 'dependencies/' + filename, 'kind': kind})

        files = {}
        for base, _, names in os.walk(package_root):
            for filename in sorted(names):
                full_path = os.path.join(base, filename)
                relative = os.path.relpath(full_path, package_root).replace(os.sep, '/')
                files[relative] = sha256_file(full_path)
        manifest = {
            'model_ref': model_ref,
            'model_revision_ref': model_revision_ref,
            'top_model': os.path.basename(model_path),
            'matlab_version': matlab_version,
            'files': files,
            'dependencies': dependency_records,
            'package_sha256': package_sha256(package_root),
        }
        manifest_path = os.path.join(package_root, 'package_manifest.json')
        with open(manifest_path, 'w') as output:
            json.dump(manifest, output, indent=2, sort_keys=True)
            output.write('\n')

        # Use the production validator before publishing the asset.  The
        # temporary directory is intentionally the controlled root here.
        checked = validate_package(package_root, temporary)
        temporary_zip = os.path.join(output_parent, '.hil-model-package-{}.tmp'.format(os.getpid()))
        try:
            with zipfile.ZipFile(temporary_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
                for base, _, names in os.walk(package_root):
                    for filename in sorted(names):
                        full_path = os.path.join(base, filename)
                        relative = os.path.relpath(full_path, temporary).replace(os.sep, '/')
                        archive.write(full_path, relative)
            os.replace(temporary_zip, output_path)
        finally:
            if os.path.exists(temporary_zip):
                os.unlink(temporary_zip)
    return {'output': output_path, 'package_sha256': checked['package_sha256'],
            'contract_sha256': checked['contract_sha256'], 'top_model': manifest['top_model']}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Create a verified HIL GitLab Release package')
    parser.add_argument('--model', required=True, help='approved top-level .slx file')
    parser.add_argument('--contract', required=True, help='matching hil_contract.json')
    parser.add_argument('--model-ref', required=True, help='immutable external model identifier')
    parser.add_argument('--model-revision-ref', required=True, help='immutable revision identifier')
    parser.add_argument('--matlab-version', default='R2018b')
    parser.add_argument('--dependency', action='append', type=_dependency_spec, default=[],
                        metavar='KIND:PATH',
                        help='repeat for each dependency; kind is model_ref, data_dictionary, '
                             'init_script, mat_data, or custom_code')
    parser.add_argument('--output', required=True, help='output ZIP path (normally hil_model_package.zip)')
    args = parser.parse_args(argv)
    try:
        result = create_release_package(args.model, args.contract, args.model_ref,
                                        args.model_revision_ref, args.matlab_version,
                                        args.dependency, args.output)
    except (IOError, OSError, PackageError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
