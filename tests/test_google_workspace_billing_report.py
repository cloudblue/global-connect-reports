# -*- coding: utf-8 -*-
#
# Copyright (c) 2026, CloudBlue
# All rights reserved.
#

import os
from unittest.mock import MagicMock

import pytest
from openpyxl import load_workbook

from reports.google_workspace_billing_report import entrypoint
from reports.google_workspace_billing_report.entrypoint import (
    GOOGLE_PRODUCTS,
    HEADERS,
    _get_products,
    _process_line,
    generate,
    get_item_data,
)
from reports.http import GoogleAPIClientError

XLSX_TEMPLATE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'reports', 'google_workspace_billing_report', 'templates', 'xlsx', 'template.xlsx',
)

CUSTOMER_ID = 'C01abcdef'
ENTITLEMENT_ID = 'ENT-0001'


@pytest.fixture(autouse=True)
def clear_cache():
    """entrypoint.subscriptions_dict is a module global and leaks between runs."""
    entrypoint.subscriptions_dict.clear()
    yield
    entrypoint.subscriptions_dict.clear()


class FakeGoogleClient:
    def __init__(self, entitlements=None, offer=None, entitlements_error=None, offer_error=None):
        self.entitlements = entitlements if entitlements is not None else [_entitlement()]
        self.offer = offer if offer is not None else _offer()
        self.entitlements_error = entitlements_error
        self.offer_error = offer_error

    def get_customer_entitlements(self, customer_id):
        if self.entitlements_error:
            raise GoogleAPIClientError(self.entitlements_error)
        return self.entitlements

    def get_entitlement_offer(self, customer_id, entitlement_id):
        if self.offer_error:
            raise GoogleAPIClientError(self.offer_error)
        return self.offer


def _entitlement(entitlement_id=ENTITLEMENT_ID, **overrides):
    entitlement = {
        'name': f'accounts/A-1/customers/{CUSTOMER_ID}/entitlements/{entitlement_id}',
        'provisioning_state': 1,
        'create_time': '2026-01-10T08:00:00Z',
        'commitment_settings': {
            'start_time': '2026-01-10T08:00:00Z',
            'end_time': '2027-01-10T08:00:00Z',
            'renewal_settings': {'enable_renewal': True},
        },
        'parameters': [
            {'name': 'num_units', 'value': {'int64_value': 25}},
            {'name': 'max_units', 'value': {'int64_value': 50}},
            {'name': 'assigned_units', 'value': {'int64_value': 20}},
        ],
        'purchase_order_id': 'PO-1',
    }
    entitlement.update(overrides)
    return entitlement


def _offer(**overrides):
    offer = {
        'name': 'accounts/A-1/offers/OFFER-1',
        'sku': {
            'name': 'accounts/A-1/skus/1010020027',
            'product': {'name': 'accounts/A-1/products/Google-Apps'},
            'marketing_info': {'display_name': 'Google Workspace Business Standard'},
        },
        'price_by_resources': [{
            'price': {
                'base_price': {'units': '12', 'nanos': 0, 'currency_code': 'EUR'},
                'effective_price': {'units': '10', 'nanos': 500000000, 'currency_code': 'EUR'},
            },
        }],
    }
    offer.update(overrides)
    return offer


@pytest.fixture
def subscription():
    return {
        'id': 'AS-0000-0000-0001',
        'external_id': 'EXT-0001',
        'status': 'active',
        'params': [
            {'id': 'domain', 'value': 'example.com'},
            {'id': 'customer_id', 'value': CUSTOMER_ID},
            {'id': 'entitlement_id', 'value': ENTITLEMENT_ID},
            {'id': 'purchase_type', 'value': 'commitment'},
        ],
        'items': [{
            'display_name': 'Google Workspace Business Standard',
            'mpn': 'GOOGLE_WORKSPACE_BUSINESS_STANDARD',
            'quantity': 25,
            'period': 'Yearly',
        }],
        'events': {
            'created': {'at': '2026-01-10T08:00:00+00:00'},
            'updated': {'at': '2026-10-16T14:46:08+00:00'},
        },
        'billing': {'period': {'delta': 1, 'uom': 'yearly'}, 'anniversary': {'day': 10, 'month': 1}},
        'contract': {'id': 'CRD-00000-00000-00001', 'name': 'Distribution contract'},
        'tiers': {
            'customer': {'id': 'TA-0000-0000-0001', 'name': 'Customer', 'external_id': 'C-1'},
            'tier1': {'id': 'TA-0000-0000-0002', 'name': 'Reseller', 'external_id': 'T1-1'},
            'tier2': {'id': 'TA-0000-0000-0003', 'name': 'Distributor', 'external_id': 'T2-1'},
        },
        'connection': {
            'type': 'test',
            'provider': {'id': 'PA-000-001', 'name': 'Provider'},
            'vendor': {'id': 'VA-000-002', 'name': 'Vendor'},
            'hub': {'id': 'HB-0000-0001', 'name': 'Hub'},
        },
        'product': {'id': GOOGLE_PRODUCTS[1], 'name': 'Google Workspace'},
    }


