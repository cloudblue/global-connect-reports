# -*- coding: utf-8 -*-
#
# Copyright (c) 2026, CloudBlue
# All rights reserved.
#

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

from reports import http
from reports.http import GoogleAPIClient, GoogleAPIClientError, RateLimiter

QUOTA_ERROR = (
    b"429 Quota exceeded for quota metric 'ListEntitlements requests' and limit "
    b"'ListEntitlements requests per minute' of service 'cloudchannel.googleapis.com'"
)


class FakeClock(object):
    """A clock that only moves when something sleeps on it."""

    def __init__(self):
        self.now = 0.0
        self.slept = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class FakeResponse(object):
    def __init__(self, status_code, body=None, content=b'', headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self._body = body

    def json(self):
        return self._body


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(http, 'time', fake)
    return fake


@pytest.fixture(autouse=True)
def no_jitter(monkeypatch):
    """Pin the random half of the backoff so the delays can be asserted."""
    monkeypatch.setattr(http, 'random', SimpleNamespace(random=lambda: 0.5))


@pytest.fixture
def client():
    connect_client = MagicMock()
    connect_client.api_key = 'ApiKey SU-000-000:secret'
    return GoogleAPIClient(connect_client, 'https://gms.example.com', 'mp-19359')


def answers(monkeypatch, *responses):
    """Answer each call with the next response, repeating the last one."""
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        response = responses[min(len(calls) - 1, len(responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(http.requests, 'get', fake_get)
    return calls


def test_the_urls_are_the_ones_the_extension_serves(client, clock, monkeypatch):
    calls = answers(monkeypatch, FakeResponse(200, body=[]))

    client.get_customer_entitlements('C-1')
    client.get_entitlement_offer('C-1', 'E-1')
    client.get_biling_records('E-1', 10, 2026)

    assert calls == [
        'https://gms.example.com/api/customer_entitlements?marketplace_id=MP-19359&customer_id=C-1',
        'https://gms.example.com/api/entitlement_offer?marketplace_id=MP-19359'
        '&customer_id=C-1&entitlement_id=E-1',
        'https://gms.example.com/api/entitlements/E-1?month=10&year=2026',
    ]


def test_a_quota_error_is_retried(client, clock, monkeypatch):
    calls = answers(
        monkeypatch,
        FakeResponse(429, content=QUOTA_ERROR),
        FakeResponse(200, body=[{'name': 'entitlements/E-1'}]),
    )

    assert client.get_customer_entitlements('C-1') == [{'name': 'entitlements/E-1'}]
    assert len(calls) == 2
    assert clock.slept == [2.0]


def test_the_backoff_grows_and_then_gives_up(client, clock, monkeypatch):
    calls = answers(monkeypatch, FakeResponse(429, content=QUOTA_ERROR))

    with pytest.raises(GoogleAPIClientError) as error:
        client.get_customer_entitlements('C-1')

    assert len(calls) == http.MAX_ATTEMPTS
    assert clock.slept == [2.0, 4.0, 8.0, 16.0]
    assert 'Quota exceeded' in str(error.value)


def test_a_retry_after_header_is_honoured(client, clock, monkeypatch):
    answers(
        monkeypatch,
        FakeResponse(429, content=QUOTA_ERROR, headers={'Retry-After': '7'}),
        FakeResponse(200, body=[]),
    )

    client.get_customer_entitlements('C-1')

    assert clock.slept == [7.0]


def test_retrying_stops_once_the_budget_is_spent(client, clock, monkeypatch):
    client.retry_budget = 1.0
    calls = answers(monkeypatch, FakeResponse(429, content=QUOTA_ERROR, headers={'Retry-After': '30'}))

    with pytest.raises(GoogleAPIClientError):
        client.get_customer_entitlements('C-1')

    assert len(calls) == 1
    assert clock.slept == []


def test_a_missing_customer_is_not_retried(client, clock, monkeypatch):
    calls = answers(monkeypatch, FakeResponse(404, content=b'404 Customer name not found'))

    with pytest.raises(GoogleAPIClientError) as error:
        client.get_customer_entitlements('C-1')

    assert len(calls) == 1
    assert clock.slept == []
    assert 'Customer name not found' in str(error.value)


def test_a_network_error_is_reported_like_any_other(client, clock, monkeypatch):
    answers(monkeypatch, requests.ConnectionError('connection reset'))

    with pytest.raises(GoogleAPIClientError) as error:
        client.get_customer_entitlements('C-1')

    assert 'connection reset' in str(error.value)


def test_entitlement_calls_are_paced(client, clock, monkeypatch):
    client.entitlements_limiter = RateLimiter(2, window=60.0)
    answers(monkeypatch, FakeResponse(200, body=[]))

    for customer_id in ('C-1', 'C-2', 'C-3'):
        client.get_customer_entitlements(customer_id)

    assert clock.slept == [60.0]


def test_offer_calls_are_not_paced(client, clock, monkeypatch):
    client.entitlements_limiter = RateLimiter(1, window=60.0)
    answers(monkeypatch, FakeResponse(200, body={}))

    for entitlement_id in ('E-1', 'E-2', 'E-3'):
        client.get_entitlement_offer('C-1', entitlement_id)

    assert clock.slept == []
