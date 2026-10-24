import json
import unittest
from public_social import x_posts,archive_posts,PublicReadError

class PublicSocialTests(unittest.TestCase):
 def tweet(self,ident,author,text,stamp=1792822586000):
  return {'rest_id':ident,'details':{'full_text':text,'created_at_ms':stamp},
          'core':{'user_results':{'result':{'core':{'screen_name':author}}}}}
 def page(self,payload):return '<script>stream.next({data:'+json.dumps(json.dumps(payload))+'})</script>'
 def test_public_page_filters_other_authors_and_preserves_publication(self):
  payload=[self.tweet('1','elonmusk','BTC update'),self.tweet('2','other','bad signal')]
  posts=x_posts(self.page(payload),'elonmusk')
  self.assertEqual(len(posts),1)
  self.assertEqual(posts[0]['created_at'],'2026-10-24T06:16:26+00:00')
 def test_quoted_posts_do_not_become_independent_signals(self):
  tweet=self.tweet('1','elonmusk','comment')
  tweet['quoted_tweet_results']=self.tweet('2','elonmusk','old quoted text')
  self.assertEqual(len(x_posts(self.page(tweet),'elonmusk')),1)
 def test_schema_or_signin_page_is_not_healthy_empty_feed(self):
  with self.assertRaises(PublicReadError):x_posts('<html>Please sign in</html>','elonmusk')
 def test_deduplicates_same_post_in_multiple_payloads(self):
  tweet=self.tweet('1','elonmusk','BTC')
  self.assertEqual(len(x_posts(self.page([tweet,tweet]),'elonmusk')),1)
 def test_archive_keeps_original_date_and_ignores_image_titles(self):
  page='<rss><channel><item><title>Generated image summary</title><description>View image</description><link>image</link></item><item><description>&lt;p&gt;BTC &amp;amp; ETH&lt;/p&gt;</description><pubDate>Fri, 23 Oct 2026 18:09:23 +0000</pubDate><link>original</link></item></channel></rss>'
  posts=archive_posts(page)
  self.assertEqual(len(posts),1)
  self.assertEqual(posts[0]['text'],'BTC & ETH')
  self.assertEqual(posts[0]['created_at'],'Fri, 23 Oct 2026 18:09:23 +0000')
