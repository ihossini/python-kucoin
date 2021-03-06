import base64
import calendar
import hashlib
import hmac
import time
from datetime import datetime

import requests

from .exceptions import (
    KucoinAPIException, KucoinRequestException, MarketOrderException, LimitOrderException
)
from .utils import compact_json_dict, flat_uuid


class Client(object):

    REST_API_URL = 'https://openapi-v2.kucoin.com'
    SANDBOX_API_URL = 'https://openapi-sandbox.kucoin.com'
    API_VERSION = 'v1'

    SIDE_BUY = 'buy'
    SIDE_SELL = 'sell'

    ACCOUNT_MAIN = 'main'
    ACCOUNT_TRADE = 'trade'

    ORDER_LIMIT = 'limit'
    ORDER_MARKET = 'market'
    ORDER_LIMIT_STOP = 'limit_stop'
    ORDER_MARKET_STOP = 'market_stop'

    STOP_LOSS = 'loss'
    STOP_ENTRY = 'entry'

    STP_CANCEL_NEWEST = 'CN'
    STP_CANCEL_OLDEST = 'CO'
    STP_DECREASE_AND_CANCEL = 'DC'
    STP_CANCEL_BOTH = 'CB'

    TIMEINFORCE_GOOD_TILL_CANCELLED = 'GTC'
    TIMEINFORCE_GOOD_TILL_TIME = 'GTT'
    TIMEINFORCE_IMMEDIATE_OR_CANCEL = 'IOC'
    TIMEINFORCE_FILL_OR_KILL = 'FOK'

    def __init__(self, api_key, api_secret, passphrase, sandbox=False, requests_params=None):
        # https://docs.kucoin.com/

        self.API_KEY = api_key
        self.API_SECRET = api_secret
        self.API_PASSPHRASE = passphrase
        if sandbox:
            self.API_URL = self.SANDBOX_API_URL
        else:
            self.API_URL = self.REST_API_URL

        self._requests_params = requests_params
        self.session = self._init_session()

    def test(self):
        return "This is a test"

    def _init_session(self):

        session = requests.session()
        headers = {'Accept': 'application/json',
                   'User-Agent': 'python-kucoin',
                   'Content-Type': 'application/json',
                   'KC-API-KEY': self.API_KEY,
                   'KC-API-PASSPHRASE': self.API_PASSPHRASE}
        session.headers.update(headers)
        return session

    @staticmethod
    def _get_params_for_sig(data):
        """Convert params to ordered string for signature

        :param data:
        :return: ordered parameters like amount=10&price=1.1&type=BUY

        """
        return '&'.join(["{}={}".format(key, data[key]) for key in data])

    def _generate_signature(self, nonce, method, path, data):
        # Generate the call signature

        data_json = ""
        endpoint = path
        if method == "get":
            if data:
                query_string = self._get_params_for_sig(data)
                endpoint = "{}?{}".format(path, query_string)
        elif data:
            data_json = compact_json_dict(data)
        sig_str = ("{}{}{}{}".format(nonce, method.upper(), endpoint, data_json)).encode('utf-8')
        m = hmac.new(self.API_SECRET.encode('utf-8'), sig_str, hashlib.sha256)
        return base64.b64encode(m.digest())

    def _create_path(self, path):
        return '/api/{}/{}'.format(self.API_VERSION, path)

    def _create_uri(self, path):
        return '{}{}'.format(self.API_URL, path)

    def _request(self, method, path, signed, **kwargs):

        # set default requests timeout
        kwargs['timeout'] = 10

        # add our global requests params
        if self._requests_params:
            kwargs.update(self._requests_params)

        kwargs['data'] = kwargs.get('data', {})
        kwargs['headers'] = kwargs.get('headers', {})

        full_path = self._create_path(path)
        uri = self._create_uri(full_path)

        if signed:
            # generate signature
            nonce = int(time.time() * 1000)
            kwargs['headers']['KC-API-TIMESTAMP'] = str(nonce)
            kwargs['headers']['KC-API-SIGN'] = self._generate_signature(nonce, method, full_path, kwargs['data'])

        if kwargs['data'] and method == 'get':
            kwargs['params'] = kwargs['data']
            del(kwargs['data'])

        if signed and method != 'get' and kwargs['data']:
            kwargs['data'] = compact_json_dict(kwargs['data'])

        response = getattr(self.session, method)(uri, **kwargs)
        return self._handle_response(response)

    @staticmethod
    def _handle_response(response):
        """Internal helper for handling API responses from the KuCoin server.
        Raises the appropriate exceptions when necessary; otherwise, returns the
        response.
        """

        if not str(response.status_code).startswith('2'):
            raise KucoinAPIException(response)
        try:
            res = response.json()

            if 'code' in res and res['code'] != "200000":
                raise KucoinAPIException(response)

            if 'success' in res and not res['success']:
                raise KucoinAPIException(response)

            # by default return full response
            # if it's a normal response we have a data attribute, return that
            if 'data' in res:
                res = res['data']
            return res
        except ValueError:
            raise KucoinRequestException('Invalid Response: %s' % response.text)

    def _get(self, path, signed=False, **kwargs):
        return self._request('get', path, signed, **kwargs)

    def _post(self, path, signed=False, **kwargs):
        return self._request('post', path, signed, **kwargs)

    def _put(self, path, signed=False, **kwargs):
        return self._request('put', path, signed, **kwargs)

    def _delete(self, path, signed=False, **kwargs):
        return self._request('delete', path, signed, **kwargs)

    def get_timestamp(self):
        # https://docs.kucoin.com/#time

        return self._get("timestamp")

    # Currency Endpoints

    def get_currencies(self):
        # https://docs.kucoin.com/#get-currencies

        return self._get('currencies', False)

    def get_currency(self, currency):
        # https://docs.kucoin.com/#get-currency-detail

        return self._get('currencies/{}'.format(currency), False)

    # User Account Endpoints

    def get_accounts(self, currency=None):
        # https://docs.kucoin.com/#accounts

        data = {}

        if currency:
            data['currency'] = currency

        return self._get('accounts', True, data=data)

    def get_account(self, account_id):
        # https://docs.kucoin.com/#get-an-account

        return self._get('accounts/{}'.format(account_id), True)

    def create_account(self, account_type, currency):
        # https://docs.kucoin.com/#create-an-account

        data = {
            'type': account_type,
            'currency': currency
        }

        return self._post('accounts', True, data=data)

    def get_account_activity(self, account_id, start=None, end=None, page=None, limit=None):
        # https://docs.kucoin.com/#get-account-history

        data = {}
        if start:
            data['startAt'] = start
        if end:
            data['endAt'] = end
        if page:
            data['currentPage'] = page
        if limit:
            data['pageSize'] = limit

        return self._get('accounts/{}/ledgers'.format(account_id), True, data=data)

    def get_account_holds(self, account_id, page=None, page_size=None):
        # https://docs.kucoin.com/#get-holds

        data = {}
        if page:
            data['currentPage'] = page
        if page_size:
            data['pageSize'] = page_size

        return self._get('accounts/{}/holds'.format(account_id), True, data=data)

    def create_inner_transfer(self, from_account_id, to_account_id, amount, order_id=None):
        # https://docs.kucoin.com/#get-holds

        data = {
            'payAccountId': from_account_id,
            'recAccountId': to_account_id,
            'amount': amount
        }

        if order_id:
            data['clientOid'] = order_id
        else:
            data['clientOid'] = flat_uuid()

        return self._post('accounts/inner-transfer', True, data=data)

    # Deposit Endpoints

    def create_deposit_address(self, currency):
        # https://docs.kucoin.com/#create-deposit-address

        data = {
            'currency': currency
        }

        return self._post('deposit-addresses', True, data=data)

    def get_deposit_address(self, currency):
        # https://docs.kucoin.com/#get-deposit-address

        data = {
            'currency': currency
        }

        return self._get('deposit-addresses', True, data=data)

    def get_deposits(self, currency=None, status=None, start=None, end=None, page=None, limit=None):
       # https://docs.kucoin.com/#get-deposit-list

        data = {}
        if currency:
            data['currency'] = currency
        if status:
            data['status'] = status
        if start:
            data['startAt'] = start
        if end:
            data['endAt'] = end
        if limit:
            data['pageSize'] = limit
        if page:
            data['page'] = page

        return self._get('deposits', True, data=data)

    # Withdraw Endpoints

    def get_withdrawals(self, currency=None, status=None, start=None, end=None, page=None, limit=None):
        # https://docs.kucoin.com/#get-withdrawals-list

        data = {}
        if currency:
            data['currency'] = currency
        if status:
            data['status'] = status
        if start:
            data['startAt'] = start
        if end:
            data['endAt'] = end
        if limit:
            data['pageSize'] = limit
        if page:
            data['page'] = page

        return self._get('withdrawals', True, data=data)

    def get_withdrawal_quotas(self, currency):
        # https://docs.kucoin.com/#get-withdrawal-quotas

        data = {
            'currency': currency
        }

        return self._get('withdrawals/quotas', True, data=data)

    def create_withdrawal(self, currency, amount, address, memo=None, is_inner=False, remark=None):
        # https://docs.kucoin.com/#apply-withdraw

        data = {
            'currency': currency,
            'amount': amount,
            'address': address
        }

        if memo:
            data['memo'] = memo
        if is_inner:
            data['isInner'] = is_inner
        if remark:
            data['remark'] = remark

        return self._post('withdrawals', True, data=data)

    def cancel_withdrawal(self, withdrawal_id):
        # https://docs.kucoin.com/#cancel-withdrawal

        return self._delete('withdrawals/{}'.format(withdrawal_id), True)

    # Order Endpoints

    def create_market_order(self, symbol, side, size=None, funds=None, client_oid=None, remark=None, stp=None):
        # https://docs.kucoin.com/#place-a-new-order

        if not size and not funds:
            raise MarketOrderException('Need size or fund parameter')

        if size and funds:
            raise MarketOrderException('Need size or fund parameter not both')

        data = {
            'side': side,
            'symbol': symbol,
            'type': self.ORDER_MARKET
        }

        if size:
            data['size'] = size
        if funds:
            data['funds'] = funds
        if client_oid:
            data['clientOid'] = client_oid
        else:
            data['clientOid'] = flat_uuid()
        if remark:
            data['remark'] = remark
        if stp:
            data['stp'] = stp

        return self._post('orders', True, data=data)

    def create_limit_order(self, symbol, side, price, size, client_oid=None, remark=None,
                           time_in_force=None, stop=None, stop_price=None, stp=None, cancel_after=None, post_only=None,
                           hidden=None, iceberg=None, visible_size=None):
        # https://docs.kucoin.com/#place-a-new-order

        if stop and not stop_price:
            raise LimitOrderException('Stop order needs stop_price')

        if stop_price and not stop:
            raise LimitOrderException('Stop order type required with stop_price')

        if cancel_after and time_in_force != self.TIMEINFORCE_GOOD_TILL_TIME:
            raise LimitOrderException('Cancel after only works with time_in_force = "GTT"')

        if hidden and iceberg:
            raise LimitOrderException('Order can be either "hidden" or "iceberg"')

        if iceberg and not visible_size:
            raise LimitOrderException('Iceberg order requires visible_size')

        data = {
            'symbol': symbol,
            'side': side,
            'type': self.ORDER_LIMIT,
            'price': price,
            'size': size
        }

        if client_oid:
            data['clientOid'] = client_oid
        else:
            data['clientOid'] = flat_uuid()
        if remark:
            data['remark'] = remark
        if stp:
            data['stp'] = stp
        if time_in_force:
            data['timeInForce'] = time_in_force
        if cancel_after:
            data['cancelAfter'] = cancel_after
        if post_only:
            data['postOnly'] = post_only
        if stop:
            data['stop'] = stop
            data['stopPrice'] = stop_price
        if hidden:
            data['hidden'] = hidden
        if iceberg:
            data['iceberg'] = iceberg
            data['visible_size'] = visible_size

        return self._post('orders', True, data=data)

    def cancel_order(self, order_id):
        # https://docs.kucoin.com/#cancel-an-order

        return self._delete('orders/{}'.format(order_id), True)

    def cancel_all_orders(self, symbol=None):
        # https://docs.kucoin.com/#cancel-all-orders

        data = {}
        if symbol is not None:
            data['symbol'] = symbol
        return self._delete('orders', True, data=data)

    def get_orders(self, symbol=None, status=None, side=None, order_type=None,
                   start=None, end=None, page=None, limit=None):
        # https://docs.kucoin.com/#list-orders

        data = {}

        if symbol:
            data['symbol'] = symbol
        if status:
            data['status'] = status
        if side:
            data['side'] = side
        if order_type:
            data['type'] = order_type
        if start:
            data['startAt'] = start
        if end:
            data['endAt'] = end
        if page:
            data['page'] = page
        if limit:
            data['pageSize'] = limit

        return self._get('orders', True, data=data)

    def get_historical_orders(self, symbol=None, side=None,
                              start=None, end=None, page=None, limit=None):
        # https://docs.kucoin.com/#get-v1-historical-orders-list

        data = {}

        if symbol:
            data['symbol'] = symbol
        if side:
            data['side'] = side
        if start:
            data['startAt'] = start
        if end:
            data['endAt'] = end
        if page:
            data['page'] = page
        if limit:
            data['pageSize'] = limit

        return self._get('hist-orders', True, data=data)

    def get_order(self, order_id):
        # https://docs.kucoin.com/#get-an-order

        return self._get('orders/{}'.format(order_id), True)

    # Fill Endpoints

    def get_fills(self, order_id=None, symbol=None, side=None, order_type=None,
                  start=None, end=None, page=None, limit=None):
        # https://docs.kucoin.com/#list-fills

        data = {}

        if order_id:
            data['orderId'] = order_id
        if symbol:
            data['symbol'] = symbol
        if side:
            data['side'] = side
        if order_type:
            data['type'] = order_type
        if start:
            data['startAt'] = start
        if end:
            data['endAt'] = end
        if page:
            data['page'] = page
        if limit:
            data['pageSize'] = limit

        return self._get('fills', True, data=data)

    # Market Endpoints

    def get_symbols(self):
        # https://docs.kucoin.com/#symbols-amp-ticker

        return self._get('symbols', False)

    def get_ticker(self, symbol=None):
        # https://docs.kucoin.com/#get-ticker

        data = {}
        tick_path = 'market/allTickers'
        if symbol is not None:
            tick_path = 'market/orderbook/level1'
            data = {
                'symbol': symbol
            }
        return self._get(tick_path, False, data=data)

    def get_fiat_prices(self, base=None, symbol=None):
        # https://docs.kucoin.com/#get-fiat-price

        data = {}

        if base is not None:
            data['base'] = base
        if symbol is not None:
            data['currencies'] = symbol

        return self._get('prices', False, data=data)

    def get_24hr_stats(self, symbol):
        # Get 24hr stats for a symbol. Volume is in base currency units. open, high, low are in quote currency units.

        data = {
            'symbol': symbol
        }

        return self._get('market/stats', False, data=data)

    def get_markets(self):
        # https://docs.kucoin.com/#get-market-list

        return self._get('markets', False)

    def get_order_book(self, symbol):
        # https://docs.kucoin.com/#get-part-order-book-aggregated

        data = {
            'symbol': symbol
        }

        return self._get('market/orderbook/level2_100', False, data=data)

    def get_full_order_book(self, symbol):
        # https://docs.kucoin.com/#get-full-order-book-aggregated

        data = {
            'symbol': symbol
        }

        return self._get('market/orderbook/level2', False, data=data)

    def get_full_order_book_level3(self, symbol):
        # https://docs.kucoin.com/#get-full-order-book-atomic

        data = {
            'symbol': symbol
        }

        return self._get('market/orderbook/level3', False, data=data)

    def get_trade_histories(self, symbol):
        # https://docs.kucoin.com/#get-trade-histories

        data = {
            'symbol': symbol
        }

        return self._get('market/histories', False, data=data)

    def get_kline_data(self, symbol, kline_type='5min', start=None, end=None):
        # https://docs.kucoin.com/#get-historic-rates

        data = {
            'symbol': symbol
        }

        if kline_type is not None:
            data['type'] = kline_type
        if start is not None:
            data['startAt'] = start
        else:
            data['startAt'] = calendar.timegm(datetime.utcnow().date().timetuple())
        if end is not None:
            data['endAt'] = end
        else:
            data['endAt'] = int(time.time())

        return self._get('market/candles', False, data=data)

    # Lending Endpoints

    def get_lending_orderbook(self, currency):
        # https://docs.kucoin.com/#lending-market-data

        data = {
            'currency':currency
        }

        return self._get('margin/market', False, data=data)

    def create_lending_order(self, currency, size, dailyIntRate, term):
        # https://docs.kucoin.com/#post-lend-order

        data = {
            'currency':currency,
            'size':size,
            'dailyIntRate':dailyIntRate,
            'term':term
        }

        return self._post('margin/lend', True, data=data)

    def get_lending_orders(self, currency):   
        # https://docs.kucoin.com/#get-active-order        

        data = {
            'currency':currency
        }

        return self._get('margin/lend/active', True, data=data)

    def cancel_lend_order(self, orderId):
        # https://docs.kucoin.com/#cancel-lend-order

        return self._delete('margin/lend/{}'.format(orderId), True)


    # Websocket Endpoints

    def get_ws_endpoint(self, private=False):
        # https://docs.kucoin.com/#websocket-feed

        path = 'bullet-public'
        signed = private
        if private:
            path = 'bullet-private'

        return self._post(path, signed)
