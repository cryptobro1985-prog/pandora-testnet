from public_parser import parse_profile,parse_post

def test_public_profile_parser():
    html='''<html><script type="application/json">{"xig_user_by_username":{"pk":"1","username":"demo","full_name":"Demo","biography":"bio","follower_count":10,"following_count":2,"is_verified":true,"is_private":false,"profile_pic_url":"x","polaris_ordered_timeline_connection":{"edges":[{"node":{"code":"ABC123"}}]}}}</script></html>'''
    p=parse_profile(html,"demo")
    assert p["user_id"]=="1"
    assert p["followers_count"]==10
    assert p["recent_post_codes"]==["ABC123"]

def test_public_post_parser():
    html='''<html><script type="application/json">{"xig_polaris_media":{"code":"ABC123","if_not_gated_logged_out":{"pk":"9","code":"ABC123","taken_at":1760000000,"like_count":5,"comment_count":2,"caption":{"text":"Hi @alice #wow"},"user":{"pk":"1","username":"demo"},"coauthor_producers":[{"username":"co"}],"usertags":{"in":[{"user":{"username":"tagged"}}]},"location":{"pk":"7","name":"Somewhere","lat":1.0,"lng":2.0}}}}</script></html>'''
    p=parse_post(html,"ABC123")
    assert p["like_count"]==5
    assert p["mentions"]==["alice"]
    assert p["hashtags"]==["wow"]
    assert p["tagged_users"]==["tagged"]
    assert p["coauthors"]==["co"]
    assert p["location"]["name"]=="Somewhere"
