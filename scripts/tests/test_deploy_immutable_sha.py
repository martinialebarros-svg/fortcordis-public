#!/usr/bin/env python3
"""Exercise deploy selection with Git/launcher doubles; no network or services."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]
PIN = "a" * 40
TIP = "b" * 40
LATER = "c" * 40
PREVIOUS = "d" * 40

GIT_DOUBLE = r'''
git() {
  printf '%s\n' "$*" >> "$TRACE"
  case "$1" in
    check-ref-format) return "${INVALID_BRANCH:-0}" ;;
    fetch)
      if [[ "$4" == "$PIN" && "${FAIL_PIN_FETCH:-0}" == 1 ]]; then return 1; fi
      if [[ "$4" == +refs/* && "${FAIL_BRANCH_FETCH:-0}" == 1 ]]; then return 1; fi
      return 0 ;;
    merge-base) return "${NOT_ANCESTOR:-0}" ;;
    rev-parse)
      if [[ "$2" == HEAD ]]; then cat "$FAKE_HEAD"; return; fi
      if [[ "$3" == "${PIN}^{commit}" ]]; then
        printf '%s\n' "${RESOLVED_PIN:-$PIN}"
      elif [[ "$3" == refs/remotes/* ]]; then cat "$FAKE_REMOTE"
      else return 98; fi ;;
    checkout)
      if [[ "${ADVANCE_ON_CHECKOUT:-0}" == 1 ]]; then
        printf '%s\n' "$LATER" > "$FAKE_REMOTE"
      fi
      return "${FAIL_CHECKOUT:-0}" ;;
    reset)
      [[ "${FAIL_RESET:-0}" != 1 ]] || return 1
      printf '%s\n' "${INSTALLED_OVERRIDE:-$3}" > "$FAKE_HEAD" ;;
    *) return 99 ;;
  esac
}
'''


def step_blocks(text, name):
    """Read a named step without a YAML dependency or evaluating expressions."""
    lines = text.splitlines()
    result = []
    for pos, line in enumerate(lines):
        if line.strip() != f"- name: {name}":
            continue
        indent = len(line) - len(line.lstrip())
        end = pos + 1
        while end < len(lines):
            if lines[end].strip() and len(lines[end]) - len(lines[end].lstrip()) <= indent:
                break
            end += 1
        result.append(lines[pos:end])
    return result


class ImmutableDeployShaTests(unittest.TestCase):
    def run_deploy_functions(self, commands="resolve_deploy_target\nupdate_deploy_code", **changes):
        with tempfile.TemporaryDirectory(prefix="deploy-sha-test-") as temp:
            folder = Path(temp)
            head, remote, trace, state = [folder / n for n in ("head", "remote", "trace", "state")]
            head.write_text(PREVIOUS + "\n")
            remote.write_text(TIP + "\n")
            env = dict(os.environ, APP_DIR=str(folder / "app"), BRANCH="main",
                       DEPLOY_SHA=PIN, DEPLOY_REF="refs/heads/main", PIN=PIN,
                       LATER=LATER, TRACE=str(trace), FAKE_HEAD=str(head),
                       FAKE_REMOTE=str(remote), STATE=str(state))
            # Isolate these tests from caller settings; every Git call is a double.
            for key in ("INVALID_BRANCH", "FAIL_PIN_FETCH", "FAIL_BRANCH_FETCH", "NOT_ANCESTOR",
                        "RESOLVED_PIN", "ADVANCE_ON_CHECKOUT", "FAIL_CHECKOUT", "FAIL_RESET",
                        "INSTALLED_OVERRIDE"):
                env.pop(key, None)
            env.update(changes)
            script = 'set -euo pipefail\nsource scripts/deploy_prod_vps.sh\n' + GIT_DOUBLE
            script += commands + '\nprintf "%s\\n" "$DEPLOY_TARGET_SHA" "$CODE_UPDATED" > "$STATE"\n'
            run = subprocess.run(["bash", "-c", script], cwd=ROOT, env=env, text=True,
                                 capture_output=True, timeout=10)
            return run, (trace.read_text().splitlines() if trace.exists() else []), head.read_text().strip(), (
                state.read_text().splitlines() if state.exists() else [])

    def test_branch_advance_does_not_replace_the_gated_sha(self):
        for branch in ("main", "stage"):
            with self.subTest(branch=branch):
                run, trace, head, state = self.run_deploy_functions(
                    BRANCH=branch, DEPLOY_REF=f"refs/heads/{branch}", ADVANCE_ON_CHECKOUT="1")
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(head, PIN)
                self.assertEqual(state, [PIN, "1"])
                self.assertIn(f"fetch --no-tags origin +refs/heads/{branch}:refs/remotes/origin/{branch}", trace)
                self.assertIn(f"fetch --no-tags origin {PIN}", trace)
                self.assertIn(f"merge-base --is-ancestor {PIN} refs/remotes/origin/{branch}", trace)
                self.assertIn(f"checkout {branch}", trace)
                self.assertIn(f"reset --hard {PIN}", trace)
                self.assertNotIn(f"reset --hard {TIP}", trace)
                self.assertNotIn(f"reset --hard {LATER}", trace)

    def test_invalid_context_aborts_before_any_remote_fetch_or_reset(self):
        for changes in ({"DEPLOY_SHA": ""}, {"DEPLOY_SHA": "abc123"},
                        {"DEPLOY_SHA": "z" * 40}, {"DEPLOY_REF": "refs/heads/stage"},
                        {"DEPLOY_REF": "refs/tags/main"}, {"INVALID_BRANCH": "1"}):
            with self.subTest(changes=changes):
                run, trace, head, _ = self.run_deploy_functions(**changes)
                self.assertNotEqual(run.returncode, 0)
                self.assertEqual(head, PREVIOUS)
                self.assertFalse(any(x.startswith(("fetch ", "checkout ", "reset ")) for x in trace))

    def test_unavailable_or_foreign_commit_never_falls_back_to_branch_tip(self):
        for changes in ({"FAIL_PIN_FETCH": "1"}, {"FAIL_BRANCH_FETCH": "1"},
                        {"NOT_ANCESTOR": "1"}, {"RESOLVED_PIN": TIP}):
            with self.subTest(changes=changes):
                run, trace, head, _ = self.run_deploy_functions(**changes)
                self.assertNotEqual(run.returncode, 0)
                self.assertEqual(head, PREVIOUS)
                self.assertFalse(any(x.startswith(("checkout ", "reset ")) for x in trace))

    def test_manual_call_without_identity_is_rejected_without_io(self):
        run, trace, head, state = self.run_deploy_functions(
            DEPLOY_SHA="", DEPLOY_REF="", ADVANCE_ON_CHECKOUT="1")
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("DEPLOY_SHA must be", run.stderr)
        self.assertEqual(head, PREVIOUS)
        self.assertEqual(state, [])
        self.assertFalse(any(x.startswith(("fetch ", "checkout ", "reset ")) for x in trace))

    def test_installed_head_mismatch_remains_a_rollback_failure(self):
        commands = r'''
resolve_deploy_target
PRE_DEPLOY_HASH="dddddddddddddddddddddddddddddddddddddddd"
rollback_deploy() { printf '%s\n' "$PRE_DEPLOY_HASH" > "$STATE"; }
trap 'on_exit $?' EXIT
update_deploy_code
'''
        run, _, head, state = self.run_deploy_functions(commands, INSTALLED_OVERRIDE=TIP)
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(head, TIP)  # fake rollback only records the requested previous SHA
        self.assertEqual(state, [PREVIOUS])
        self.assertIn("Installed HEAD differs", run.stderr)
        self.assertIn("Deploy rollback executado com sucesso", run.stderr)

    def test_no_update_before_target_resolution(self):
        run, trace, head, _ = self.run_deploy_functions("update_deploy_code")
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(trace, [])
        self.assertEqual(head, PREVIOUS)

    def test_stage_wrapper_preserves_pin_and_environment_isolation(self):
        with tempfile.TemporaryDirectory(prefix="deploy-wrapper-test-") as temp:
            folder = Path(temp)
            fake_bin = folder / "bin"
            fake_bin.mkdir()
            output = folder / "context"
            launcher = fake_bin / "bash"
            launcher.write_text('#!/bin/sh\nprintf "%s\\n" "$BRANCH" "$DEPLOY_SHA" "$DEPLOY_REF" '
                                '"$DEPLOY_ACTIVATE_WHATSAPP_REMINDER_SERVICE" > "$CONTEXT_OUTPUT"\n')
            launcher.chmod(0o700)
            env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}", DEPLOY_SHA=PIN,
                       DEPLOY_REF="refs/heads/stage", BRANCH="main",
                       DEPLOY_ACTIVATE_WHATSAPP_REMINDER_SERVICE="1", CONTEXT_OUTPUT=str(output))
            run = subprocess.run(["/bin/bash", "scripts/deploy_stage_vps.sh"], cwd=ROOT,
                                 env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(output.read_text().splitlines(), ["stage", PIN, "refs/heads/stage", "0"])

    def test_workflows_pin_checkout_archive_and_installer_and_keep_sync_assertion(self):
        for filename, branch in (("deploy.yml", "main"), ("deploy-stage.yml", "stage")):
            with self.subTest(workflow=filename):
                text = (ROOT / ".github/workflows" / filename).read_text()
                checkouts = text.count("uses: actions/checkout@v5")
                self.assertEqual(checkouts, len(re.findall(
                    r"uses: actions/checkout@v5\n\s+with:\n\s+ref: \$\{\{ github.sha \}\}", text)))
                self.assertIn('git archive --format=tar "$DEPLOY_SHA" --', text)
                self.assertNotRegex(text, r'git archive[^\n]*origin/')
                self.assertIn('git fetch --no-tags origin "$DEPLOY_SHA"', text)
                self.assertIn('DEPLOY_SHA="$DEPLOY_SHA" \\', text)
                self.assertIn('DEPLOY_REF="$DEPLOY_REF" \\', text)
                self.assertIn('test "$(git rev-parse HEAD)" = "${{ github.sha }}"', text)
                self.assertIn("run: python3 scripts/tests/test_deploy_immutable_sha.py", text)
                preflight = "- name: Verify approved SHA on VPS before configuration"
                self.assertEqual(text.count(preflight), 1)
                self.assertLess(text.index(preflight), text.index("- name: Configure OpenAI secret"))
                remote_check = "\n".join(step_blocks(text, preflight.removeprefix("- name: "))[0])
                self.assertIn("source /dev/stdin", remote_check)
                self.assertIn("resolve_deploy_target", remote_check)
                self.assertIn(f"DEPLOY_REF='refs/heads/{branch}'", remote_check)
                # A remote job must validate before even SSH secret preparation.
                jobs = re.split(r"(?m)^  ([a-z][a-z0-9-]*):\n", text)
                for name, body in zip(jobs[1::2], jobs[2::2]):
                    if "ssh -i" not in body and "secrets.VPS_SSH_KEY" not in body:
                        continue
                    self.assertIn("- name: Validate immutable deploy target", body, name)
                    self.assertLess(body.index("- name: Validate immutable deploy target"),
                                    body.index("secrets.VPS_SSH_KEY"), name)
                for block in step_blocks(text, "Validate immutable deploy target"):
                    value = "\n".join(block)
                    self.assertIn(f"BRANCH: {branch}", value)
                    self.assertIn("DEPLOY_REF: ${{ github.ref }}", value)
                    self.assertIn("DEPLOY_SHA: ${{ github.sha }}", value)
                    self.assertIn("validate_deploy_target", value)

    def test_workflow_validation_function_rejects_manual_wrong_ref_before_io(self):
        run, trace, _, _ = self.run_deploy_functions("validate_deploy_target", DEPLOY_REF="refs/heads/feature")
        self.assertNotEqual(run.returncode, 0)
        self.assertFalse(any(x.startswith(("fetch ", "checkout ", "reset ")) for x in trace))
        run, _, _, _ = self.run_deploy_functions("validate_deploy_target", DEPLOY_SHA="")
        self.assertNotEqual(run.returncode, 0)


class RealGitDeployTests(unittest.TestCase):
    """Use a disposable remote and checkout, never an operational checkout."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="deploy-real-git-")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.remote = self.folder / "remote.git"
        self.seed = self.folder / "seed"
        self.checkout = self.folder / "app"
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
                        GIT_AUTHOR_NAME="Synthetic deploy test", GIT_AUTHOR_EMAIL="deploy@example.invalid",
                        GIT_COMMITTER_NAME="Synthetic deploy test", GIT_COMMITTER_EMAIL="deploy@example.invalid")
        self.git("init", "--bare", str(self.remote))
        self.git("init", "-b", "main", str(self.seed))
        self.git("-C", str(self.seed), "remote", "add", "origin", str(self.remote))
        self.previous = self.commit("previous")
        self.git("-C", str(self.seed), "push", "origin", "HEAD:main", "HEAD:stage")
        self.git("clone", "--branch", "main", str(self.remote), str(self.checkout))
        self.pin = self.commit("approved")
        self.git("-C", str(self.seed), "push", "origin", "HEAD:main", "HEAD:stage")
        self.tip = self.commit("parallel")
        self.git("-C", str(self.seed), "push", "origin", "HEAD:main", "HEAD:stage")
        (self.checkout / "backend").mkdir()
        (self.checkout / "backend/.env").write_text("SYNTHETIC_PRESERVE=yes\n")
        self.runtime = self.folder / "backups"

    def git(self, *args):
        return subprocess.check_output(["git", *args], env=self.env, stderr=subprocess.DEVNULL,
                                       text=True).strip()

    def commit(self, value):
        (self.seed / "release.txt").write_text(value)
        self.git("-C", str(self.seed), "add", "release.txt")
        self.git("-C", str(self.seed), "commit", "-m", value)
        return self.git("-C", str(self.seed), "rev-parse", "HEAD")

    def context(self, **changes):
        return dict(self.env, APP_DIR=str(self.checkout), BRANCH="main", DEPLOY_SHA=self.pin,
                    DEPLOY_REF="refs/heads/main", RUNTIME_BACKUP_DIR=str(self.runtime), **changes)

    def run_functions(self, commands="resolve_deploy_target\nupdate_deploy_code", **changes):
        env = self.context()
        env.update(changes)
        return subprocess.run(["bash", "-c", 'set -euo pipefail; source "$1"; cd "$APP_DIR";\n' + commands,
                               "fixture", str(ROOT / "scripts/deploy_prod_vps.sh")], env=env,
                              capture_output=True, text=True, timeout=20)

    def assert_untouched(self):
        self.assertEqual(self.git("-C", str(self.checkout), "rev-parse", "HEAD"), self.previous)
        self.assertEqual((self.checkout / "backend/.env").read_text(), "SYNTHETIC_PRESERVE=yes\n")
        self.assertFalse(self.runtime.exists())

    def test_real_remote_advances_after_resolution_but_only_approved_tree_is_installed(self):
        for branch in ("main", "stage"):
            with self.subTest(branch=branch):
                # Reset only the disposable checkout for the second environment.
                self.git("-C", str(self.checkout), "reset", "--hard", self.previous)
                later = self.commit("later-" + branch)
                commands = '''resolve_deploy_target
git -C "$SEED" push origin "HEAD:$BRANCH"
update_deploy_code
'''
                run = self.run_functions(commands, BRANCH=branch, DEPLOY_REF=f"refs/heads/{branch}",
                                         SEED=str(self.seed))
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(self.git("-C", str(self.checkout), "rev-parse", "HEAD"), self.pin)
                self.assertEqual((self.checkout / "release.txt").read_text(), "approved")
                self.assertEqual(self.git("--git-dir", str(self.remote), "rev-parse", branch), later)

    def test_real_unavailable_and_foreign_commits_do_not_touch_runtime(self):
        self.git("-C", str(self.seed), "checkout", "--orphan", "foreign")
        foreign = self.commit("unrelated")
        self.git("-C", str(self.seed), "push", "origin", "foreign")
        for sha in ("0" * 40, foreign):
            with self.subTest(sha=sha):
                run = self.run_functions(DEPLOY_SHA=sha)
                self.assertNotEqual(run.returncode, 0)
                self.assert_untouched()

    def test_entrypoint_missing_or_invalid_identity_fails_before_any_command(self):
        fake_bin = self.folder / "bin"
        fake_bin.mkdir()
        calls = self.folder / "calls"
        for name in ("git", "systemctl", "curl", "npm", "python3", "sudo"):
            path = fake_bin / name
            path.write_text('#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$CALLS"\nexit 97\n')
            path.chmod(0o700)
        for identity in ("", "bad-sha"):
            for entrypoint in ("deploy_prod_vps.sh", "deploy_stage_vps.sh"):
                with self.subTest(identity=identity, entrypoint=entrypoint):
                    env = self.context()
                    env.update(DEPLOY_SHA=identity, DEPLOY_REF="", CALLS=str(calls),
                               PATH=f"{fake_bin}:{os.environ['PATH']}")
                    run = subprocess.run(["/bin/bash", str(ROOT / "scripts" / entrypoint)], env=env,
                                         capture_output=True, text=True, timeout=10)
                    self.assertNotEqual(run.returncode, 0)
                    self.assertIn("DEPLOY_SHA must be", run.stderr)
                    self.assertFalse(calls.exists(), "Invalid SHA reached an external command")
                    self.assertNotIn("rollback", run.stderr)
                    self.assert_untouched()

    def test_actual_remote_workflow_preflight_checks_commit_before_runtime_writes(self):
        fake_bin = self.folder / "ssh-bin"
        fake_bin.mkdir()
        ssh = fake_bin / "ssh"
        # Execute the actual SSH command locally, substituting only its fixture path.
        ssh.write_text('''#!/bin/bash
command="${@: -1}"
command="${command//\/var\/www\/fortcordis-v2/$FIXTURE_CHECKOUT}"
command="${command//\/var\/www\/fortcordis-stage/$FIXTURE_CHECKOUT}"
exec bash -c "$command"
''')
        ssh.chmod(0o700)
        for workflow in ("deploy.yml", "deploy-stage.yml"):
            block = step_blocks((ROOT / ".github/workflows" / workflow).read_text(),
                                "Verify approved SHA on VPS before configuration")[0]
            start = next(i for i, line in enumerate(block) if line.strip() == "run: |") + 1
            code = textwrap.dedent("\n".join(block[start:]))
            code = code.replace("${{ secrets.VPS_USER }}@${{ secrets.VPS_HOST }}", "fixture@host")
            for sha, expected in ((self.pin, 0), ("0" * 40, 1)):
                with self.subTest(workflow=workflow, sha=sha):
                    env = self.context()
                    env.update(DEPLOY_SHA=sha, FIXTURE_CHECKOUT=str(self.checkout),
                               PATH=f"{fake_bin}:{os.environ['PATH']}")
                    run = subprocess.run(["bash", "-c", code], cwd=ROOT, env=env,
                                         capture_output=True, text=True, timeout=20)
                    self.assertEqual(run.returncode == 0, expected == 0, run.stderr)
                    self.assert_untouched()


if __name__ == "__main__":
    unittest.main(verbosity=2)
