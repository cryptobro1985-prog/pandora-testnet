import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile
import io
import json
from unittest.mock import patch
from types import SimpleNamespace
from urllib.parse import urlparse, parse_qs

SPEC = importlib.util.spec_from_file_location("hype_acquire", Path(__file__).parents[1] / "acquire.py")
acquire = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acquire)


class AcquisitionSafetyTests(unittest.TestCase):
    def test_private_artifact_probe_uses_existing_authenticated_gh(self):
        result=SimpleNamespace(returncode=0,stdout=json.dumps({'id':13278474318,
            'name':'universal-minute-HYPE','expired':False}).encode(),stderr=b'')
        with patch.object(acquire.subprocess,'run',return_value=result) as run, \
                patch.object(acquire.urllib.request,'urlopen',side_effect=AssertionError('anonymous private API probe')):
            status=acquire.gh_probe(13278474318)
        self.assertEqual(status['status'],'accessible')
        self.assertEqual(run.call_args.args[0],['gh','api',
            '/repos/cryptobro1985-prog/pandora-testnet/actions/artifacts/13278474318'])

    def test_artifact_only_success_is_independent_of_blocked_bybit(self):
        with tempfile.TemporaryDirectory() as d, \
                patch.object(acquire,'gh_probe',return_value={'status':'accessible'}), \
                patch.object(acquire,'probe',side_effect=AssertionError('Bybit must not be requested')), \
                patch.object(acquire,'gh_artifact',return_value={'artifact_id':13278474318,'sha256':'fixture'}), \
                patch.object(acquire,'safe_extract',return_value=[{'fixture':True}]):
            result=acquire.main(['--fetch','--source','artifacts','--artifact-ids','13278474318','--output',d])
            report=json.loads((Path(d)/'acquisition.json').read_text())
        self.assertEqual(result,0)
        self.assertEqual(report['downloaded_files'],1)
        self.assertEqual(len(report['probes']),1)

    def test_auth_failure_is_recorded_without_anonymous_fallback(self):
        result=SimpleNamespace(returncode=1,stdout=b'',stderr=b'Forbidden')
        with patch.object(acquire.subprocess,'run',return_value=result):
            status=acquire.gh_probe(13278474318)
        self.assertEqual(status['status'],'unavailable')
        self.assertIn('Forbidden',status['error'])

    def test_valid_archive_preserves_and_hashes_contents(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); z = root / "a.zip"
            with zipfile.ZipFile(z, "w") as f:
                f.writestr("nested/HYPE.csv", "ts,close\n1,2\n")
            rows = acquire.safe_extract(z, root / "out")
            self.assertEqual(rows[0]["sha256"], acquire.digest(root / "out/nested/HYPE.csv")["sha256"])
            self.assertEqual((root / "out/nested/HYPE.csv").read_text(), "ts,close\n1,2\n")

    def test_traversal_validated_before_any_output(self):
        for bad in ("../escape", "/absolute", "a\\..\\escape", "C:escape"):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as d:
                root = Path(d); z = root / "a.zip"
                with zipfile.ZipFile(z, "w") as f:
                    f.writestr("good.csv", "good")
                    f.writestr(bad, "bad")
                with self.assertRaises(ValueError): acquire.safe_extract(z, root / "out")
                self.assertFalse((root / "out/good.csv").exists())

    def test_symlink_and_size_limits_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); z = root / "a.zip"
            with zipfile.ZipFile(z, "w") as f:
                item = zipfile.ZipInfo("link")
                item.external_attr = (stat.S_IFLNK | 0o777) << 16
                f.writestr(item, "../escape")
            with self.assertRaises(ValueError): acquire.safe_extract(z, root / "out")
            with zipfile.ZipFile(z, "w") as f: f.writestr("a", "12345")
            with self.assertRaises(ValueError): acquire.safe_extract(z, root / "out", max_bytes=4)

    def test_existing_output_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); z = root / "a.zip"; out = root / "out"; out.mkdir()
            (out / "a").write_text("original")
            with zipfile.ZipFile(z, "w") as f: f.writestr("a", "replacement")
            with self.assertRaises(FileExistsError): acquire.safe_extract(z, out)
            self.assertEqual((out / "a").read_text(), "original")

    def test_oi_pagination_preserves_real_observations(self):
        import datetime as dt
        start = dt.date(2026, 10, 4)
        epoch = int(dt.datetime(2026, 10, 4, tzinfo=dt.timezone.utc).timestamp() * 1000)
        urls = []
        def response(request, **kwargs):
            urls.append(request.full_url)
            records = ([{"timestamp": str(epoch + 300000), "openInterest": "110"},
                        {"timestamp": str(epoch), "openInterest": "100"}]
                       if len(urls) == 1 else [])
            return io.BytesIO(json.dumps({"retCode": 0, "result": {"list": records}}).encode())
        with tempfile.TemporaryDirectory() as d, patch.object(acquire.urllib.request, "urlopen", response):
            out = Path(d) / "oi.csv"
            report = acquire.fetch_historical_oi(start, start, out)
            self.assertEqual(report["points"], 2)
            self.assertEqual(out.read_text().splitlines()[1:], [f"{epoch},100.0", f"{epoch+300000},110.0"])
            self.assertFalse(report["available_30s_history"])

    def test_oi_rejects_future_observations(self):
        import datetime as dt
        obj = {"retCode": 0, "result": {"list": [{"timestamp": "9999999999999", "openInterest": "1"}]}}
        with tempfile.TemporaryDirectory() as d, patch.object(acquire.urllib.request, "urlopen",
                return_value=io.BytesIO(json.dumps(obj).encode())):
            out = Path(d) / "oi.csv"
            with self.assertRaises(ValueError): acquire.fetch_historical_oi(dt.date(2026,10,4), dt.date(2026,10,4), out)
            self.assertFalse(out.exists())


if __name__ == "__main__": unittest.main()
