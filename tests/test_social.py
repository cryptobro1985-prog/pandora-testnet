import asyncio
import os
import unittest
from unittest.mock import patch, MagicMock
import social_scrapers as social

class SocialTests(unittest.TestCase):
 def test_missing_session_fails_before_network(self):
  with patch.dict(os.environ, {'X_SESSION_COOKIES':''}):
   with self.assertRaisesRegex(social.SourceUnavailable,'needs_x_session'):
    asyncio.run(social.read_x(['elonmusk']))
 def test_html_and_entities(self):
  self.assertEqual(social.plain('<p>BTC &amp; ETH</p>'),'BTC & ETH')
 def test_subprocess_timeout(self):
  with patch.object(social.subprocess,'run',side_effect=social.subprocess.TimeoutExpired('reader',35)):
   with self.assertRaisesRegex(social.SourceUnavailable,'source_timeout'):social.poll('x',['elonmusk'])
 def test_secret_exception_not_forwarded(self):
  with patch.object(social.subprocess,'run',return_value=MagicMock(stdout='secret exception with token')):
   with self.assertRaisesRegex(social.SourceUnavailable,'reader_failed'):social.poll('x',['elonmusk'])
 def test_successful_empty_page_is_valid(self):
  with patch.object(social.subprocess,'run',return_value=MagicMock(stdout='{"ok":true,"posts":[]}')):
   self.assertEqual(social.poll('x',['elonmusk']),[])
 def test_block_not_reported_as_empty_success(self):
  with patch.object(social.subprocess,'run',return_value=MagicMock(stdout='{"ok":false,"error":"truth_http_403"}')):
   with self.assertRaisesRegex(social.SourceUnavailable,'truth_http_403'):social.poll('truth',['realDonaldTrump'])
