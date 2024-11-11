import time
import hashlib
import hmac
import requests
import json
import calendar

from requests.auth import HTTPBasicAuth

from urllib.parse import urlparse
from datetime import datetime
from decimal import Decimal


class LUNO_API:
    VERBS = [
        'POST',
        'PATCH',
        'DELETE',
        'GET',
    ]
    BASE_URL = 'https://api.luno.com/api/'

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

    def get_headers(self):
        return {
            'Content-Type': 'application/json',
        }

    def make_request(self, verb, path, data=None, params=None):
        final_url = self.BASE_URL + path

        headers = self.get_headers()
        resp = getattr(requests, verb.lower())(
            final_url,
            data=json.dumps(data) if data else "",
            params=params,
            headers=headers,
            auth=(self.api_key, self.api_secret)
        )

        if resp.status_code not in (200, 201, 202):
            self.logger.error("{}: {}", str(resp.status_code), str(resp.text))

        if not resp.text and resp.status_code == 200:
            return True
        return resp.json()

    def get_pair(self):
        return self.crypto_currency_code + self.fiat_currency_code

    def get_all_open_order_ids(self, pair=None):
        res = self.get(
            'exchange/2/listorders',
            params={'state': 'PENDING'}
        )
        orders = res['orders']
        if pair:
            orders = [
                order for order in orders
                if order['pair'] == pair
            ]
        return [
            order['order_id']
            for order in orders
        ]

    def get_usable_fiat_balance(self):
        res = self.get('1/balance')
        fiat_info = next(
            x
            for x in res['balance']
            if x['asset'] == self.fiat_currency_code
        )
        return self.balance_limit * Decimal(fiat_info['balance']) - Decimal(fiat_info['reserved'])

    def get_daily_ohlc(self, pair, from_dt, to_dt):
        params = {
            'pair': pair,
            'since': int(from_dt.timestamp() * 1000),
            'duration': 86400,
        }
        res = self.get('exchange/1/candles', params=params)

        return res['candles']

    def get_market_summary(self, pair):
        res = self.get(f'1/tickers', params={'pair': pair})
        info = res['tickers'][0]
        return {
            'created': info['timestamp'],
            'highPrice': info['ask'],
            'lowPrice': info['bid'],
            'lastTradedPrice': info['last_trade']
        }

    def place_buy_order(self, pair, price, quantity):
        payload = {
            "type": "BID",
            "volume": str(quantity),
            "price": str(price),
            "pair": pair,
            "timestamp": int(time.time() * 1000)
        }
        res = self.post(
            '/1/postorder',
            params=payload
        )
        return res

    def close_order(self, pair, order_id):
        # https://api.luno.com/api/1/stoporder
        payload = {
            "order_id": order_id
        }
        res = self.post('1/stoporder', params=payload)
        return res
