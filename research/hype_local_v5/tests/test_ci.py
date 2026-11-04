"""Local bare-Git integration: no remote service or market data involved."""
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from research.hype_local_v5 import ci_publish


class ResearchPublicationTests(unittest.TestCase):
    def test_report_branch_preserves_source_checkout_and_appends_stages(self):
        def command(*args,cwd):
            return subprocess.check_output(['git',*args],cwd=cwd,stderr=subprocess.DEVNULL).decode().strip()
        with TemporaryDirectory() as temp:
            root=Path(temp);remote=root/'remote.git';repo=root/'source';repo.mkdir()
            command('init','--bare',str(remote),cwd=root)
            command('init',cwd=repo)
            command('config','user.name','research-test',cwd=repo)
            command('config','user.email','research-test@example.invalid',cwd=repo)
            (repo/'source.txt').write_text('source must stay intact')
            command('add','source.txt',cwd=repo);command('commit','-m','source',cwd=repo)
            source_head=command('rev-parse','HEAD',cwd=repo)
            command('remote','add','origin',str(remote),cwd=repo)
            before=Path.cwd()
            try:
                os.chdir(repo)
                with patch.dict(os.environ,{'GITHUB_SHA':source_head,'GITHUB_RUN_ID':'unit-test','GITHUB_RUN_ATTEMPT':'1'}):
                    status=ci_publish.prepare_reports('started',Path('status-start'),[])
                    first=ci_publish.publish(Path('status-start'),status)
                    Path('study').mkdir();Path('study/run_status.json').write_text('{"status":"fixture_only"}')
                    status=ci_publish.prepare_reports('final',Path('status-final'),[Path('study')])
                    second=ci_publish.publish(Path('status-final'),status)
                self.assertEqual(command('rev-parse','HEAD',cwd=repo),source_head)
                self.assertEqual(command('rev-parse',second+'^',cwd=repo),first)
                self.assertEqual((repo/'source.txt').read_text(),'source must stay intact')
                stored=json.loads(command('--git-dir='+str(remote),'show',ci_publish.BRANCH+':status.json',cwd=root))
                self.assertEqual(stored['stage'],'final')
                tree=command('--git-dir='+str(remote),'ls-tree','-r','--name-only',ci_publish.BRANCH,cwd=root)
                self.assertIn('runs/unit-test-1/started/status.json',tree)
                self.assertIn('runs/unit-test-1/final/reports/study/run_status.json',tree)
                self.assertNotIn('source.txt',tree)
            finally:os.chdir(before)


if __name__=='__main__':unittest.main()
