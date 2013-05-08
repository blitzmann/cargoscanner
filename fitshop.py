# -*- coding: utf-8 -*-
"""
    An Eve Online Shopping List for Fits
"""
import json
import simplejson
import urllib2
import time
import datetime
import xml.etree.ElementTree as ET
import humanize
import locale
import redis
import os
import jsonpickle

from flask import Flask, request, render_template, url_for, redirect, session, \
    send_from_directory

from flask.ext.cache import Cache
from flaskext.babel import Babel, format_decimal, format_timedelta

from sqlalchemy import create_engine, MetaData, Table, Column, Integer, Text,\
    Float, Boolean, select, desc


# configuration
DEBUG = True
TYPES = json.loads(open('data/types.json').read())
USER_AGENT = 'Evepraisal/1.0 +http://evepraisal.com/'
SQLALCHEMY_DATABASE_URI = 'sqlite:///data/scans.db'
CACHE_TYPE = 'redis'
CACHE_KEY_PREFIX = 'evepraisal'
#CACHE_MEMCACHED_SERVERS = ['127.0.0.1:11211']
CACHE_REDIS_HOST = '127.0.0.1'
CACHE_REDIS_PORT = 6379
#CACHE_DEFAULT_TIMEOUT = 10 * 60
#CACHE_REDIS_DB = ;
TEMPLATE = 'default'
SECRET_KEY = 'SET ME TO SOMETHING SECRET IN THE APP CONFIG!'
#REDIS_EMDR_DB = 0
#REDIS_SHOPPING_DB = 3

emdr = redis.StrictRedis(host='localhost', port=6379, db=0)
#shopping = redis.StrictRedis(host='localhost', port=6379, db=REDIS_SHOPPING_DB)

cache = Cache()
app = Flask(__name__)
app.config.from_object(__name__)
app.config.from_pyfile('application.cfg', silent=True)

engine = create_engine(app.config['SQLALCHEMY_DATABASE_URI'], convert_unicode=True)
metadata = MetaData(bind=engine)
scans = Table('Scans', metadata,
    Column('Id', Integer, primary_key=True),
    Column('Data', Text),
    Column('Created', Integer),
    Column('SellValue', Float),
    Column('BuyValue', Float),
    Column('Public', Boolean, default=True),
)

try:
    engine.connect()
    engine.execute("ALTER TABLE Scans ADD Public BOOLEAN")
except:
    pass

locale.setlocale(locale.LC_ALL, '')

babel = Babel(app)
metadata.create_all(bind=engine)
cache.init_app(app)


class EveType():
    def __init__(self, type_id, count=0, props=None, pricing_info=None):
        self.type_id = type_id

        self.count = count
        self.fitted_count = 0

        self.props = props or {}
        self.pricing_info = pricing_info or {}
        self.market = self.props.get('market', False)
        self.volume = self.props.get('volume', 0)
        self.type_name = self.props.get('typeName', 0)
        self.group_id = self.props.get('groupID')

    def representative_value(self):
        if not self.pricing_info:
            return 0
        sell_price = self.pricing_info.get('totals', {}).get('sell', 0)
        buy_price = self.pricing_info.get('totals', {}).get('buy', 0)
        return max(sell_price, buy_price)

    def is_market_item(self):
        return self.props.get('market', False) == True

    def incr_count(self, count, fitted=False):
        self.count += count
        if fitted:
            self.fitted_count += count

    def to_dict(self):
        return {
            'typeID': self.type_id,
            'count': self.count,
            'fitted_count': self.fitted_count,
            'market': self.market,
            'volume': self.volume,
            'typeName': self.type_name,
            'groupID': self.group_id,
            'totals': self.pricing_info.get('totals'),
            'sell': self.pricing_info.get('sell'),
            'buy': self.pricing_info.get('buy'),
        }

    @classmethod
    def from_dict(self, cls, d):
        return cls(d['typeID'], d['count'],
            {
                'typeName': d.get('typeName'),
                'groupID': d.get('groupID'),
                'volume': d.get('volume')
            },
            {
                'totals': d.get('totals'),
                'sell': d.get('sell'),
                'buy': d.get('buy'),
            }
        )


