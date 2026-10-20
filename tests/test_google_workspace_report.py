# -*- coding: utf-8 -*-
#
# Copyright (c) 2026, CloudBlue
# All rights reserved.
#

import os
from unittest.mock import MagicMock

import pytest
from openpyxl import load_workbook

from reports.google_workspace_report.entrypoint import (
    GOOGLE_PRODUCT,
    HEADERS,
    _process_line,
    generate,
)

XLSX_TEMPLATE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'reports', 'google_workspace_report', 'templates', 'xlsx', 'template.xlsx',
)

RECONCILIATION_PARAM_ID = 'PRM-550-104-278-0001'
ITEM_ID = 'PRD-550-104-278-0001'


@pytest.fixture
def product_params():
    return [
        {
            'parameter': {'id': 'sku_id'},
            'item': {'id': ITEM_ID},
            'value': '1010020027',
        },
        {
            'parameter': {'id': 'product_id'},
            'item': {'id': ITEM_ID},
            'value': 'Google-Apps',
        },
    ]


@pytest.fixture
def subscription():
    return {
        'id': 'AS-0000-0000-0001',
        'external_id': 'EXT-0001',
        'status': 'active',
        'params': [
            {'id': 'domain', 'name': 'domain', 'value': 'example.com'},
            {'id': 'customer_id', 'name': 'customer_id', 'value': 'C01abcdef'},
            {'id': RECONCILIATION_PARAM_ID, 'name': 'reconciliation_id', 'value': 'VND-0001'},
        ],
        'items': [
            {
                'display_name': 'Google Workspace Business Standard',
                'mpn': 'GOOGLE_WORKSPACE_BUSINESS_STANDARD',
                'global_id': ITEM_ID,
            },
        ],
        'events': {
            'created': {'at': '2024-02-14T10:00:00+00:00'},
            'updated': {'at': '2026-10-16T14:46:08+00:00'},
        },
        'billing': {
            'period': {'delta': 1, 'uom': 'monthly'},
            'anniversary': {'day': 14, 'month': 2},
        },
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
        'product': {'id': GOOGLE_PRODUCT[0], 'name': 'Google Workspace'},
    }


@pytest.fixture
def client(subscription, product_params):
    client = MagicMock()

    subscriptions = MagicMock()
    subscriptions.count.return_value = 1
    subscriptions.__iter__.return_value = iter([subscription])
    client.ns.return_value.assets.filter.return_value = subscriptions

    products = client.products.__getitem__.return_value
    products.configurations.filter.return_value.limit.return_value = product_params

    product_collection = client.collection.return_value.__getitem__.return_value
    product_collection.collection.return_value.all.return_value = [
        {'name': RECONCILIATION_PARAM_ID, 'constraints': {'reconciliation': True}},
    ]

    return client


@pytest.fixture
def parameters():
    return {
        'date': {'after': '2020-10-08T03:00:00+00:00', 'before': '2026-10-15T19:45:00+00:00'},
        'mkp': {'all': False, 'choices': ['MP-19359']},
        'connection_type': {'all': False, 'choices': ['test']},
        'status': {'all': True, 'choices': []},
    }


def test_process_line_returns_one_value_per_header(subscription, product_params):
    """Every column produced by _process_line must have a matching HEADERS entry.

    Regression test for LITE-35385: two columns (Google SKU, Google Product) were
    added to the row without being added to HEADERS, which made the json renderer
    fail with 'IndexError: tuple index out of range' and silently shifted the
    columns of the csv renderer.
    """
    row = _process_line(subscription, 'VND-0001', product_params)

    assert len(row) == len(HEADERS)


def test_headers_are_unique():
    assert len(set(HEADERS)) == len(HEADERS)


def test_json_renderer_emits_one_key_per_header(client, parameters):
    rows = list(generate(
        client=client,
        parameters=parameters,
        progress_callback=MagicMock(),
        renderer_type='json',
    ))

    assert len(rows) == 1
    assert len(rows[0]) == len(HEADERS)
    assert rows[0]['google_sku'] == '1010020027'
    assert rows[0]['google_product'] == 'Google-Apps'
    assert rows[0]['item_mpn'] == 'GOOGLE_WORKSPACE_BUSINESS_STANDARD'
    assert rows[0]['hub_name'] == 'Hub'


def test_csv_renderer_header_row_matches_data_rows(client, parameters):
    rows = list(generate(
        client=client,
        parameters=parameters,
        progress_callback=MagicMock(),
        renderer_type='csv',
    ))

    assert rows[0] == HEADERS
    assert all(len(row) == len(HEADERS) for row in rows[1:])


def test_xlsx_template_column_count_matches_headers():
    """The xlsx renderer writes the row by position under the template header row."""
    worksheet = load_workbook(XLSX_TEMPLATE).active
    header = [cell.value for cell in worksheet[1] if cell.value is not None]

    assert len(header) == len(HEADERS)
