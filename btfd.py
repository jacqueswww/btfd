import configparser
import datetime
import re
import threading
import time
import math

from decimal import Decimal

from loguru import logger
from valr_api import VALR_API


logger.add("btfd.log", rotation="1 day")


BACKENDS = {
    'valr': VALR_API
}

td_re = re.compile(r'(^[0-9]+)([h|m|s|d])')
unit_map = {
    's': 1,
    'm': 60,
    'h': 60 * 60,
    'd': 24 * 60 * 60,
}


def get_time_in_seconds(input_str):
    m = td_re.match(input_str)
    num, unit = m.groups()
    return int(num) * unit_map[unit]


def calculate_position_sizing(balance, no_of_levels):
    # Double position size the lower you go.
    levels = [2**i for i in range(no_of_levels)]
    total_position_weights = sum(levels)
    position_size = Decimal(balance) / total_position_weights
    return [i*position_size for i in levels]


@logger.catch
def run_strategy(strategy_name, strategy_config, backend):
    logger.info('Number of levels: {}', backend.no_of_levels)

    while True:
        logger.info('({}) Closing All Open Positions', strategy_name)
        # balance = round(backend.get_fiat_balance(), 2)
        balance = 100
        position_sizes = calculate_position_sizing(balance, backend.no_of_levels)
        pair = backend.crypto_currency_code + backend.fiat_currency_code
        from_date = (datetime.datetime.now() - datetime.timedelta(days=8))
        to_date = datetime.datetime.now()
        history_ohlc = backend.get_daily_ohlc(pair, from_date, to_date)
        market_summary = backend.get_market_summary(pair)
        history_ohlc.insert(0, {
            'startTime': market_summary['created'],
            'high': market_summary['highPrice'],
            'close': market_summary['lastTradedPrice'],
            'low': market_summary['lowPrice']
        })

        # for day in history_ohlc:
        #     logger.info('{} - {}', day['startTime'], day['close'])

        avg_ohlc_price = sum([
            (Decimal(day['high']) + Decimal(day['low'])) / 2
            for day in history_ohlc]) / len(history_ohlc
        )
        avg_ohlc_price = round(avg_ohlc_price)

        logger.info('({}) Current Balance: {}', strategy_name, balance)
        logger.info('({}) Position Sizes: {}', strategy_name, position_sizes)
        logger.info('({}) Average Daily Price: {}', strategy_name, avg_ohlc_price)

        step_value = round(avg_ohlc_price * (Decimal(backend.level_step_perc) / 100))
        positions = [
            [avg_ohlc_price - (i * step_value), position_sizes[i]]
            for i in range(backend.no_of_levels)
        ]
        # logger.info(positions)

        for price, size in positions:
            logger.info(
                '({}) {} {} @ {} {}', strategy_name, size, backend.fiat_currency_code, price,
                backend.fiat_currency_code
            )

        # import ipdb; ipdb.set_trace()
        # for level in range(backend.no_of_levels):
        #     logger.info('({}) {}', strategy_name, level)

        time.sleep(
            get_time_in_seconds(backend.sleep_duration)
        )


@logger.catch
def main(config):
    for strategy_name in config.sections():
        backend_name = config.get(strategy_name, 'BACKEND')
        if backend_name not in BACKENDS:
            raise Exception('Invalid backend', backend_name)
        backend_config = config[strategy_name]
        backend = BACKENDS[backend_name](backend_config, logger)
        run_strategy(strategy_name, config[strategy_name], backend)


if __name__ == '__main__':
    config = configparser.ConfigParser()
    config.read('./config.ini')
    main(config)
