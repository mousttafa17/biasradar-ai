from biasradar.ingestion.rss import RSSFetcher


def test_rss_fetcher_normalizes_and_filters_entries(monkeypatch) -> None:
    feed = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Example Feed</title>
      <item><title>Argentina reaches the final</title>
        <link>https://example.com/argentina-final</link>
        <description>World Cup report</description>
        <pubDate>Sat, 18 Jul 2026 10:00:00 GMT</pubDate></item>
      <item><title>Unrelated technology story</title>
        <link>https://example.com/technology</link></item>
    </channel></rss>"""
    monkeypatch.setattr(RSSFetcher, "_download", lambda self, url: feed)

    items = RSSFetcher(["https://example.com/feed.xml"]).fetch("Argentina FIFA")

    assert len(items) == 1
    assert items[0].source_name == "Example Feed"
    assert items[0].source_type == "rss"
    assert items[0].provider == "rss"
    assert str(items[0].url) == "https://example.com/argentina-final"
    assert items[0].published_at is not None


def test_rss_fetcher_respects_global_limit(monkeypatch) -> None:
    feed = b"""<rss version="2.0"><channel><title>Feed</title>
      <item><title>Topic one</title><link>https://example.com/one</link></item>
      <item><title>Topic two</title><link>https://example.com/two</link></item>
    </channel></rss>"""
    monkeypatch.setattr(RSSFetcher, "_download", lambda self, url: feed)

    assert len(RSSFetcher(["https://example.com/feed.xml"]).fetch("Topic", 1)) == 1
