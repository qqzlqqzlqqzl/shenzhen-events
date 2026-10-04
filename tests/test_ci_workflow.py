"""Offline workflow gates. All synthetic fixtures are retained, never cleaned."""
import os
import json
import sys
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SUITES = '''taxonomy_browser multiday_browser calendar_browser review_district_browser
review_filter_context_browser review_personal_browser review_feedback_state_browser
review_planning_browser review_decisions_browser review_session_boundary_browser
review_recovery_browser feedback_browser review_browser coverage_browser
refresh_races_browser storage_resilience_browser owner_navigation_browser
readability_browser mobile_overlays_browser eefocus_safety_browser'''.split()


class WorkflowContract(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='radar-ci-contract-retained-'))
        (self.root / 'scripts').mkdir()
        (self.root / 'tests').mkdir()
        (self.root / 'runner-temp').mkdir()
        for name in ('run_browser_matrix.sh', 'prepare_ci_artifacts.sh'):
            shutil.copyfile(ROOT / 'scripts' / name, self.root / 'scripts' / name)
        for name in SUITES:
            (self.root / 'tests' / (name + '.py')).write_text('# Synthetic suite sentinel\n')
        self.python = self.root / 'synthetic-python'
        self.python.write_text('''#!/usr/bin/env bash
printf '%s\n' "$1" >> "$MATRIX_CALLS"
if [[ "$1" == *"${MATRIX_SLEEP:-never-sleep}"* ]]; then sleep 3; fi
if [[ "$1" == *"${MATRIX_FAIL:-never-fail}"* ]]; then exit 9; fi
printf 'synthetic fixture completed: %s\n' "$1"
''')
        self.python.chmod(0o700)
        self.env = dict(os.environ, RUNNER_TEMP=str(self.root / 'runner-temp'),
                        RADAR_TEST_PYTHON=str(self.python),
                        RADAR_BROWSER_SUITE_TIMEOUT='5',
                        MATRIX_CALLS=str(self.root / 'calls.txt'))

    def run_script(self, name):
        return subprocess.run(['timeout', '25s', 'bash', str(self.root / 'scripts' / name)],
                              env=self.env, capture_output=True, text=True, timeout=30)

    def rows(self):
        return [line.split('\t') for line in
                (self.root / 'artifacts/ci/browser-matrix.tsv').read_text().splitlines()[1:]]

    def test_all_twenty_suites_are_required_and_observed(self):
        result = self.run_script('run_browser_matrix.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(SUITES), 20)
        self.assertEqual([row[0] for row in self.rows()], SUITES)
        self.assertTrue(all(row[1:] == ['passed', '0'] for row in self.rows()))
        self.assertEqual(len((self.root / 'calls.txt').read_text().splitlines()), 20)

    def test_missing_suite_fails_closed_and_later_suites_still_run(self):
        original = self.root / 'tests' / (SUITES[3] + '.py')
        original.rename(original.with_suffix('.py.retained'))
        result = self.run_script('run_browser_matrix.sh')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.rows()[3], [SUITES[3], 'failed-missing-suite', '66'])
        self.assertEqual(self.rows()[-1], [SUITES[-1], 'passed', '0'])
        self.assertEqual(len((self.root / 'calls.txt').read_text().splitlines()), 19)

    def test_suite_failure_cannot_be_masked_by_tee(self):
        self.env['MATRIX_FAIL'] = SUITES[0]
        result = self.run_script('run_browser_matrix.sh')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.rows()[0], [SUITES[0], 'failed', '9'])
        self.assertEqual(self.rows()[-1], [SUITES[-1], 'passed', '0'])

    def test_timeout_fails_and_preserves_remaining_suite_count(self):
        self.env.update(MATRIX_SLEEP=SUITES[0], RADAR_BROWSER_SUITE_TIMEOUT='1')
        result = self.run_script('run_browser_matrix.sh')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.rows()[0], [SUITES[0], 'failed', '124'])
        self.assertEqual(len(self.rows()), 20)
        self.assertEqual(self.rows()[-1][1], 'passed')

    def test_existing_matrix_is_not_overwritten(self):
        self.assertEqual(self.run_script('run_browser_matrix.sh').returncode, 0)
        original = (self.root / 'artifacts/ci/browser-matrix.tsv').read_bytes()
        result = self.run_script('run_browser_matrix.sh')
        self.assertEqual(result.returncode, 73)
        self.assertEqual((self.root / 'artifacts/ci/browser-matrix.tsv').read_bytes(), original)

    def test_existing_suite_log_is_not_overwritten(self):
        out = self.root / 'artifacts/ci'
        out.mkdir(parents=True)
        sentinel = out / (SUITES[0] + '.log')
        sentinel.write_bytes(b'original evidence\n')
        self.assertEqual(self.run_script('run_browser_matrix.sh').returncode, 1)
        self.assertEqual(sentinel.read_bytes(), b'original evidence\n')
        self.assertEqual(self.rows()[0][1], 'blocked-existing-log')

    def test_old_artifacts_are_retained_outside_new_upload(self):
        old = self.root / 'artifacts/historical'
        old.mkdir(parents=True)
        (old / 'sentinel.txt').write_bytes(b'historical bytes\n')
        result = self.run_script('prepare_ci_artifacts.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list((self.root / 'artifacts').iterdir()), [self.root / 'artifacts/ci'])
        retained = list((self.root / 'runner-temp').glob('events-retained.*/artifacts/historical/sentinel.txt'))
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0].read_bytes(), b'historical bytes\n')

    def test_python_cleanup_is_retained_and_directory_semantics_stay_strict(self):
        env = dict(self.env, RADAR_RETAIN_TEST_FILES='1',
                   RADAR_TEST_RETENTION_ROOT=str(self.root),
                   RADAR_TEST_WORKSPACE=str(self.root),
                   PYTHONPATH=str(ROOT / 'tests/ci_retention'))
        code = r"""
import json, os, pathlib, shutil, tempfile
root=pathlib.Path(os.environ['RADAR_TEST_RETENTION_ROOT'])
a=root/'file.txt';a.write_text('retained file');os.unlink(a)
b=root/'folder';b.mkdir();(b/'inside.txt').write_text('retained folder');shutil.rmtree(b)
c=root/'empty';c.mkdir();os.rmdir(c)
d=root/'nonempty';d.mkdir();(d/'inside.txt').write_text('unchanged')
try:os.rmdir(d)
except OSError:pass
else:raise AssertionError('nonempty rmdir must fail')
with tempfile.TemporaryDirectory(dir=root) as temp:
    (pathlib.Path(temp)/'inside.txt').write_text('retained temporary')
kept=list((root/'retained-test-cleanup').iterdir())
assert len(kept)==4, kept
assert (d/'inside.txt').read_text()=='unchanged'
assert any(p.is_file() and p.read_text()=='retained file' for p in kept)
assert any(p.is_dir() and (p/'inside.txt').is_file() and (p/'inside.txt').read_text()=='retained temporary' for p in kept)
print(json.dumps({'retained':len(kept),'nonempty_rmdir':'refused'}))
"""
        result = subprocess.run(['timeout', '15s', sys.executable, '-c', code],
                                env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['retained'], 4)

    def test_rmtree_rejects_regular_file_without_moving_it(self):
        file = self.root / 'regular-file.txt'
        file.write_text('retained sentinel bytes\n')
        env = dict(self.env, RADAR_RETAIN_TEST_FILES='1',
                   RADAR_TEST_RETENTION_ROOT=str(self.root),
                   RADAR_TEST_WORKSPACE=str(self.root),
                   SLOT5_NEGATIVE_FILE=str(file),
                   PYTHONPATH=str(ROOT / 'tests/ci_retention'))
        code = """
import shutil,os
from pathlib import Path
p=Path(os.environ["SLOT5_NEGATIVE_FILE"])
try:
 shutil.rmtree(p)
except NotADirectoryError:
 assert p.read_text()=="retained sentinel bytes\\n"
 print("PASS: file rejected and unchanged")
else:
 print("FAIL: rmtree accepted a regular file; baseline API requires NotADirectoryError")
 raise SystemExit(37)
"""
        result = subprocess.run(['timeout', '15s', sys.executable, '-c', code],
                                env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(file.read_text(), 'retained sentinel bytes\n')

    def test_retention_invalid_configuration_fails_before_user_code(self):
        env = dict(self.env, RADAR_RETAIN_TEST_FILES='1',
                   RADAR_TEST_RETENTION_ROOT='/', RADAR_TEST_WORKSPACE=str(self.root),
                   PYTHONPATH=str(ROOT / 'tests/ci_retention'))
        result = subprocess.run(['timeout', '15s', sys.executable, '-c', "print('must not run')"],
                                env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 78)
        self.assertNotIn('must not run', result.stdout)

    def test_workflow_enables_retention_and_fail_closed_runner(self):
        workflow = (ROOT / '.github/workflows/validate-events.yml').read_text()
        self.assertIn('scripts/prepare_ci_artifacts.sh', workflow)
        self.assertIn('scripts/run_browser_matrix.sh', workflow)
        self.assertIn('RADAR_RETAIN_TEST_FILES=1', workflow)
        self.assertIn('tests/ci_retention', workflow)
        self.assertNotIn('rm -rf artifacts', workflow)
        self.assertNotIn('if [ -f "tests/$suite.py" ]', workflow)


if __name__ == '__main__':
    unittest.main()
