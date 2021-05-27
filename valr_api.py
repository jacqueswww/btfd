import time
import hashlib
import hmac
import requests
import json
import calendar

from urllib.parse import urlparse
from datetime import datetime
from decimal import Decimal


class VALR_API:
    VERBS = [
        'POST',
        'PATCH',
        'DELETE',
        'GET',
    ]
    BASE_URL = 'https://api.valr.com/v1/'

    def __init__(self, config, logger):
        self.api_key = config['API_KEY']
        self.api_secret = config['API_SECRET']
        self.sleep_duration = config['RESTRUCTURE_TIME']
        self.fiat_currency_code = config['FIAT_CURRENCY_CODE']
        self.crypto_currency_code = config['CRYPTO_CURRENCY_CODE']
        self.no_of_levels = int(config['ICEBERG_LEVELS'])
        self.level_step_perc = Decimal(config['LEVEL_STEP_PERCENTAGE'])
        self.min_order_size = Decimal(config['MINIMUM_ORDER_SIZE'])
        self.quantity_precision = int(config['QUANTITY_PRECISION'])
        self.iceberg_multiple = Decimal(config['ICEBERG_MULTIPLE'])
        self.balance_limit = Decimal(config['BALANCE_LIMIT'])
        self.logger = logger

    def __getattr__(self, name):
        if name.upper() in self.VERBS:
            def method(*args, **kwargs):
                return self.make_request(name.upper(), *args, **kwargs)
            return method
        return object.__getattribute__(self, name)

    def get_pair(self):
        return self.crypto_currency_code + self.fiat_currency_code

    def get_headers(self, timestamp, signature):
        return {
            'Content-Type': 'application/json',
            'X-VALR-API-KEY': self.api_key,
            'X-VALR-SIGNATURE': signature,
            'X-VALR-TIMESTAMP': str(timestamp),
        }

    def make_request(self, verb, path, data=None, params=None):
        timestamp = int(time.time()*1000)
        final_url = self.BASE_URL + path
        signature = self.sign_request(
            timestamp=timestamp,
            verb=verb.upper(),
            path=urlparse(final_url).path,
            body=data
        )
        headers = self.get_headers(timestamp, signature)
        resp = getattr(requests, verb.lower())(
            final_url,
            data=json.dumps(data) if data else "",
            params=params,
            headers=headers,
        )
        if resp.status_code not in (200, 201, 202):
            self.logger.error("{}{}", resp.status_code, resp.text)

        if not resp.text and resp.status_code == 200:
            return True

        return resp.json()

    def sign_request(self, timestamp, verb, path, body):
        """Signs the request payload using the api key secret
        api_key_secret - the api key secret
        timestamp - the unix timestamp of this request e.g. int(time.time()*1000)
        verb - Http verb - GET, POST, PUT or DELETE
        path - path excluding host name, e.g. '/v1/withdraw
        body - http request body as a string, optional
        """
        body = "" if not body else json.dumps(body)
        payload = "{}{}{}{}".format(timestamp,verb.upper(),path,body)
        message = bytearray(payload,'utf-8')
        signature = hmac.new(
            bytearray(self.api_secret,'utf-8'), message, digestmod=hashlib.sha512
        ).hexdigest()
        return signature

    def get_usable_fiat_balance(self):
        balances = self.get('account/balances')
        total = next(
            account
            for account in balances
            if account['currency'] == self.fiat_currency_code
        )['total']
        return Decimal(total) * self.balance_limit

    def get_market_summary(self, pair):
        res = self.get(f'public/{pair}/marketsummary')
        return res

    def get_daily_ohlc(self, pair, from_dt, to_dt):
        url = f'https://api.valr.com/{pair}/buckets'
        params = {
            'startTime': int(time.mktime(from_dt.timetuple())),
            'endTime': int(time.mktime(to_dt.timetuple())),
            'periodSeconds': 86400
        }
        res = requests.get(url, params=params)

        if res.status_code != 200:
            self.logger.error(res.text)

        return res.json()

    def get_all_open_order_ids(self, pair=None):
        orders = self.get('orders/open')
        if pair:
            orders = [
                order for order in orders
                if order['currencyPair'] == pair
            ]
        return [
            order['orderId']
            for order in orders
        ]

    def close_order(self, pair, order_id):
        payload = {
            "pair": pair,
            "orderId": order_id
        }
        res = self.delete('orders/order', data=payload)
        return res

    def place_buy_order(self, pair, price, quantity):
        payload = {
            "side": "BUY",
            "quantity": str(quantity),
            "price": str(price),
            "pair": pair,
        }
        res = self.post(
            'orders/limit',
            data=payload
        )
        return res

# curl --location --request POST 'https://api.valr.com/v1/orders/limit' \
# --header 'Content-Type: application/json' \
# --header 'X-VALR-API-KEY: yourApiKey' \
# --header 'X-VALR-SIGNATURE: e6669da57358f6b838f83f5ea5118a9ec39f71ae9018b9e4a1e0690fd3361208a4b0be4c84966792f302b600a69cf82c257722774a44ac1850570cfedd6053c4' \
# --header 'X-VALR-TIMESTAMP: 1560007630778' \
# --data-raw '{
#     "side": "SELL",
#     "quantity": "0.100000",
#     "price": "10000",
#     "pair": "BTCZAR",
#     "postOnly": true,
#     "customerOrderId": "1235"
# }'
