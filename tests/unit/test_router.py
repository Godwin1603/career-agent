import pytest

from src.applications.services.router import ApplicationRouter
from src.core.config import settings
from src.core.enums import ApplicationStrategy, JobStatus
from src.jobs.models import Job


@pytest.fixture
def router():
    return ApplicationRouter()


def test_router_below_threshold(router):
    job = Job(relevance_score=settings.RELEVANCE_THRESHOLD - 1)
    result = router.route(job)

    assert result.skipped is True
    assert len(result.strategies) == 0
    assert job.status == JobStatus.skipped


def test_router_no_strategies(router):
    job = Job(
        relevance_score=settings.RELEVANCE_THRESHOLD + 10,
        application_url=None,
        detected_portal=None,
        google_form_url=None,
        email_address=None,
    )
    result = router.route(job)

    assert result.skipped is False
    assert len(result.strategies) == 0
    assert job.status != JobStatus.skipped


def test_router_portal_only(router):
    job = Job(
        relevance_score=settings.RELEVANCE_THRESHOLD + 10,
        application_url="https://portal.com/job/123",
        detected_portal="Workday",
    )
    result = router.route(job)

    assert result.skipped is False
    assert result.strategies == [ApplicationStrategy.portal]


def test_router_form_only(router):
    job = Job(
        relevance_score=settings.RELEVANCE_THRESHOLD + 10,
        google_form_url="https://docs.google.com/forms/d/123",
    )
    result = router.route(job)

    assert result.skipped is False
    assert result.strategies == [ApplicationStrategy.form]


def test_router_email_only(router):
    job = Job(
        relevance_score=settings.RELEVANCE_THRESHOLD + 10,
        email_address="jobs@company.com",
    )
    result = router.route(job)

    assert result.skipped is False
    assert result.strategies == [ApplicationStrategy.email]


def test_router_portal_and_form(router):
    job = Job(
        relevance_score=settings.RELEVANCE_THRESHOLD + 10,
        application_url="https://portal.com",
        google_form_url="https://docs.google.com/forms/d/123",
    )
    result = router.route(job)

    assert result.skipped is False
    assert ApplicationStrategy.portal in result.strategies
    assert ApplicationStrategy.form in result.strategies
    assert len(result.strategies) == 2


def test_router_portal_and_email(router):
    job = Job(
        relevance_score=settings.RELEVANCE_THRESHOLD + 10,
        application_url="https://portal.com",
        email_address="jobs@company.com",
    )
    result = router.route(job)

    assert result.skipped is False
    assert ApplicationStrategy.portal in result.strategies
    assert ApplicationStrategy.email in result.strategies
    assert len(result.strategies) == 2


def test_router_form_and_email(router):
    job = Job(
        relevance_score=settings.RELEVANCE_THRESHOLD + 10,
        google_form_url="https://docs.google.com/forms/d/123",
        email_address="jobs@company.com",
    )
    result = router.route(job)

    assert result.skipped is False
    assert ApplicationStrategy.form in result.strategies
    assert ApplicationStrategy.email in result.strategies
    assert len(result.strategies) == 2


def test_router_all_strategies(router):
    job = Job(
        relevance_score=settings.RELEVANCE_THRESHOLD + 10,
        application_url="https://portal.com",
        google_form_url="https://docs.google.com/forms/d/123",
        email_address="jobs@company.com",
    )
    result = router.route(job)

    assert result.skipped is False
    assert ApplicationStrategy.portal in result.strategies
    assert ApplicationStrategy.form in result.strategies
    assert ApplicationStrategy.email in result.strategies
    assert len(result.strategies) == 3


def test_router_exactly_at_threshold(router):
    job = Job(
        relevance_score=settings.RELEVANCE_THRESHOLD,
        application_url="https://portal.com/job/123",
    )
    result = router.route(job)

    assert result.skipped is False
    assert result.strategies == [ApplicationStrategy.portal]
