"""Dependency-light test runner: uses the existing Forge Python, no pytest required."""
import argparse
import importlib.util
import inspect
import json
from pathlib import Path
import sys
import unittest
import time
import hashlib

HERE = Path(__file__).resolve().parent

def run(build):
    sys.path.insert(0, str(build))
    # Support source changes between runs, including core and UI modules.
    for name in list(sys.modules):
        if name.startswith(('lumex_', 'lum_test_')):
            del sys.modules[name]
    suite = unittest.TestSuite()
    for index, path in enumerate(sorted(HERE.glob('test_*.py'))):
        spec = importlib.util.spec_from_file_location(f'lum_test_{index}', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
        for name, fn in inspect.getmembers(module, inspect.isfunction):
            if name.startswith('test_'):
                suite.addTest(unittest.FunctionTestCase(fn))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return {'passed': result.wasSuccessful(), 'tests': result.testsRun,
            'failures': len(result.failures), 'errors': len(result.errors)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, default=HERE.parent)
    parser.add_argument('--report', type=Path, default=Path('lumex-test-report.json'))
    parser.add_argument('--watch', action='store_true')
    args = parser.parse_args(); previous = None
    while True:
        fingerprint = hashlib.sha256(b''.join(p.read_bytes() for p in sorted(args.build.rglob('*.py')))).hexdigest()
        if fingerprint != previous:
            result = run(args.build.resolve()); result['fingerprint'] = fingerprint
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(result, indent=2))
            print(json.dumps(result), flush=True)
            if not args.watch:return 0 if result['passed'] else 1
            previous = fingerprint
        time.sleep(1)

if __name__ == '__main__':
    try:raise SystemExit(main())
    except KeyboardInterrupt:raise SystemExit(130)
