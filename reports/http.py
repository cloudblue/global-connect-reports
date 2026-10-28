import random
import time
from collections import deque
from functools import reduce
from operator import getitem

import requests
from connect.client import ConnectClient, R

SERVICE_IDS = ["SRVC-9722-3113", "SRVC-5460-5389"]

# Google allows 24 ListEntitlements requests per minute per project. That budget
# belongs to the whole project, so the connector's own traffic spends from it
# too and the report has to stay below the cap rather than on it.
ENTITLEMENTS_PER_MINUTE = 18
RATE_LIMIT_WINDOW = 60.0

# Google answers 429 once the quota is spent, and the extension can pass back a
# gateway error while it restarts. Both clear on their own, so they are worth
# another attempt; a 404 or a 403 will not.
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 5
MAX_BACKOFF = 32.0

# Seconds the client may spend waiting across the whole run. Once spent, calls
# fail fast and the rows carry the error, instead of a report that sleeps for
# hours and looks hung.
RETRY_BUDGET = 300.0

REQUEST_TIMEOUT = 60.0


class RateLimiter(object):
    """Keep at most `limit` calls inside any `window` seconds, sleeping to fit."""

    def __init__(self, limit, window=RATE_LIMIT_WINDOW):
        self.limit = limit
        self.window = window
        self.calls = deque()

    def wait(self):
        while True:
            now = time.monotonic()
            while self.calls and now - self.calls[0] >= self.window:
                self.calls.popleft()
            if len(self.calls) < self.limit:
                self.calls.append(now)
                return
            time.sleep(self.window - (now - self.calls[0]))


class GoogleAPIClient(object):
    def __init__(self, connect_client: ConnectClient, api_url, marketplace_id):
        self.api_url = api_url
        self.client = connect_client
        self.marketplace_id = marketplace_id.upper()
        self.entitlements_limiter = RateLimiter(ENTITLEMENTS_PER_MINUTE)
        self.retry_budget = RETRY_BUDGET

    def get_customer_entitlements(self, customer_id):
        return self._get(
            f'/api/customer_entitlements?marketplace_id={self.marketplace_id}'
            f'&customer_id={customer_id}',
            limiter=self.entitlements_limiter,
        )

    def get_entitlement_offer(self, customer_id, entitlement_id):
        return self._get(
            f'/api/entitlement_offer?marketplace_id={self.marketplace_id}'
            f'&customer_id={customer_id}&entitlement_id={entitlement_id}',
        )

    def get_biling_records(self, entitlement_id, month, year):
        return self._get(
            f'/api/entitlements/{entitlement_id}?month={month}&year={year}',
        )

    def _get(self, path, limiter=None):
        headers = {
            "Accept": "application/json",
            "Authorization": self.client.api_key,
        }
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if limiter:
                limiter.wait()
            try:
                response = requests.get(
                    self.api_url + path,
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                )
            except requests.RequestException as error:
                raise GoogleAPIClientError(f'Google Management Settings Error: {error}')
            if response.status_code == 200:
                return response.json()
            if response.status_code not in RETRY_STATUS_CODES or attempt == MAX_ATTEMPTS:
                break
            if not self._wait_before_retry(attempt, response):
                break
        raise GoogleAPIClientError(f'Google Management Settings Error: {response.content}')

    def _wait_before_retry(self, attempt, response):
        """Wait out a retryable answer. Returns False once the budget is spent."""
        delay = _retry_after(response)
        if delay is None:
            # Jittered, so that two reports running together do not keep
            # retrying in step and spending the same quota window twice.
            delay = min(2 ** attempt, MAX_BACKOFF) * (0.5 + random.random())
        if delay > self.retry_budget:
            return False
        self.retry_budget -= delay
        time.sleep(delay)
        return True


def obtain_url_for_service(client):
    query = R()
    query &= R().status.eq('installed')
    query &= R().environment.extension.id.oneof(SERVICE_IDS)
    installation = client.ns('devops').collection('installations').filter(query).first()
    if not installation:
        raise ValueError('The service for the Google Managements Settings was not found.')

    hostname = _get_value(installation, ['environment', 'hostname'])
    domain = _get_value(installation, ['environment', 'domain'])
    url = 'https://' + hostname + '.' + domain
    return url


class GoogleAPIClientError(Exception):
    pass


def _retry_after(response):
    """Seconds Google asked us to wait, or None when it did not say."""
    try:
        return max(float(response.headers.get('Retry-After')), 0.0)
    except (TypeError, ValueError):
        return None


def _get_value(base, path, default="-"):
    try:
        return reduce(lambda value, path_elem: getitem(value, path_elem), path, base)
    except (IndexError, KeyError, TypeError):
        return default
