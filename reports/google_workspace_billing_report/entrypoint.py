# -*- coding: utf-8 -*-
#
# Copyright (c) 2023, CloudBlue
# All rights reserved.
#

from connect.client import R

from reports.http import GoogleAPIClient, GoogleAPIClientError, obtain_url_for_service
from reports.subscriptions_report.utils import (convert_to_datetime, get_value,
                                                parameter_value_by_name, get_price)

HEADERS = (
    'Subscription ID', 'Subscription External ID', 'Google Entitlement ID',
    'Subscription Type', 'Purchase Type', 'Google Domain', 'Google Customer ID', 'Item Name', 'Item MPN',
    'Google SKU', 'Google Product', 'Google Offer ID', 'Google Offer SKU Display Name',
    'Item Quantity', 'Consumption', 'Google Num Units', 'Google Maximum Units', 'Google Assigned Units',
    'Google Offer Effective Price', 'Google Offer Price',
    'Creation date', 'Updated date', 'Google Creation Time', 'Google Commitment Start Date',
    'Google Commitment End Date', 'Google Renewal Enabled', 'Status', 'Google Entitlement Status',
    'Google Suspension Reasons', 'Google Purchase Order ID', 'Billing Period',
    'Anniversary Day', 'Anniversary Month', 'Contract ID', 'Contract Name',
    'Customer ID', 'Customer Name', 'Customer External ID',
    'Tier 1 ID', 'Tier 1 Name', 'Tier 1 External ID',
    'Tier 2 ID', 'Tier 2 Name', 'Tier 2 External ID',
    'Provider Account ID', 'Provider Account name',
    'Vendor Account ID', 'Vendor Account Name',
    'Product ID', 'Product Name', 'Hub ID', 'Hub Name',
    'Error Details',
)

GOOGLE_PRODUCTS = ['PRD-861-570-450', 'PRD-550-104-278']

DEFAULT_STATUSES = ['active', 'suspended', 'terminated', 'terminating']

subscriptions_dict = {}


def generate(
        client=None,
        parameters=None,
        progress_callback=None,
        renderer_type=None,
        extra_context_callback=None,
):
    progress = 0
    if renderer_type == 'csv':
        yield HEADERS
        progress = 1

    try:
        subscriptions = _get_subscriptions(client, parameters)
        google_client = _get_google_client(client, parameters)
        total = subscriptions.count() + progress
    except Exception as error:
        yield _render(_error_row('-', error), renderer_type)
        progress_callback(1, 1)
        return

    progress_callback(progress, max(total, 1))

    # An explicit iterator: a ResourceSet is iterable but not an iterator, and
    # the page fetches happen while it is consumed, so they need guarding too.
    pending = iter(subscriptions)
    while True:
        try:
            subscription = next(pending)
        except StopIteration:
            break
        except Exception as error:
            yield _render(_error_row('-', error), renderer_type)
            break

        yield _render(_safe_process_line(subscription, google_client, client), renderer_type)
        progress += 1
        progress_callback(progress, max(total, progress))

    progress_callback(max(progress, 1), max(total, progress, 1))


def _render(row, renderer_type):
    if renderer_type == 'json':
        return {
            HEADERS[idx].replace(' ', '_').lower(): value
            for idx, value in enumerate(row)
        }
    return row


def _error_row(subscription_id, error):
    """Report a failure in the last column instead of letting it escape.

    The reports runner blocks the report template on any exception raised by
    report code, so one unexpected subscription would take the template down
    for the whole account until it is unblocked by hand.
    """
    row = ['-'] * len(HEADERS)
    row[0] = subscription_id
    row[-1] = f'{type(error).__name__}: {error}'
    return tuple(row)


def _safe_process_line(subscription, google_client, connect_client):
    try:
        return _process_line(subscription, google_client, connect_client)
    except Exception as error:
        return _error_row(subscription.get('id', '-'), error)


def _get_google_client(client, parameters):
    url_for_service = obtain_url_for_service(client)
    choices = (parameters.get('mkp') or {}).get('choices') or []
    return GoogleAPIClient(client, url_for_service, choices[0] if choices else "")


def _get_products(parameters):
    """Honour the (required) product parameter, restricted to Google products."""
    product = parameters.get('product') or {}
    if product.get('all') is not False or not product.get('choices'):
        return GOOGLE_PRODUCTS
    selected = [product_id for product_id in product['choices'] if product_id in GOOGLE_PRODUCTS]
    if not selected:
        raise ValueError(
            'None of the selected products is a Google product '
            f'({", ".join(GOOGLE_PRODUCTS)}).',
        )
    return selected


