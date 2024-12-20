import configparser
import datetime
import math
import re
import signal
import threading
import time

from decimal import Decimal

from loguru import logger
from valr_api import VALR_API
from luno_api import LUNO_API

class Shutdown(Exception):
    pass


logger.add("btfd.log", rotation="1 day")

shutdown_flag = threading.Event()

BACKENDS = {
    'valr': VALR_API,
    'luno': LUNO_API
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


def calculate_position_sizing(balance, no_of_levels, iceberg_multiple):
    # Double position size the lower you go.
    levels = [Decimal(iceberg_multiple)**i for i in range(no_of_levels)]
    total_position_weights = sum(levels)
    position_size = Decimal(balance) / total_position_weights
    return [i*position_size for i in levels]


@logger.catch
def run_strategy(strategy_name, strategy_config, backend):
    logger.info('Number of levels: {}', backend.no_of_levels)
    sleep_duration_seconds = get_time_in_seconds(backend.sleep_duration)
    last_run_ts = None
    pair = backend.get_pair()

    while not shutdown_flag.is_set():

        if last_run_ts is not None:
            last_run_delta_s = time.time() - last_run_ts
            if last_run_delta_s < sleep_duration_seconds:
                time.sleep(1)
                continue

        logger.info('({}) Closing All Open Positions', strategy_name)
        order_ids = backend.get_all_open_order_ids(pair)
        for order_id in order_ids:
            logger.info('({}) Closing Order {}', strategy_name, order_id)
            logger.info('({}) {}', strategy_name, backend.close_order(pair, order_id))

        # ~~ Start Strategy
        balance = round(backend.get_usable_fiat_balance(), 2)
        position_sizes = calculate_position_sizing(balance, backend.no_of_levels, backend.iceberg_multiple)
        from_date = (datetime.datetime.now() - datetime.timedelta(days=8))
        to_date = datetime.datetime.now()
        history_ohlc = backend.get_daily_ohlc(pair, from_date, to_date)

        market_summary = backend.get_market_summary(pair)
        last_traded_price = Decimal(market_summary['lastTradedPrice'])
        history_ohlc.insert(0, {
            'startTime': market_summary['created'],
            'high': market_summary['highPrice'],
            'close': last_traded_price,
            'open':last_traded_price,
            'low': market_summary['lowPrice']
        })

        avg_ohlc_price = sum([
            (Decimal(day['high']) + Decimal(day['low']) + Decimal(day['close']) + Decimal(day['open'])) / 4
            for day in history_ohlc]) / len(history_ohlc
        )

        avg_ohlc_price = round(avg_ohlc_price)

        if avg_ohlc_price >= last_traded_price:
            avg_ohlc_price = round(Decimal('0.99') * last_traded_price)

        logger.info('({}) Current Balance: {}', strategy_name, balance)
        # logger.info('({}) Position Sizes: {}', strategy_name, position_sizes)
        logger.info('({}) Base Price: {}', strategy_name, avg_ohlc_price)

        step_value = math.floor(avg_ohlc_price * (Decimal(backend.level_step_perc) / 100))
        positions = [
            [avg_ohlc_price - (i * step_value), position_sizes[i]]
            for i in range(backend.no_of_levels)
        ]

        logger.info('Placing positions: ')
        for price, size in positions:
            final_size = math.floor(size)
            quantity = math.floor(size/price * 10**backend.quantity_precision) / 10**backend.quantity_precision
            final_size = quantity * price
            if quantity < Decimal(backend.min_order_size):
                logger.error('({}) Position {} @ {} too small, skipping.', strategy_name, round(size/price, 6), price)
                continue

            logger.info(
                '({}) {quantity} {crypto_currency_code} @ {price} {fiat_currency_code} = {size}',
                strategy_name,
                quantity=quantity,
                crypto_currency_code=backend.crypto_currency_code,
                fiat_currency_code=backend.fiat_currency_code,
                size=final_size,
                price=price
            )

            backend.place_buy_order(
                pair=pair,
                quantity=quantity,
                price=price
            )

        last_run_ts = time.time()


def sigterm_handler(signum, frame):
    raise Shutdown()


@logger.catch
def main(config):

    signal.signal(signal.SIGTERM, sigterm_handler)
    signal.signal(signal.SIGINT, sigterm_handler)

    threads = []
    try:
        for strategy_name in config.sections():
            backend_name = config.get(strategy_name, 'BACKEND')
            if backend_name not in BACKENDS:
                raise Exception('Invalid backend', backend_name)
            backend_config = config[strategy_name]
            backend = BACKENDS[backend_name](backend_config, logger)

            t = threading.Thread(
                target=run_strategy,
                args=(strategy_name, config[strategy_name], backend)
            )
            threads.append(t)
            t.start()
            time.sleep(10)
    except Shutdown:
        shutdown_flag.set()
        for t in threads:
            t.join()


if __name__ == '__main__':
    config = configparser.ConfigParser()
    config.read('./config.ini')
    main(config)
