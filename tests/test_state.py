import json
from datetime import UTC, datetime, timedelta

from fedifetcher.state import ServerCache, TimestampedSet


def ago(**kwargs):
    return datetime.now(UTC) - timedelta(**kwargs)


def test_timestamped_set_from_plain_iterable():
    seen = TimestampedSet(["a", "b"])
    assert "a" in seen
    assert len(seen) == 2
    assert list(seen) == ["a", "b"]


def test_timestamped_set_preserves_insertion_order():
    seen = TimestampedSet(["c", "a", "b"])
    seen.add("d")
    assert list(seen) == ["c", "a", "b", "d"]


def test_timestamped_set_keeps_first_timestamp():
    original = ago(hours=5)
    seen = TimestampedSet([])
    seen.add("a", original)
    seen.add("a")
    assert seen.get("a") == original


def test_timestamped_set_parses_stored_timestamps():
    when = ago(hours=2)
    seen = TimestampedSet({"a": when.isoformat()})
    assert seen.get("a") == when


def test_timestamped_set_update_adds_many():
    seen = TimestampedSet([])
    seen.update(["a", "b"])
    assert len(seen) == 2


def test_timestamped_set_expiry_drops_only_the_old():
    seen = TimestampedSet([])
    seen.add("old", ago(hours=48))
    seen.add("fresh", ago(hours=1))

    assert seen.expire_older_than(timedelta(hours=24)) == 1

    assert "old" not in seen
    assert "fresh" in seen


def test_timestamped_set_roundtrips_through_json():
    when = ago(hours=3)
    seen = TimestampedSet([])
    seen.add("a", when)

    restored = TimestampedSet(json.loads(seen.toJSON()))

    assert restored.get("a") == when


def server(**overrides):
    entry = {"peertubeApiSupport": False, "last_checked": ago(days=1)}
    entry.update(overrides)
    return entry


def test_server_cache_add_and_get():
    hosts = ServerCache({})
    hosts.add("example.org", server())
    assert "example.org" in hosts
    assert hosts.get("example.org")["peertubeApiSupport"] is False
    assert len(hosts) == 1


def test_server_cache_parses_stored_last_checked():
    when = ago(days=2)
    hosts = ServerCache({"example.org": {"last_checked": when.isoformat()}})
    assert hosts.get("example.org")["last_checked"] == when


def test_server_cache_expires_stale_hosts():
    hosts = ServerCache({})
    hosts.add("stale.org", server(last_checked=ago(days=40)))
    hosts.add("fresh.org", server(last_checked=ago(days=1)))

    assert hosts.expire(timedelta(days=30), timedelta(hours=1)) == 1

    assert "stale.org" not in hosts
    assert "fresh.org" in hosts


def test_server_cache_expires_failures_sooner_than_successes():
    hosts = ServerCache({})
    hosts.add("failed.org", server(info=None, last_checked=ago(hours=2)))
    hosts.add("worked.org", server(last_checked=ago(hours=2)))

    assert hosts.expire(timedelta(days=30), timedelta(hours=1)) == 1

    assert "failed.org" not in hosts
    assert "worked.org" in hosts


def test_server_cache_drops_entries_predating_peertube_support():
    hosts = ServerCache({})
    hosts.add("old-schema.org", {"last_checked": ago(hours=1)})

    assert hosts.expire(timedelta(days=30), timedelta(hours=1)) == 1

    assert "old-schema.org" not in hosts


def test_server_cache_keeps_entries_without_last_checked():
    hosts = ServerCache({})
    hosts.add("unknown-age.org", {"peertubeApiSupport": True})

    assert hosts.expire(timedelta(days=30), timedelta(hours=1)) == 0

    assert "unknown-age.org" in hosts


def test_server_cache_is_iterable():
    hosts = ServerCache({})
    hosts.add("a.org", server())
    hosts.add("b.org", server())
    assert list(hosts) == ["a.org", "b.org"]


def test_server_cache_roundtrips_through_json():
    when = ago(days=1)
    hosts = ServerCache({})
    hosts.add("example.org", server(last_checked=when))

    restored = ServerCache(json.loads(hosts.toJSON()))

    assert restored.get("example.org")["last_checked"] == when