def _get_subscriptions(client, parameters):
    query = R()
    query &= R().product.id.oneof(_get_products(parameters))
    if parameters.get('date') and parameters['date']['after'] != '':
        query &= R().events.created.at.ge(parameters['date']['after'])
        query &= R().events.created.at.le(parameters['date']['before'])
    if parameters.get('mkp') and parameters['mkp']['all'] is False:
        query &= R().marketplace.id.oneof(parameters['mkp']['choices'])
    if parameters.get('connection_type') and parameters['connection_type']['all'] is False:
        query &= R().asset.connection.type.oneof(parameters['connection_type']['choices'])
    if parameters.get('status') and parameters['status']['all'] is False:
        query &= R().status.oneof(parameters['status']['choices'])
    else:
        query &= R().status.oneof(DEFAULT_STATUSES)

    return client.ns('subscriptions').assets.filter(query)


def calculate_period(delta, uom):
    if delta == 1:
        if uom == 'monthly':
            return 'Monthly'
        return 'Yearly'
    else:
        if uom == 'monthly':
            return f'{int(delta)} Months'
        return f'{int(delta)} Years'


def _process_google_subscription(subscription, google_client):
    params = subscription.get('params', [])
    google_customer_id = parameter_value_by_name('customer_id', params, "")
    entitlement_id = get_entitlement_id(params)
    if not google_customer_id or not entitlement_id:
        res = {'error': 'Subscription has missing google parameters.'}
        return res
    # Test and preview subscriptions live in the provider's test Google
    # account. Asking the production account for them answers 404.
    environment = subscription['connection']['type']
    customer = (environment, google_customer_id)
    if customer not in subscriptions_dict.keys():
        _get_google_subscriptions(google_client, customer)
    if subscriptions_dict[customer].get('error'):
        return subscriptions_dict[customer]
    _fill_subscription_entitlement_offer_data(google_client, customer, entitlement_id)
    return subscriptions_dict.get(customer).get(entitlement_id, {})


def _fill_subscription_entitlement_offer_data(google_client, customer, entitlement_id):
    environment, google_customer_id = customer
    # setdefault: Connect can hold an entitlement_id that Google did not return
    # for this customer, in which case the key does not exist yet.
    entitlement = subscriptions_dict[customer].setdefault(entitlement_id, {})
    if 'entitlement_data' in entitlement or 'error' in entitlement:
        # Another subscription on the same entitlement already looked it up.
        return
    try:
        entitlement_offer_data = google_client.get_entitlement_offer(
            google_customer_id, entitlement_id, environment)
    except GoogleAPIClientError as err:
        subscriptions_dict[customer][entitlement_id] = {'error': str(err)}
        return

    entitlement['entitlement_data'] = entitlement_offer_data


def _get_google_subscriptions(google_client, customer):
    environment, google_customer_id = customer
    try:
        entitlements = google_client.get_customer_entitlements(google_customer_id, environment)
    except GoogleAPIClientError as err:
        subscriptions_dict[customer] = {'error': str(err)}
        return
    subscriptions_dict[customer] = _entitlements_as_dict(entitlements)


def _entitlements_as_dict(entitlements):
    result = {}
    for entitlement in entitlements:
        _id = entitlement['name'].split('/')[-1]
        result[_id] = entitlement
    return result


def _process_google_data(google_subscription):
    data = {}
    entitlement_data = google_subscription.get('entitlement_data', {})
    sku = entitlement_data.get('sku', {})
    # `or` rather than a get() default: Google returns these keys as empty lists.
    price = (entitlement_data.get('price_by_resources') or [{}])[0].get('price', {})
    suspension_reasons = google_subscription.get('suspension_reasons') or [-1]

    data['sku'] = sku.get('name', '-')
    data['product'] = sku.get('product', {}).get('name', '-')
    data['sku_display_name'] = sku.get('marketing_info', {}).get('display_name', '-')
    data['offer_id'] = entitlement_data.get('name', '-')
    data['num_units'] = get_google_parameter('num_units', google_subscription.get('parameters', {})).get(
        'value', {}).get('int64_value', '-')
    data['max_units'] = get_google_parameter('max_units', google_subscription.get('parameters', {})).get(
        'value', {}).get('int64_value', '-')
    data['assigned_units'] = get_google_parameter('assigned_units', google_subscription.get('parameters', {})).get(
        'value', {}).get('int64_value', '-')
    data['effective_price'] = get_price(price.get('effective_price', {}))
    data['base_price'] = get_price(price.get('base_price', {}))
    data['created_time'] = google_subscription.get('create_time', '-')
    data['commitment_start_date'] = google_subscription.get('commitment_settings', {}).get('start_time', '-')
    data['commitment_end_date'] = google_subscription.get('commitment_settings', {}).get('end_time', '-')
    data['renewal_status'] = get_value(
        google_subscription.get('commitment_settings', ''), 'renewal_settings', 'enable_renewal')
    data['status'] = get_entitlement_status(google_subscription.get('provisioning_state'))
    data['suspension_reasons'] = get_suspension_reasons(suspension_reasons[0])
    data['purchase_order_id'] = google_subscription.get('purchase_order_id', '-')
    data['error'] = google_subscription.get('error', '-')

    return data


