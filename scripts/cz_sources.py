"""Small adapters around maintained libraries. Never publish session material/errors."""
import asyncio
import os
import re
import tempfile
import urllib.request
from contextlib import aclosing
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from urllib.parse import urlsplit


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def parse_time(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp requires timezone")
    return result.astimezone(timezone.utc)


def validate_post(post, username):
    if not re.fullmatch(r"\d{1,25}", str(post.get("id", ""))):
        raise ValueError("Invalid post ID")
    if post.get("author", "").lower() != username.lower():
        raise ValueError("Unexpected author")
    if not isinstance(post.get("text"), str) or not post["text"].strip() or len(post["text"]) > 30000:
        raise ValueError("Invalid text")
    date = parse_time(post["published_at"])
    if date > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("Future timestamp")
    post = dict(post)
    post["id"] = str(post["id"])
    post["published_at"] = date.isoformat()
    post["url"] = f"https://x.com/{username}/status/{post['id']}"
    post["edit_ids"] = [str(x) for x in post.get("edit_ids", []) if re.fullmatch(r"\d{1,25}", str(x))]
    return post


def normalize_tweet(tweet, username, user_id):
    if str(tweet.user.id) != str(user_id):
        return None  # Promoted entries / other authors must never become CZ signals.
    if tweet.user.username.lower() != username.lower():
        raise ValueError("Unexpected username")
    media = tweet.media
    has_media = bool(media.photos or media.videos or media.animated) if media is not None else None
    kind = ("retweet" if tweet.retweetedTweet else "reply" if tweet.inReplyToTweetId
            else "quote" if tweet.isQuoteStatus or tweet.quotedTweet else "original")
    edit = tweet.editControl or {}
    return validate_post({"id": str(tweet.id), "author": username,
                          "author_id": str(user_id), "text": tweet.rawContent,
                          "published_at": tweet.date.isoformat(), "kind": kind,
                          "has_media": has_media,
                          # The model prefers note_tweet full text. An ellipsis alone cannot
                          # prove truncation, so conservatively mark completeness unknown.
                          "text_complete": None if re.search(r"(?:…|\.\.\.)\s*(?:https?://\S+)?$", tweet.rawContent) else True,
                          "edit_ids": edit.get("edit_tweet_ids", [])}, username)


async def fetch_twscrape(config, state, cookies):
    result = {"source": "twscrape", "posts": [], "status": "error", "code": "source_error"}
    try:
        from twscrape import API
        from twscrape.logger import set_log_level
        set_log_level("CRITICAL")
    except ImportError:
        result["code"] = "dependency_missing"
        return result

    async def run():
        # Ephemeral credential database: never under the repo or in Actions cache/artifacts.
        with tempfile.TemporaryDirectory(prefix="cz-session-") as directory:
            api = API(os.path.join(directory, "accounts.db"), raise_when_no_account=True, wait_timeout=10)
            await api.pool.add_account_cookies("cz-monitor", cookies)
            user_id = state.get("user_id")
            if not user_id:
                user = await api.user_by_login(config["username"])
                if not user or user.username.lower() != config["username"].lower():
                    raise ValueError("Author lookup failed")
                user_id = str(user.id)
            result["user_id"] = user_id
            async with aclosing(api.user_tweets(int(user_id), limit=config.get("max_posts", 200))) as tweets:
                async for tweet in tweets:
                    post = normalize_tweet(tweet, config["username"], user_id)
                    if post:
                        result["posts"].append(post)
            result["status"] = "ok" if result["posts"] else "error"
            result["code"] = "ok" if result["posts"] else "empty_response"

    try:
        await asyncio.wait_for(run(), timeout=config.get("timeout_seconds", 90))
    except asyncio.TimeoutError:
        result["code"] = "timeout"
    except Exception:
        # Exceptions can include request headers or cookies. Only publish controlled codes.
        result["code"] = "source_error"
    if result["posts"] and result["status"] != "ok":
        result["status"] = "partial"
    return result


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.blocked = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.blocked += 1
        if tag in ("br", "p", "div"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.blocked:
            self.blocked -= 1

    def handle_data(self, data):
        if not self.blocked:
            self.parts.append(data)


def fetch_rss(config, url):
    result = {"source": "rss", "posts": [], "status": "error", "code": "source_error"}
    try:
        import feedparser
    except ImportError:
        result["code"] = "dependency_missing"
        return result
    try:
        if urlsplit(url).scheme != "https":
            raise ValueError("RSS requires HTTPS")
        req = urllib.request.Request(url, headers={"User-Agent": "rich-radar-cz/1.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError("Oversized feed")
        feed = feedparser.parse(body)
        rejected = 0
        for item in feed.entries[:config.get("max_posts", 200)]:
            try:
                # The source is owner-configured. Require an exact handle in each link,
                # but still label identity/completeness as secondary-source assertions.
                path = urlsplit(item.get("link", "")).path
                match = re.fullmatch(r"/([^/]+)/status/(\d+)/?", path)
                if not match or match[1].lower() != config["username"].lower():
                    raise ValueError("Unattributed item")
                timestamp = item.get("published_parsed") or item.get("updated_parsed")
                if not timestamp:
                    raise ValueError("Missing publication timestamp")
                parser = PlainText()
                content = item.get("content", [])
                parser.feed(content[0].get("value", "") if content else item.get("summary", ""))
                result["posts"].append(validate_post({
                    "id": match[2], "author": config["username"], "text": "".join(parser.parts).strip(),
                    "published_at": datetime(*timestamp[:6], tzinfo=timezone.utc).isoformat(),
                    "kind": "unknown", "has_media": None, "text_complete": None,
                    "edit_ids": []}, config["username"]))
            except (ValueError, KeyError, TypeError):
                rejected += 1
        if result["posts"]:
            result["status"] = "partial" if feed.bozo or rejected else "ok"
            result["code"] = "partial_feed" if feed.bozo or rejected else "ok"
        else:
            result["code"] = "empty_response"
    except Exception:
        result["code"] = "source_error"
    return result
