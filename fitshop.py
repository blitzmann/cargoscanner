# -*- coding: utf-8 -*-
"""
    An Eve Online Shopping List for Fits
    
    every item has a type class, giving info to the item (price, volume, etc)
    every fit has a fit class, giving info of the fit (name, items it has and count (or duplicate), quantity)
    
    every time fit quantiry is updated, it modifies the EveType for that item to show new quantity (perhaps allow custom qty for individuel items as well)
"""

import simplejson as json
import urllib2
import time
import datetime
import xml.etree.ElementTree as ET
import humanize
import locale
import redis
import os
import jsonpickle
import pprint
import short_url
from short_hash import short_hash
import pickle

from flask import Flask, request, render_template, url_for, redirect, session, \
    send_from_directory, abort
import flask_sijax

from flask.ext.cache import Cache
from flaskext.babel import Babel, format_decimal, format_timedelta


# configuration
DEBUG = True
TYPES = json.loads(open('/home/http/public/fitshop/data/types.json').read())
USER_AGENT = 'FitShop/1.0'
CACHE_TYPE = 'redis'
CACHE_KEY_PREFIX = 'fitshop'
#CACHE_MEMCACHED_SERVERS = ['127.0.0.1:11211']
CACHE_REDIS_HOST = '127.0.0.1'
CACHE_REDIS_PORT = 6379
#CACHE_DEFAULT_TIMEOUT = 10 * 60
TEMPLATE = 'default'
SECRET_KEY = 'SET ME TO SOMETHING SECRET IN THE APP CONFIG!'
REDIS_EMDR_DB = 0
REDIS_SHOPPING_DB = 3

REGIONS = json.loads(open('/home/http/public/fitshop/emdr/regions.json').read())

emdr = redis.Redis(host='localhost', port=6379, db=REDIS_EMDR_DB)
fitshop = redis.Redis(host='localhost', port=6379, db=REDIS_SHOPPING_DB)

cache = Cache()
app = Flask(__name__)
app.config.from_object(__name__)
app.config.from_pyfile('application.cfg', silent=True)

locale.setlocale(locale.LC_ALL, '')

babel = Babel(app)
cache.init_app(app)

# one instance per item
# includes information on items price, volume, count, 
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
                'typeID' : d.get('typeID'),
                'market': d.get('market'),
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

# one instance per Fit
# includes fit name, quantity?
class EveFit():
    def __init__(self, type_id, name="Unknown Name", qty=0, modules=None):
        self.id = 0
        self.type_id = type_id # type if of fit (which ship)
        self.qty = qty # qty of ships we want
        self.name = name # name of fit
       
        self.modules = modules or [] # list of modules in the format {typeid: qty}

    def representative_value(self):
        if not self.pricing_info:
            return 0
        sell_price = self.pricing_info.get('totals', {}).get('sell', 0)
        buy_price = self.pricing_info.get('totals', {}).get('buy', 0)
        return max(sell_price, buy_price)

    def add_item(self, itemID):
        self.modules.append(str(itemID))
        
    def incr_count(self, qty):
        self.qty += qty

    def to_dict(self):
        return {
            'typeID': str(self.type_id),
            'qty': self.qty,
            'name': self.name,
            'modules': self.modules,
        }

    @classmethod
    def from_dict(self, cls, d):
        return cls(d['typeID'], d['name'], d['qty'], d['modules'])
        

@app.template_filter('format_isk')
def format_isk(value):
    try:
        return "%s ISK" % locale.format("%.2f", value, grouping=True)
    except:
        return ""

@app.template_filter('convert_id')
def convert_id(hash):
    return short_url.get_id(hash)

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

@app.template_filter('logtype')
def debug_type(value):
    return value, type(value)
    
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

def emdr_type_key(type_id, region_id):
    return "emdr-1-%s-%s" % (region_id, type_id)

def get_cached_values(eve_types, region_id):
    "Get cached pricing data of eve_types from EMDR"
    "returns: {type_id: {sell: [...], buy: [...]}}"
    
    found = {}
    for eve_type in eve_types:
        key = emdr_type_key(eve_type.type_id, region_id)
        prices = json.loads(emdr.get(key))
        if prices:
            found[eve_type.type_id] = prices['orders']
    
    return found

def save_result(result, public=True, result_id=False):
    "Save result to cache"
    data = json.dumps(result, indent=2)
    if result_id is False:
        result_id = fitshop.incr("fitshop_id")
    else:
        try:
            result_id = int(result_id)
        except:
            result_id = fitshop.incr("fitshop_id")
    # Set result to expire in 30 days
    fitshop.setex("results:%s" % result_id, data, 2592000)

    return result_id