def _get_consumed_value_from_usage(client, subscription):
    try:
        record = client.get(f'/usage/records?asset.id={subscription["id"]}&ordering(-created_time)&limit=1&offset=0')
        if len(record) == 0:
            return '-'
        return record[0].get('usage', '-')
    except Exception:
        return '-'


def get_item_data(items):
    """Return (display name, MPN).

    Must stay two values: _process_line unpacks two, and HEADERS has one label
    for each. The billing report in cloudblue/google-workspace-connect-report
    has a same-named helper that returns three (it also reports Item Period) --
    mixing the two is what caused LITE-35404.
    """
    if len(items) == 0:
        return '-', '-'
    elif len(items) == 1:
        return items[0]['display_name'], items[0]['mpn']
    else:
        for item in items:
            if 'GOOGLE_DRIVE_STORAGE' in item.get('mpn'):
                return 'Google Drive Storage', 'GOOGLE_DRIVE_STORAGE'

        return items[0]['display_name'], items[0]['mpn']


def _process_line(subscription, google_client, connect_client):
    params = subscription.get('params', [])
    item_name, item_mpn = get_item_data(subscription.get('items', []))
    google_subscription = _process_google_subscription(subscription, google_client)
    google_data = _process_google_data(google_subscription)
    consumption = _get_consumed_value_from_usage(connect_client, subscription)

    return (
        subscription.get('id'),
        subscription.get('external_id', '-'),
        get_entitlement_id(params),
        get_value(subscription, 'connection', 'type'),
        parameter_value_by_name('purchase_type', params),
        parameter_value_by_name('domain', params),
        parameter_value_by_name('customer_id', params),
        item_name,
        item_mpn,
        google_data['sku'],
        google_data['product'],
        google_data['offer_id'],
        google_data['sku_display_name'],
        next(iter(subscription.get('items', [])), {}).get('quantity', '-'),
        consumption,
        google_data['num_units'],
        google_data['max_units'],
        google_data['assigned_units'],
        google_data['base_price'],
        google_data['effective_price'],
        convert_to_datetime(subscription['events']['created']['at']),
        convert_to_datetime(subscription['events']['updated']['at']),
        google_data['created_time'],
        google_data['commitment_start_date'],
        google_data['commitment_end_date'],
        google_data['renewal_status'],
        subscription.get('status'),
        google_data['status'],
        google_data['suspension_reasons'],
        google_data['purchase_order_id'],
        calculate_period(
            subscription['billing']['period']['delta'],
            subscription['billing']['period']['uom'],
        ) if 'billing' in subscription else '-',
        subscription.get('billing', {}).get('anniversary', {}).get('day', '-'),
        subscription.get('billing', {}).get('anniversary', {}).get('month', '-'),
        subscription['contract']['id'] if 'contract' in subscription else '-',
        subscription['contract']['name'] if 'contract' in subscription else '-',
        get_value(subscription.get('tiers', ''), 'customer', 'id'),
        get_value(subscription.get('tiers', ''), 'customer', 'name'),
        get_value(subscription.get('tiers', ''), 'customer', 'external_id'),
        get_value(subscription.get('tiers', ''), 'tier1', 'id'),
        get_value(subscription.get('tiers', ''), 'tier1', 'name'),
        get_value(subscription.get('tiers', ''), 'tier1', 'external_id'),
        get_value(subscription.get('tiers', ''), 'tier2', 'id'),
        get_value(subscription.get('tiers', ''), 'tier2', 'name'),
        get_value(subscription.get('tiers', ''), 'tier2', 'external_id'),
        get_value(subscription['connection'], 'provider', 'id'),
        get_value(subscription['connection'], 'provider', 'name'),
        get_value(subscription['connection'], 'vendor', 'id'),
        get_value(subscription['connection'], 'vendor', 'name'),
        get_value(subscription, 'product', 'id'),
        get_value(subscription, 'product', 'name'),
        get_value(subscription['connection'], 'hub', 'id'),
        get_value(subscription['connection'], 'hub', 'name'),
        google_data['error'],
    )


def get_google_parameter(value, params):
    try:
        return list(filter(lambda param: param['name'] == value, params))[0]
    except (IndexError, KeyError, TypeError):
        return {}


def get_entitlement_status(value):
    if value == 0:
        return "unspecified"
    if value == 1:
        return "active"
    if value == 5:
        return "suspended"
    return '-'


def get_suspension_reasons(value):
    if value == 0:
        return 'SUSPENSION_REASON_UNSPECIFIED'
    if value == 1:
        return 'RESELLER_INITIATED'
    if value == 2:
        return 'TRIAL_ENDED'
    if value == 3:
        return 'RENEWAL_WITH_TYPE_CANCEL'
    if value == 4:
        return 'PENDING_TOS_ACCEPTANCE'
    if value == 100:
        return 'OTHER '
    return '-'


def get_entitlement_id(params):
    param_value = parameter_value_by_name('entitlement_id', params, "")
    if not param_value:
        return param_value
    entitlement_id = param_value.strip('["]')
    return entitlement_id