@pytest.fixture
def parameters():
    return {
        'date': {'after': '2026-10-01T03:00:00+00:00', 'before': '2026-10-21T02:59:00+00:00'},
        'connection_type': {'all': False, 'choices': ['test']},
        'mkp': {'all': False, 'choices': ['MP-19359']},
        'product': {'all': False, 'choices': [GOOGLE_PRODUCTS[1]]},
    }


@pytest.fixture
def connect_client(subscription):
    client = MagicMock()
    resource_set = MagicMock()
    resource_set.count.return_value = 1
    resource_set.__iter__.return_value = iter([subscription])
    client.ns.return_value.assets.filter.return_value = resource_set
    client.get.return_value = [{'usage': 20}]
    return client


@pytest.fixture
def google(monkeypatch):
    """Patch out the two calls that would reach the network."""
    fake = FakeGoogleClient()
    monkeypatch.setattr(entrypoint, 'obtain_url_for_service', lambda client: 'https://gms.example.com')
    monkeypatch.setattr(entrypoint, 'GoogleAPIClient', lambda *args, **kwargs: fake)
    return fake


def _run(connect_client, parameters, renderer_type):
    return list(generate(
        client=connect_client,
        parameters=parameters,
        progress_callback=MagicMock(),
        renderer_type=renderer_type,
    ))


def test_get_item_data_returns_two_values():
    """Regression test for LITE-35404.

    _process_line unpacks two values. The billing report in
    cloudblue/google-workspace-connect-report has a same-named helper that
    returns three; taking that one is what raised
    'ValueError: too many values to unpack (expected 2)' on every row.
    """
    items = [{'display_name': 'Name', 'mpn': 'MPN', 'period': 'Yearly'}]

    assert len(get_item_data([])) == 2
    assert len(get_item_data(items)) == 2
    assert len(get_item_data(items + items)) == 2


def test_process_line_returns_one_value_per_header(subscription, google):
    row = _process_line(subscription, google, MagicMock(get=lambda url: []))

    assert len(row) == len(HEADERS)


def test_headers_are_unique():
    """The HEADERS block was pasted twice: 66 entries for a 53 column row."""
    assert len(set(HEADERS)) == len(HEADERS)


def test_xlsx_template_header_matches_headers():
    worksheet = load_workbook(XLSX_TEMPLATE).active
    header = [cell.value for cell in worksheet[1] if cell.value is not None]

    assert header == list(HEADERS)


def test_csv_renderer_header_row_matches_data_rows(connect_client, parameters, google):
    rows = _run(connect_client, parameters, 'csv')

    assert rows[0] == HEADERS
    assert len(rows) == 2
    assert all(len(row) == len(HEADERS) for row in rows[1:])


def test_json_renderer_emits_one_key_per_header(connect_client, parameters, google):
    rows = _run(connect_client, parameters, 'json')

    assert len(rows) == 1
    assert len(rows[0]) == len(HEADERS)
    assert rows[0]['google_entitlement_id'] == ENTITLEMENT_ID
    assert rows[0]['google_assigned_units'] == 20
    assert rows[0]['google_maximum_units'] == 50
    assert rows[0]['google_commitment_end_date'] == '2027-01-10T08:00:00Z'
    assert rows[0]['consumption'] == 20
    assert rows[0]['error_details'] == '-'