def load_result(result_id):
    "Load result from cache"
    try:
        result_id = int(result_id)
    except:
        return

    data = fitshop.get("results:%s" % result_id)
    
    if data:
        return json.loads(data)
    
def parse_paste_items(raw_paste, previous_results = None, previous_fits = None, qty = 1):
    """
        Takes a scan result and returns:
            {'name': {details}, ...}, ['bad line']
    """
    lines = [line.strip() for line in raw_paste.splitlines() if line.strip()]

    fits = previous_fits or {} # {'typeID-name': EveFit instance}
    results = previous_results or {} # list of items
    bad_lines = []
    fitID = None #current fit id
    
    fit_append = False # True if the modules need to be appended to fitting modules list, False is the fit is already in system (skip appending of modules)
    # add type to results list
    def _add_type(name, count, append2Fit=True, fitted=False):
        if name == '':
            return False
        # get details from types file (loaded via json)
        details = app.config['TYPES'].get(name)
        if not details:
            return False # doesn't exist
        type_id = details['typeID']
        if type_id not in results:
            results[type_id] = EveType(type_id, props=details.copy())
        results[type_id].incr_count(count, fitted=fitted)
        if append2Fit: #we turn this off if the item in question is the ship itself
            fits[fitID].add_item(type_id)
        return True
        
    def _add_fit(typeName, fitName, qty=1):
        if typeName == '':
            return False
        # get details from types file (loaded via json)
        details = app.config['TYPES'].get(typeName)
        if not details:
            return False # doesn't exist
        type_id = details['typeID']
        fitID = str(type_id) + fitName
        # todo: possibly use hash of object to determine fits that are the same?
        if fitID not in fits:
            fit_append = True
            fits[fitID] = EveFit(type_id, fitName)
        else:
            # found fit, do not append modules
            fit_append = False
        fits[fitID].incr_count(qty)
        return True, fitID, fit_append

    for line in lines:
        fmt_line = line.lower().replace(' (original)', '')
        #app.logger.debug("Line: %s, fitID: %s",fmt_line, fitID)

        # aiming for the format "[panther, my pimp panther]" (EFT)
        if '[' in fmt_line and ']' in fmt_line and fmt_line.count(",") > 0:
            item, name = fmt_line.lstrip('[').rstrip(']').split(',', 1)
            success, fitID, fit_append = _add_fit(item.strip(), name, qty) 
            
            if success and _add_type(item.strip(), qty, False):
                continue
         
        """if fitID == None: #if we do not have a fit associated with item, skip it
            app.logger.debug("no fitID found")
            continue
"""
        # aiming for the format "Cargo Scanner II" (Basic Listing)
        if _add_type(fmt_line, qty, fit_append):
            continue
            
        # aiming for the format (EFT)
        # "800mm Repeating Artillery II, Republic Fleet EMP L"
        if ',' in fmt_line:
            item, item2 = fmt_line.rsplit(',', 1)
            _add_type(item2.strip(), qty, fit_append)
            if _add_type(item.strip(), qty, fit_append):
                continue

        # aiming for the format "Hornet x5" (EFT)
        try:
            if 'x' in fmt_line:
                item, count = fmt_line.rsplit('x', qty)       # remove , and . from count (decimal seperators)
                if _add_type(item.strip(), int(count.strip().replace(',', '').replace('.', '')), fit_append):
                    continue
        except ValueError:
            pass

            
        #todo: do not add [Empty High Slot] type lines to bad lines list
        
        # could not find appropriate format
        bad_lines.append(line)
    
    #app.logger.debug("fit: %s", jsonpickle.encode(fits  ))
    return results, fits, bad_lines


def is_from_igb():
    return request.headers.get('User-Agent', '').find("EVE-IGB") != -1


def get_invalid_values(eve_types, region=None):
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


def populate_market_values(eve_types, methods=None, region='10000002'):
    unpopulated_types = list(eve_types)

    if methods is None:
        methods = [get_invalid_values, get_cached_values]
    for pricing_method in methods:
        if len(unpopulated_types) == 0:
            break
        # returns a dict with {type_id: pricing_info}
        prices = pricing_method(unpopulated_types, region)
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

                eve_type.pricing_info = pdata
            else:
                new_unpopulated_types.append(eve_type)
        unpopulated_types = new_unpopulated_types

    return eve_types
 
@app.route('/auth-ajax', methods=['POST'])
def auth(): 
    result_id_code = request.form.get('result_id', 'true')
    result_id = short_url.get_id(request.form.get('result_id', 'true'))
    results = load_result(result_id)

    if results:
        auth = results['auth_hash']
        auth_input = request.form.get('auth_input', '')
        if (result_id_code not in session.get('auths') and auth_input != auth):
            return str(False)
    session.get('auths').add(result_id_code)
    session.modified = True

    return str(True)

