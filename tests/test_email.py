from tests.context import Cache, JobEmailsConfig, Email, compose_email
from tests.fake_k8s import FakeK8sPodGenerator


def test_email_basic():
    """Basic test."""
    email = Email(
        subject="subject", to_addr="to@example.com", from_addr="from@example.com", body="body"
    )
    assert email
    assert email.message


def test_email_compose():
    """Basic compose test."""
    cache = Cache()

    cache.add_event(FakeK8sPodGenerator.new(phase="Running", job_emails=JobEmailsConfig.ALL))
    assert len(cache.cache) == 1

    for userjobs in cache.cache:
        email = compose_email(userjobs)
        assert email
        assert email.message
