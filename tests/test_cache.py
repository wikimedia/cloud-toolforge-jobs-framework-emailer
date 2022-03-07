import os  # noqa: F401
import sys  # noqa: F401
import pytest
from tests.context import Cache, JobEmailsConfig, event_early_filter, JobEventNotRelevant

from tests.fake_k8s import FakeK8sPodGenerator


def test_cache_init():
    """Verify we can create a cache object with no args."""
    assert Cache() is not None


def test_cache_init_with_unknown_kwargs():
    """Verify we can't create a cache with args."""
    with pytest.raises(TypeError, match=r".*got an unexpected keyword argument.*"):
        Cache(cache="")


def test_cache_add_empty_event():
    """Verify hte cache rejects fake/empty objects."""
    cache = Cache()

    with pytest.raises(JobEventNotRelevant):
        cache.add_event(FakeK8sPodGenerator.new())
    assert len(cache.cache) == 0


def test_cache_delete_one():
    """Verify the event cache is kept in expected state after adding/removing an object."""
    cache = Cache()

    cache.add_event(FakeK8sPodGenerator.new(phase="Running", job_emails=JobEmailsConfig.ALL))
    assert len(cache.cache) == 1

    cache.delete(cache.cache[0])
    assert len(cache.cache) == 0


def test_cache_delete_multiple():
    """Verify the event cache is kept in an expected state after removing multiple objects."""
    cache = Cache()

    event1 = FakeK8sPodGenerator.new(
        account="tool1", phase="Running", job_emails=JobEmailsConfig.ALL
    )
    cache.add_event(event1)
    userjob1 = cache.cache[0]
    assert len(cache.cache) == 1

    event2 = FakeK8sPodGenerator.new(
        account="tool2", phase="Running", job_emails=JobEmailsConfig.ALL
    )
    cache.add_event(event2)
    userjob2 = cache.cache[1]
    assert len(cache.cache) == 2

    event3 = FakeK8sPodGenerator.new(
        account="tool3", phase="Running", job_emails=JobEmailsConfig.ALL
    )
    cache.add_event(event3)
    userjob3 = cache.cache[2]
    assert len(cache.cache) == 3

    cache.delete(userjob3)
    assert len(cache.cache) == 2
    assert userjob1 in cache.cache
    assert userjob2 in cache.cache
    assert userjob3 not in cache.cache


def test_cache_repeated_event():
    """Verify the cache detects (and rejects) repeated events."""
    cache = Cache()

    event = FakeK8sPodGenerator.new(
        account="tool1", phase="Running", job_emails=JobEmailsConfig.ALL
    )
    cache.add_event(event)
    assert len(cache.cache) == 1

    for userjobs in cache.cache:
        assert len(userjobs.jobs) == 1
        for job in userjobs.jobs:
            assert len(job.events) == 1


def test_cache_seq_ok():
    """Verify the cache detects multiple events for the same single job."""
    cache = Cache()
    username = "mytool"
    jobname = "myjob"

    for event in FakeK8sPodGenerator.phase_ok_sequence(
        account=username, job_name=jobname, emails=JobEmailsConfig.ALL
    ):
        cache.add_event(event)
        assert len(cache.cache) == 1  # same account, same job

    for userjobs in cache.cache:
        if userjobs.username == username:
            assert len(userjobs.jobs) == 1

            for job in userjobs.jobs:
                if job.name == jobname:
                    assert len(job.events) == 3


def test_cache_multiple_seq():
    """Verify the cache can work with multiple evens for different jobs."""
    cache = Cache()
    n = 6

    for event in FakeK8sPodGenerator.multiple_sequence(n=n):
        try:
            cache.add_event(event)
        except JobEventNotRelevant:
            # some are meant to fail
            pass

    assert len(cache.cache) == n

    for userjobs in cache.cache:
        print(f"user: {userjobs.username}, jobs: {len(userjobs.jobs)}")
        assert len(userjobs.jobs) == n * 9  # magic number, per multiple_sequence() implementation
        for job in userjobs.jobs:
            print(f"job {job.name} ({job.type} {job.emailsconfig}) events: {len(job.events)}")
            if job.emailsconfig == JobEmailsConfig.ONFAILURE:
                assert len(job.events) == 2  # magic number again
            if job.emailsconfig == JobEmailsConfig.ONFINISH:
                assert len(job.events) == 2  # magic number again
            if job.emailsconfig == JobEmailsConfig.ALL:
                assert len(job.events) == 4  # magic number again


def test_event_early_filter_del_timestmp():
    """Verify the early filter function works."""
    event = FakeK8sPodGenerator.new(job_emails=JobEmailsConfig.ALL)
    event["metadata"]["deletion_timestamp"] = "some_value"
    with pytest.raises(JobEventNotRelevant):
        event_early_filter(event, "MODIFIED")


def test_event_early_filter_emails_none():
    """Verify the early filter function works."""
    event = FakeK8sPodGenerator.new(job_emails=JobEmailsConfig.NONE)
    with pytest.raises(JobEventNotRelevant):
        event_early_filter(event, "MODIFIED")


def test_event_early_filter_emails_all(caplog):
    """Verify the early filter function works."""
    event = FakeK8sPodGenerator.new(job_emails=JobEmailsConfig.ALL)
    event_early_filter(event, "MODIFIED")


def test_job_event_emails_none():
    """Verify that job events with emails = none are ignored."""
    cache = Cache()

    event = FakeK8sPodGenerator.new(job_emails=JobEmailsConfig.NONE)
    with pytest.raises(JobEventNotRelevant):
        cache.add_event(event) is None

    assert len(cache.cache) == 0