@app.template_filter('format_isk')
def format_isk(value):
    try:
        return "%s ISK" % locale.format("%.2f", value, grouping=True)
    except:
        return ""


@app.template_filter('format_isk_human')
def format_isk_human(value):
    if value is None:
        return ""
    try:
        return "%s ISK" % humanize.intword(value, format='%.2f')
    except:
        return str(value)


@app.template_filter('format_volume')
def format_volume(value):
    try:
        if value == 0:
            return "0m<sup>3</sup>"
        if value < 0.01:
            return "%.4fm<sup>3</sup>" % value
        if value < 1:
            return "%.2fm<sup>3</sup>" % value
        return "%sm<sup>3</sup>" % humanize.intcomma(int(value))
    except:
        return "unknown m<sup>3</sup>"


@app.template_filter('relative_time')
def relative_time(past):
    try:
        return humanize.naturaltime(datetime.datetime.fromtimestamp(past))
    except:
        return ""


@app.template_filter('bpc_count')
def bpc_count(bad_lines):
    c = 0
    for line in bad_lines:
        if '(copy)' in line.lower():
            c += 1
    return c


@babel.localeselector
def get_locale():
    return request.accept_languages.best_match(['en'])


def emdr_type_key(typeId):
    return "emdr-1-10000002-%s" % typeId


def memcache_type_key(typeId):
    return "prices:%s" % typeId


def get_cached_values(eve_types):
    "Get Cached values given the eve_types"
    found = {}
    for eve_type in eve_types:
        key = emdr_type_key(eve_type.type_id)
        obj = simplejson.loads(emdr.get(key))
        if obj:
            #app.logger.debug("Found cache for %d: %s", eve_type.type_id, obj) 
            found[eve_type.type_id] = obj['orders']

    return found


def get_market_values(eve_types):
    """
        Takes list of typeIds. Returns dict of pricing details with typeId as
        the key. Calls out to the eve-central.

        Example Return Value:
        {
            21574:{
             'all': {'avg': 254.83, 'min': 254.83, 'max': 254.83, 'price': 254.83},
             'buy': {'avg': 5434414.43, 'min': 5434414.43, 'max': 5434414.43, 'price': 5434414.43},
             'sell': {'avg': 10552957.04, 'min': 10552957.04, 'max': 10552957.04, 'price': 10552957.04}
        }
    """
    app.logger.debug("MARKET")
    if len(eve_types) == 0:
        return {}

    market_prices = {}
    for types in [eve_types[i:i + 200] for i in range(0, len(eve_types), 200)]:
        typeids = ["typeid=" + str(x.type_id) for x in types]
        # Forge (for jita): 10000002
        # Metropolis (for hek): 10000042
        # Heimatar (for rens): 10000030
        # Sinq Laison region (for dodixie): 10000032
        # Domain (for amarr): 10000043
        regions = ['regionlimit=10000002', 'regionlimit=10000042',
            'regionlimit=10000030', 'regionlimit=10000032', 'regionlimit=10000043']
        query_str = '&'.join(regions + typeids)
        url = "http://api.eve-central.com/api/marketstat?%s" % query_str
        try:
            request = urllib2.Request(url)
            request.add_header('User-Agent', app.config['USER_AGENT'])
            response = urllib2.build_opener().open(request).read()
            stats = ET.fromstring(response).findall("./marketstat/type")

            for marketstat in stats:
                k = int(marketstat.attrib.get('id'))
                v = {}
                for stat_type in ['sell', 'buy', 'all']:
                    props = {}
                    for stat in marketstat.find(stat_type):
                        props[stat.tag] = float(stat.text)
                    v[stat_type] = props
                v['all']['price'] = v['all']['percentile']
                v['buy']['price'] = v['buy']['percentile']
                v['sell']['price'] = v['sell']['percentile']
                market_prices[k] = v

                # Cache for up to 10 hours
                cache.set(memcache_type_key(k), v, timeout=10 * 60 * 60)
        except urllib2.HTTPError:
            pass
    return market_prices


