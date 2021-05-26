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
        self.level_step_perc = int(config['LEVEL_STEP_PERCENTAGE'])
        self.logger = logger

    def __getattr__(self, name):
        if name.upper() in self.VERBS:
            def method(*args, **kwargs):
                return self.make_request(name.upper(), *args, **kwargs)
            return method
        return object.__getattribute__(self, name)

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
        if resp.status_code != 200:
            self.logger.error(resp.text)
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

    def get_fiat_balance(self):
        balances = self.get('account/balances')
        total = next(
            account
            for account in balances
            if account['currency'] == self.fiat_currency_code
        )['total']
        return Decimal(total)

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