@app.route('/password')
def request_pass():
    return render_template('password.html')

@app.route('/shop', methods=['POST'])
def submit():
    "Main function. So direty work of submission and returns results"
    raw_paste = request.form.get('raw_paste', '')
    
    session['paste_autosubmit'] = request.form.get('paste_autosubmit', 'false')
    session['hide_buttons'] = request.form.get('hide_buttons', 'false')
    session['save'] = request.form.get('save', 'true')
    session['auths'] = set(session.get('auths') or [])
    session['region_id'] = request.form.get('trade_region', '10000002')
    
    try:
        qty = int(request.form.get('qty', '0'))
    except ( ValueError ):
        qty = 1

    if session['region_id'] not in REGIONS.keys():
        session['region_id'] = '10000002'
    
    new_result = True  # flag for new results
    authorized = False # flag for authorization to modify

    result_id = short_url.get_id(request.form.get('result_id', 'true'))
    results = load_result(result_id)

    '''
        If results exists, this means we are trying to modify existing result.
        Go through the motions of authenticating user, and return return some variables
    '''
    if results:
        auth = results['auth_hash']
        if (request.form.get('result_id', 'true') not in session.get('auths')):
            results.pop('auth_hash', None)
            results['result_id'] = request.form.get('result_id', 'true')
            return render_template('results.html', error='Not authorized', results=results,
                from_igb=is_from_igb(), full_page=request.form.get('load_full'))
        
        new_result = False
        prev_types = {}
        prev_fits = {}
        for id, item in results['line_items'].iteritems():
            a = EveType(item['typeID'])
            prev_types[item['typeID']] = a.from_dict(EveType, item)
        for item in results['fits']:
            a = EveFit(item['typeID'])
            prev_fits[str(item['typeID'])+item['name']] = a.from_dict(EveFit, item)
        eve_types, fits, bad_lines = parse_paste_items(raw_paste, prev_types, prev_fits, qty)
    else:
        eve_types, fits, bad_lines = parse_paste_items(raw_paste, qty = qty)
    
    # Populate types with pricing data
    populate_market_values(eve_types.values(), region=session['region_id'])

    # calculate the totals
    totals = {'sell': 0, 'buy': 0, 'volume': 0}
    for t in eve_types.values():
        for total_key in ['sell', 'buy', 'volume']:
            totals[total_key] += t.pricing_info['totals'][total_key]

    #sort buy price
    sorted_eve_types = sorted(eve_types.values(), key=lambda k: -k.representative_value())
    sorted_fits = sorted(fits.values())
    displayable_line_items = {}
    display_fits = []

    for eve_type in sorted_eve_types:
        displayable_line_items[str(eve_type.type_id)] = eve_type.to_dict()
    for fit in sorted_fits:
        display_fits.append(fit.to_dict())  

    results = {
        'from_igb': is_from_igb(),
        'totals': totals,
        'bad_line_items': bad_lines,
        'line_items': displayable_line_items, # dict of inventory
        'fits': display_fits, #dict of fits
        'region_name':  REGIONS[session['region_id']],
        'modified': time.time(),
        'auth_hash': short_hash(6) if new_result else auth
    }
    
    if len(sorted_eve_types) > 0:
        if session['save'] == 'true':
            result_id = save_result(results, public=True, result_id=(result_id if not new_result else False))
            results['result_id'] = short_url.get_code(result_id)
            session['auths'].add(results['result_id'])
        else:
            result_id = save_result(results, public=False, result_id=(result_id if not new_result else False))
    
    if not new_result:
        results.pop('auth_hash', None)
    return render_template('results.html', results=results,
        from_igb=is_from_igb(), full_page=request.form.get('load_full'))


@app.route('/shop/<string:result_id>', methods=['GET'])
def display_result(result_id):
    # Init's auth dict
    session['auths'] = set(session.get('auths') or [])
    id = short_url.get_id(result_id)
    results = load_result(id)
    error = None
    status = 200
    if results:
        results['result_id'] = result_id
        results.pop('auth_hash', None)

        return render_template('results.html', regions=REGIONS, results=results,
            error=error, from_igb=is_from_igb(), full_page=True), status
    else:
        return render_template('index.html', error="Resource Not Found",
            regions=REGIONS, from_igb=is_from_igb(), full_page=True), 404

'''
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
'''

@app.route('/', methods=['GET', 'POST'])
def index():
    "Index. Renders HTML."
    return render_template('index.html', regions = REGIONS, dfrom_igb=is_from_igb())


@app.route('/legal')
def legal():
    return render_template('legal.html')


@app.route('/robots.txt')
@app.route('/favicon.ico')
def static_from_root():
    return send_from_directory(app.static_folder, request.path[1:])

if __name__ == '__main__':
    app.run(host='0.0.0.0')