def get_market_values_2(eve_types):
    """
        Takes list of typeIds. Returns dict of pricing details with typeId as
        the key. Calls out to the eve-marketdata.
        Example Return Value:
        {
            21574:{
             'all': {'avg': 254.83, 'min': 254.83, 'max': 254.83, 'price': 254.83},
             'buy': {'avg': 5434414.43, 'min': 5434414.43, 'max': 5434414.43, 'price': 5434414.43},
             'sell': {'avg': 10552957.04, 'min': 10552957.04, 'max': 10552957.04, 'price': 10552957.04}
        }
    """
    if len(eve_types) == 0:
        return {}

    market_prices = {}
    for types in [eve_types[i:i + 200] for i in range(0, len(eve_types), 200)]:
        typeIds_str = ','.join(str(x.type_id) for x in types)
        url = "http://api.eve-marketdata.com/api/item_prices2.json?char_name=magerawr&type_ids=%s&buysell=a" % typeIds_str
        try:
            request = urllib2.Request(url)
            request.add_header('User-Agent', app.config['USER_AGENT'])
            response = json.loads(urllib2.build_opener().open(request).read())

            for row in response['emd']['result']:
                row = row['row']
                k = int(row['typeID'])
                if k not in market_prices:
                    market_prices[k] = {}
                if row['buysell'] == 's':
                    price = float(row['price'])
                    market_prices[k]['sell'] = {'avg': price, 'min': price, 'max': price}
                elif row['buysell'] == 'b':
                    price = float(row['price'])
                    market_prices[k]['buy'] = {'avg': price, 'min': price, 'max': price}

            for typeId, prices in market_prices.iteritems():
                avg = (prices['sell']['avg'] + prices['buy']['avg']) / 2
                market_prices[typeId]['all'] = {'avg': avg, 'min': avg, 'max': avg, 'price': avg}
                market_prices[typeId]['buy']['price'] = market_prices[typeId]['buy']['max']
                market_prices[typeId]['sell']['price'] = market_prices[typeId]['sell']['min']

                # Cache for up to 10 hours
                cache.set(memcache_type_key(typeId), prices, timeout=10 * 60 * 60)
        except urllib2.HTTPError:
            pass
    return market_prices


def save_result(result, public=True):
    data = json.dumps(result, indent=2)
    result = scans.insert().values(Data=data, Created=int(time.time()),
        BuyValue=result['totals']['buy'],
        SellValue=result['totals']['sell'],
        Public=public).execute()
    return result.inserted_primary_key[0]


def load_result(result_id):
    try:
        result_id = int(result_id)
    except:
        return

    data = cache.get("results:%s" % result_id)
    if data:
        return data

    row = select([scans.c.Data], (scans.c.Id == result_id) &
        ((scans.c.Public == True) | (scans.c.Public == None))).execute().first()
    if row:
        data = json.loads(row[0])
        if 'raw_scan' in data:
            data['raw_paste'] = data['raw_scan']
            del data['raw_scan']

        cache.set("results:%s" % result_id, data, timeout=600)
        return data


