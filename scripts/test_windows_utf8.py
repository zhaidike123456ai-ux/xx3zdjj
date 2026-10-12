"""Legacy-console simulation; not a Windows UI compatibility certificate."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ConsoleEncodingTests(unittest.TestCase):
    def test_native_discovery_outputs_utf8_under_gbk_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'中文草稿';root.mkdir()
            (root/'root_meta_info.json').write_text('{}',encoding='utf-8')
            result=subprocess.run([sys.executable,str(Path(__file__).with_name('jianying_adapter.py')),
                'discover','--draft-root',str(root)],capture_output=True,
                env={**os.environ,'PYTHONIOENCODING':'gbk'})
            self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads(result.stdout.decode('utf-8'))
            self.assertEqual(report['draft_roots'][0]['path'],str(root.resolve()))


if __name__=='__main__':unittest.main()