def test_price_columns_keep_the_upstream_mapping(subscription, google):
    """Pinned, not endorsed.

    'Google Offer Effective Price' is filled from the offer's base_price and
    'Google Offer Price' from its effective_price, which reads inverted. The
    mapping is identical in cloudblue/google-workspace-connect-report, so it is
    left alone here rather than silently flipping prices in a report used for
    reconciliation. Flip both this test and _process_line together if the
    report owner confirms it is wrong.
    """
    row = _process_line(subscription, google, MagicMock(get=lambda url: []))

    assert row[HEADERS.index('Google Offer Effective Price')] == '12.00 EUR'  # base_price
    assert row[HEADERS.index('Google Offer Price')] == '10.50 EUR'  # effective_price


def test_xlsx_renderer_yields_plain_rows(connect_client, parameters, google):
    rows = _run(connect_client, parameters, 'xlsx')

    assert len(rows) == 1
    assert len(rows[0]) == len(HEADERS)


def test_row_failure_is_reported_in_the_last_column(connect_client, parameters, google, subscription):
    """A broken subscription must not raise: the runner blocks the template on
    any exception escaping report code."""
    del subscription['connection']

    rows = _run(connect_client, parameters, 'xlsx')

    assert len(rows) == 1
    assert rows[0][0] == 'AS-0000-0000-0001'
    assert 'KeyError' in rows[0][-1]
    assert len(rows[0]) == len(HEADERS)


def test_setup_failure_is_reported_in_the_last_column(connect_client, parameters, monkeypatch):
    def boom(client):
        raise ValueError('The service for the Google Managements Settings was not found.')

    monkeypatch.setattr(entrypoint, 'obtain_url_for_service', boom)

    rows = _run(connect_client, parameters, 'xlsx')

    assert len(rows) == 1
    assert 'Google Managements Settings was not found' in rows[0][-1]
    assert len(rows[0]) == len(HEADERS)


def test_google_api_error_is_reported_per_row(connect_client, parameters, monkeypatch):
    fake = FakeGoogleClient(entitlements_error='Google Management Settings Error: 403')
    monkeypatch.setattr(entrypoint, 'obtain_url_for_service', lambda client: 'https://gms.example.com')
    monkeypatch.setattr(entrypoint, 'GoogleAPIClient', lambda *args, **kwargs: fake)

    rows = _run(connect_client, parameters, 'json')

    assert len(rows) == 1
    assert '403' in rows[0]['error_details']
    assert rows[0]['subscription_id'] == 'AS-0000-0000-0001'


def test_empty_price_by_resources_does_not_raise(subscription, monkeypatch):
    """Google returns the key as an empty list, so indexing the get() default raised IndexError."""
    fake = FakeGoogleClient(offer=_offer(price_by_resources=[]))

    row = _process_line(subscription, fake, MagicMock(get=lambda url: []))

    assert row[HEADERS.index('Google Offer Price')] == '-'
    assert row[HEADERS.index('Google Offer Effective Price')] == '-'


def test_empty_suspension_reasons_does_not_raise(subscription):
    fake = FakeGoogleClient(entitlements=[_entitlement(suspension_reasons=[])])

    row = _process_line(subscription, fake, MagicMock(get=lambda url: []))

    assert row[HEADERS.index('Google Suspension Reasons')] == '-'


def test_entitlement_unknown_to_google_does_not_raise(subscription):
    """Connect can hold an entitlement_id that is absent from the customer's
    entitlement list, which used to raise KeyError."""
    fake = FakeGoogleClient(entitlements=[_entitlement(entitlement_id='ENT-OTHER')])

    row = _process_line(subscription, fake, MagicMock(get=lambda url: []))

    assert len(row) == len(HEADERS)
    assert row[HEADERS.index('Google Offer ID')] == 'accounts/A-1/offers/OFFER-1'


def test_selected_products_are_honoured():
    """The product parameter is required but used to be ignored."""
    assert _get_products({'product': {'all': False, 'choices': [GOOGLE_PRODUCTS[1]]}}) == [GOOGLE_PRODUCTS[1]]
    assert _get_products({'product': {'all': True, 'choices': []}}) == GOOGLE_PRODUCTS
    assert _get_products({}) == GOOGLE_PRODUCTS


def test_non_google_product_selection_is_reported(connect_client, parameters, google):
    parameters['product'] = {'all': False, 'choices': ['PRD-000-000-000']}

    rows = _run(connect_client, parameters, 'xlsx')

    assert len(rows) == 1
    assert 'None of the selected products is a Google product' in rows[0][-1]