def parse_paste_items(raw_paste):
    """
        Takes a scan result and returns:
            {'name': {details}, ...}, ['bad line']
    """
    lines = [line.strip() for line in raw_paste.splitlines() if line.strip()]

    results = {}
    bad_lines = []

    # add type to results list
    def _add_type(name, count, fitted=False):
        if name == '':
            return False
        # get details from types file (loaded via json)
        details = app.config['TYPES'].get(name)
        if not details:
            #app.logger.debug(name+" doesn't exist")
            return False # doesn't exist
        type_id = details['typeID']
        if type_id not in results:
            results[type_id] = EveType(type_id, props=details.copy())
        results[type_id].incr_count(count, fitted=fitted)
        return True

    for line in lines:
        fmt_line = line.lower().replace(' (original)', '')

        # aiming for the format "Cargo Scanner II" (Basic Listing)
        if _add_type(fmt_line, 1):
            continue

        # aiming for the format "2 Cargo Scanner II" and "2x Cargo Scanner II"
        # (Cargo Scan)
        try:
            count, name = fmt_line.split(' ', 1)
            count = int(count.replace('x', '').strip().replace(',', '').replace('.', ''))
            if _add_type(name.strip(), count):
                continue
        except ValueError:
            pass

        # aiming for the format (EFT)
        # "800mm Repeating Artillery II, Republic Fleet EMP L"
        if ',' in fmt_line:
            item, item2 = fmt_line.rsplit(',', 1)
            _add_type(item2.strip(), 1)
            if _add_type(item.strip(), 1):
                continue

        # aiming for the format "Hornet x5" (EFT)
        try:
            if 'x' in fmt_line:
                item, count = fmt_line.rsplit('x', 1)       # remove , and . from count (decimal seperators)
                if _add_type(item.strip(), int(count.strip().replace(',', '').replace('.', ''))):
                    continue
        except ValueError:
            pass

        # aiming for the format "[panther, my pimp panther]" (EFT)
        if '[' in fmt_line and ']' in fmt_line and fmt_line.count(",") > 0:
            item, _ = fmt_line.strip('[').split(',', 1)
            if _add_type(item.strip(), 1):
                continue

        # aiming for format "PERSON'S NAME\tShipType\tdistance" (d-scan)
        if fmt_line.count("\t") > 1:
            _, item, _ = fmt_line.split("\t", 2)
            if _add_type(item.strip(), 1):
                continue

        # aiming for format "Item Name\tCount\tCategory\tFitted..." (Contracts)
        try:
            if fmt_line.count("\t") == 3:
                item, count, _, fitted = fmt_line.split("\t", 3)
                if fitted in ['', 'fitted']:
                    is_fitted = fitted == 'fitted'
                    if _add_type(item.strip(),
                                int(count.strip().replace(',', '').replace('.', '')),
                                fitted=is_fitted):
                        continue
        except ValueError:
            pass

        # aiming for format "Item Name\tCount..." (Assets, Inventory)
        try:
            if fmt_line.count("\t") > 1:
                item, count, _ = fmt_line.split("\t", 2)
                if _add_type(item.strip(), int(count.strip().replace(',', '').replace('.', ''))):
                    continue
        except ValueError:
            pass

        # aiming for format "Item Name\t..." (???)
        try:
            if fmt_line.count("\t") > 0:
                item, _ = fmt_line.split("\t", 1)
                if _add_type(item.strip(), 1):
                    continue
        except ValueError:
            pass

        # could not find appropriate format
        bad_lines.append(line)
        
    return results.values(), bad_lines


def is_from_igb():
    return request.headers.get('User-Agent', '').find("EVE-IGB") != -1


def get_invalid_values(eve_types):
    "For each item that is not on the market, set pricing info to 0"
    invalid_items = {}
    for eve_type in eve_types:
        if eve_type.props.get('market') == False:
            zeroed_price = {0, 0}
            price_info = {
                'buy': zeroed_price.copy(),
                'sell': zeroed_price.copy(),
            }
            invalid_items[eve_type.type_id] = price_info
    #app.logger.debug("Invalid market items: "+json.dumps(invalid_items))
    return invalid_items


def get_componentized_values(eve_types):
    "For cap ships, add up the value of what makes them"
    componentized_items = {}
    for eve_type in eve_types:
        if 'components' in eve_type.props:
            component_types = [EveType(c['materialTypeID'], count=c['quantity'])
                for c in eve_type.props['components']]

            populate_market_values(component_types, methods=[get_cached_values,
                get_market_values, get_market_values_2])
            zeroed_price = {'avg': 0, 'min': 0, 'max': 0, 'price': 0}
            complete_price_data = {
                'buy': zeroed_price.copy(),
                'sell': zeroed_price.copy(),
                'all': zeroed_price.copy(),
            }
            for component in component_types:
                for market_type in ['buy', 'sell', 'all']:
                    for stat in ['avg', 'min', 'max', 'price']:
                        complete_price_data[market_type][stat] += \
                            component.pricing_info[market_type][stat] * component.count
            componentized_items[eve_type.type_id] = complete_price_data
            # Cache for up to 10 hours
            cache.set(memcache_type_key(eve_type.type_id), complete_price_data,
                timeout=10 * 60 * 60)

    return componentized_items


