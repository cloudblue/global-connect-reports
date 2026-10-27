from datetime import datetime


def convert_to_datetime(param_value):
    if param_value == "" or param_value == "-" or param_value is None:
        return "-"

    return datetime.strptime(
        param_value.replace("T", " ").replace("+00:00", ""),
        "%Y-%m-%d %H:%M:%S",
    )


def convert_to_date(param_value):
    if param_value == "" or param_value == "-" or param_value is None:
        return "-"

    return datetime.strptime(
        param_value.replace("T", " ").replace("+00:00", ""),
        "%Y-%m-%d",
    )


def today_str():
    return datetime.today().strftime('%Y-%m-%d %H:%M:%S')


def get_basic_value(base, value):
    if base and value in base:
        return base[value]
    return '-'


def get_value(base, prop, value):
    if prop in base:
        return get_basic_value(base[prop], value)
    return '-'


def get_param_value(params: list, value: str) -> str:
    try:
        if params[0]['id'] == value:
            return params[0]['value']
        if params[0]['name'] == value:
            return params[0]['value']
        if len(params) == 1:
            return '-'
        return get_param_value(list(params[1:]), value)
    except Exception:
        return '-'


def get_first_day_month(date: datetime):
    return datetime(date.year, date.month, 1, 0, 0, 0)


def get_next_month_anniversary(date: datetime):
    if date.month == 12:
        return datetime(date.year + 1, 1, date.day, 0, 0, 0)
    if date.month == 1 and date.day > 28:
        return datetime(date.year, date.month + 1, 28, 0, 0, 0)
    if date.day > 30 and (date.month == 3 or date.month == 5 or date.month == 8 or date.month == 10):
        return datetime(date.year, date.month + 1, 30, 0, 0, 0)
    return datetime(date.year, date.month + 1, date.day, 0, 0, 0)


def get_next_year_anniversary(date: datetime, years_to_add):
    if date.month == 2 and date.day == 29:
        return datetime(date.year + years_to_add, date.month, 28, 0, 0, 0)
    return datetime(date.year + years_to_add, date.month, date.day, 0, 0, 0)


class MonthlyBillingItem:
    def __init__(self, item_mpn, item_period, item_display_name, quantity, unit_msrp, unit_cost, msrp, cost):
        self.Item_mpn = item_mpn
        self.Period = item_period
        self.Item_name = item_display_name
        self.Quantity = quantity
        self.Unit_Cost = unit_cost
        self.Unit_Msrp = unit_msrp
        self.Msrp = msrp
        self.Cost = cost


def get_usage_record_param_value(params: list, value: str) -> str:
    try:
        if params[0]['parameter_name'] == value:
            return params[0]['parameter_value']
        if len(params) == 1:
            return '-'
    except Exception:
        return '-'


def parameter_value(parameter_id, parameter_list, default="-"):
    try:
        parameter = list(filter(lambda param: param['id'] == parameter_id, parameter_list))[0]
        return parameter['value']
    except IndexError:
        return default


def parameter_value_by_name(parameter_name, parameter_list, default="-"):
    try:
        parameter = list(filter(lambda param: param['name'] == parameter_name, parameter_list))[0]
        return parameter['value']
    except IndexError:
        return default


def get_price(price_data):
    if not price_data:
        return '-'
    nanos = price_data.get('nanos')
    units = price_data.get('units')
    currency = price_data.get('currency_code')
    total = float(units) + float(nanos) / 10 ** 9

    return "{:0.2f} {}".format(total, currency)
