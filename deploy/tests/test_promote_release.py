import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "promote_release.py"
spec = importlib.util.spec_from_file_location("promote_release", SCRIPT)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.remote = self.root / "remote.git"
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.run_git("init", "--bare", str(self.remote))
        self.run_git("init", "-b", "main")
        self.run_git("config", "user.name", "Release test")
        self.run_git("config", "user.email", "release@example.invalid")
        self.run_git("remote", "add", "origin", str(self.remote))
        chart = self.repo / "deploy/helm"
        chart.mkdir(parents=True)
        (chart / "Chart.yaml").write_text('apiVersion: v2\nname: robinhood\nversion: 0.1.0\nappVersion: "0.1.0"\n')
        (chart / "values.yaml").write_text('images:\n  api: example/api\n  worker: example/worker\n  tag: "0.1.0"\nworker:\n  enabled: true\n')
        (self.repo / "application.txt").write_text("tagged source\n")
        self.run_git("add", ".")
        self.run_git("commit", "-m", "initial source")

    def run_git(self, *arguments):
        result = subprocess.run(["git", *arguments], cwd=self.repo,
                                capture_output=True, text=True, check=True)
        return result.stdout.strip()

    def promote(self, tag, success=True):
        result = subprocess.run([sys.executable, str(SCRIPT), "promote", tag],
                                cwd=self.repo, capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        return result.stderr

    def published(self):
        return self.run_git("--git-dir", str(self.remote), "rev-parse", "refs/heads/deploy/production")

    def published_file(self, path):
        return self.run_git("--git-dir", str(self.remote), "show", "deploy/production:" + path)

    def test_release_versions(self):
        self.assertEqual(release.version("v2.10.3"), (2, 10, 3))
        for tag in ["latest", "v1.2", "v01.2.3", "v1.2.3-rc.1", "v1.2.3+build", "v1.2.3\n"]:
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                release.version(tag)

    def test_promotion_preserves_exact_tagged_source_and_local_changes(self):
        self.run_git("tag", "-a", "v1.2.3", "-m", "release")
        source = self.run_git("rev-parse", "HEAD")
        (self.repo / "application.txt").write_text("uncommitted local change\n")
        self.run_git("add", "application.txt")
        before = self.run_git("write-tree")
        result = self.promote("v1.2.3")
        self.assertEqual(result["status"], "promoted")
        self.assertEqual(result["sourceRevision"], source)
        self.assertEqual(self.published_file("application.txt"), "tagged source")
        self.assertIn('tag: "1.2.3"', self.published_file("deploy/helm/values.yaml"))
        self.assertIn('appVersion: "1.2.3"', self.published_file("deploy/helm/Chart.yaml"))
        self.assertEqual(json.loads(self.published_file("deploy/release.json"))["tag"], "v1.2.3")
        self.assertEqual(before, self.run_git("write-tree"))
        self.assertEqual((self.repo / "application.txt").read_text(), "uncommitted local change\n")

    def test_retry_is_idempotent_and_older_releases_do_not_roll_back(self):
        self.run_git("tag", "v0.9.0")
        self.run_git("tag", "v0.10.0")
        self.promote("v0.10.0")
        head = self.published()
        self.assertEqual(self.promote("v0.10.0")["status"], "already-promoted")
        self.assertEqual(self.promote("v0.9.0")["status"], "skipped-older-release")
        self.assertEqual(head, self.published())

    def test_next_release_fast_forwards_the_production_branch(self):
        self.run_git("tag", "v1.0.0")
        self.promote("v1.0.0")
        before = self.published()
        (self.repo / "application.txt").write_text("next release\n")
        self.run_git("add", "application.txt")
        self.run_git("commit", "-m", "next release")
        self.run_git("tag", "v1.1.0")
        self.promote("v1.1.0")
        self.run_git("merge-base", "--is-ancestor", before, self.published())
        self.assertEqual(self.published_file("application.txt"), "next release")

    def test_moved_tag_or_wrong_checkout_cannot_be_promoted(self):
        self.run_git("tag", "v1.0.0")
        self.promote("v1.0.0")
        head = self.published()
        (self.repo / "application.txt").write_text("unreleased source\n")
        self.run_git("add", "application.txt")
        self.run_git("commit", "-m", "unreleased source")
        self.assertIn("tagged commit", self.promote("v1.0.0", success=False))
        self.run_git("tag", "-f", "v1.0.0")
        self.assertIn("cannot be moved", self.promote("v1.0.0", success=False))
        self.assertEqual(head, self.published())


if __name__ == "__main__":
    unittest.main()