def populate_market_values(eve_types, methods=None):
    unpopulated_types = list(eve_types)
    #app.logger.debug("POPULATING MARKET DATA")
    if methods is None:
        methods = [get_invalid_values, get_cached_values]
    for pricing_method in methods:
        if len(unpopulated_types) == 0:
            break
        # returns a dict with {type_id: pricing_info}
        prices = pricing_method(unpopulated_types)
        new_unpopulated_types = []
        for eve_type in unpopulated_types:
            if eve_type.type_id in prices:
                pdata = prices[eve_type.type_id]
                pdata['totals'] = {
                    'volume': eve_type.props.get('volume', 0) * eve_type.count
                }
                for total_key in ['sell', 'buy']:
                    _total = float(pdata[total_key][0]) * eve_type.count
                    pdata['totals'][total_key] = _total
                #app.logger.debug("%d: pdata: %s", eve_type.type_id, pdata)
                eve_type.pricing_info = pdata
            else:
                new_unpopulated_types.append(eve_type)
        unpopulated_types = new_unpopulated_types
    #app.logger.debug("eve_types: %s", jsonpickle.encode(eve_types))
    return eve_types


@app.route('/estimate', methods=['POST'])
def estimate_cost():
    "Estimate Cost of pasted stuff result given by POST[raw_paste]. Renders HTML"
    raw_paste = request.form.get('raw_paste', '')
    session['paste_autosubmit'] = request.form.get('paste_autosubmit', 'false')
    session['hide_buttons'] = request.form.get('hide_buttons', 'false')
    session['save'] = request.form.get('save', 'true')
    
    # Parse input, send to variables
    eve_types, bad_lines = parse_paste_items(raw_paste)

    # Populate types with pricing data
    populate_market_values(eve_types)

    # calculate the totals
    totals = {'sell': 0, 'buy': 0}
    for t in eve_types:
        for total_key in ['sell', 'buy']:
            totals[total_key] += t.pricing_info['totals'][total_key]

    sorted_eve_types = sorted(eve_types, key=lambda k: -k.representative_value())
    displayable_line_items = []
    for eve_type in sorted_eve_types:
        displayable_line_items.append(eve_type.to_dict())
    results = {
        'from_igb': is_from_igb(),
        'totals': totals,
        'bad_line_items': bad_lines,
        'line_items': displayable_line_items,
        'created': time.time(),
        'raw_paste': raw_paste,
    }
    if len(sorted_eve_types) > 0:
        if session['save'] == 'true':
            result_id = save_result(results, public=True)
            results['result_id'] = result_id
        else:
            result_id = save_result(results, public=False)
    return render_template('results.html', results=results,
        from_igb=is_from_igb(), full_page=request.form.get('load_full'))


@app.route('/estimate/<int:result_id>', methods=['GET'])
def display_result(result_id):
    results = load_result(result_id)
    error = None
    status = 200
    if results:
        results['result_id'] = result_id
        return render_template('results.html', results=results,
            error=error, from_igb=is_from_igb(), full_page=True), status
    else:
        return render_template('index.html', error="Resource Not Found",
            from_igb=is_from_igb(), full_page=True), 404


@app.route('/latest/', defaults={'limit': 20})
@app.route('/latest/limit/<int:limit>')
def latest(limit):
    if limit > 1000:
        return redirect(url_for('latest', limit=1000))

    result_list = cache.get("latest:%s" % limit)
    if not result_list:
        results = select(
            [scans.c.Id, scans.c.Created, scans.c.BuyValue, scans.c.SellValue],
                (scans.c.Public == True) | (scans.c.Public == None), limit=limit
            ).order_by(desc(scans.c.Created), desc(scans.c.Id)).execute()

        result_list = []
        for result in results:
            result_list.append({
                    'result_id': result['Id'],
                    'created': result['Created'],
                    'buy_value': result['BuyValue'],
                    'sell_value': result['SellValue'],
                })
        cache.set("latest:%s" % limit, result_list, timeout=60)

    return render_template('latest.html', listing=result_list)


@app.route('/', methods=['GET', 'POST'])
def index():
    "Index. Renders HTML."
    return render_template('index.html', from_igb=is_from_igb())


@app.route('/legal')
def legal():
    return render_template('legal.html')


@app.route('/robots.txt')
@app.route('/favicon.ico')
def static_from_root():
    return send_from_directory(app.static_folder, request.path[1:])


if __name__ == '__main__':
    app.run(host='192.168.1.10')