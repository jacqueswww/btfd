import configparser
import re
import threading
import time

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
    levels = [2*i for i in range(1, no_of_levels)]
    total_position_weights = sum(levels)
    position_size = round(balance/total_position_weights, 2)
    return [i*position_size for i in levels]


@logger.catch
def run_strategy(strategy_name, strategy_config, backend):
    logger.info('Number of levels: {}', backend.no_of_levels)

    while True:
        logger.info('({}) Closing All Open Positions', strategy_name)
        balance = round(backend.get_fiat_balance(), 2)
        position_sizes = calculate_position_sizing(balance, backend.no_of_levels)
        logger.info('({}) Current Balance: {}', strategy_name, balance)
        logger.info('({}) Position Sizes: {}', strategy_name, position_sizes)
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
