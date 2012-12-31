from gevent import monkey; monkey.patch_all()
import cherrypy
from Cheetah.Template import Template
from DatabaseManager import DatabaseManager
from decimal import Decimal, ROUND_DOWN
import datetime
from gevent import pywsgi
import logging
from logging import handlers
import os.path
import random
import simplejson as json
import threading
import time
import tools.auth_kerberos
import tools.auth_members
import sys
sys.path.append('templates')

app_dir = os.path.dirname(os.path.abspath(__file__))
app_config = {'/':              { 'tools.sessions.on':True },
              '/bootstrap.css': { 'tools.staticfile.on':True,
                                  'tools.staticfile.filename':app_dir + '/css/bootstrap.min.css' },
              '/bootstrap.js':  { 'tools.staticfile.on':True,
                                  'tools.staticfile.filename':app_dir + '/js/bootstrap.min.js' },
              '/jquery.js':     { 'tools.staticfile.on':True,
                                  'tools.staticfile.filename':app_dir + '/js/jquery-1.8.3.min.js' },
              '/highcharts.js': { 'tools.staticfile.on':True,
                                  'tools.staticfile.filename':app_dir + '/js/highcharts.js' }}

members = ['CRS', 'DCH', 'DHM', 'DT', 'ENH', 'GJC', 'JAC', 'JAG2', 'JJL', 'JTR', 'MAM', 'MRR']
stocks = {'LON:BYG' : 'Big Yellow Group',
          'LON:CINE': 'Cineworld Group',
          'LON:CMX' : 'Catalyst Media Group',
          'LON:DLAR': 'De La Rue',
          'LON:EMG' : 'Man Group',
          'LON:FSTA': 'Fuller, Smith and Turner',
          'LON:GAW' : 'Games Workshop Group',
          'LON:GRG' : 'Greggs',
          'LON:HIK' : 'Hikma Pharmaceuticals',
          'LON:LLOY': 'Lloyds Banking Group',
          'LON:MRO' : 'Melrose',
          'LON:NETD': 'Net Dimensions (Holdings) Limited',
          'LON:NXR' : 'Norcros',
          'LON:OMG' : 'OMG',
          'LON:PSN' : 'Persimmon',
          'LON:SHP' : 'Shire',
          'LON:SLN' : 'Silence Therapeutics',
          'LON:TSCO': 'Tesco',
          'LON:ZZZ' : 'Snoozebox Holdings'}

class PredictionContest(object):
    """CherryPy application running the monthly prediction contest"""
    def __init__(self, db, start_date, deadline):
        """Initialization"""
        self.db = db
        self.db_lock = threading.Lock()
        self.start_date = start_date
        self.deadline = deadline

    @cherrypy.expose
    @cherrypy.tools.auth_kerberos()
    @cherrypy.tools.auth_members(users=members)
    def home(self):
        """Home page for the prediction contest"""
        user = cherrypy.request.login.split('@')[0].upper()
        account = self.get_account_details(user)
        return self.make_page('home.tmpl', account)

    @cherrypy.expose
    @cherrypy.tools.auth_kerberos()
    @cherrypy.tools.auth_members(users=members)
    def update_wrapper(self):
        """Server Sent Events updating the stock prices and standings"""
        # Set headers and data.
        cherrypy.response.headers["Content-Type"] = "text/event-stream"
        cherrypy.response.headers["Cache-Control"] = "no-cache"

        make_data = lambda x: {'ticker': x, 'price': self.db.get_stock_price(x)}
        stock_prices = [make_data(ticker) for ticker in stocks]
        stock_data = sorted(stock_prices, key=lambda x: x['ticker'])

        users = self.get_leaderboard()
        data = {'stocks':stock_data, 'users':users}
        message = 'data: ' + json.dumps(data, cls=DecimalEncoder)

        # Figure out when new data might next be available - that's on 15
        # minute boundaries.  Tell the browser to look again then (randomising
        # a bit to spread the load).
        now = datetime.datetime.utcnow()
        delay = 900 - (((60 * now.minute) + now.second) % 900)
        delay += random.randint(1,11)
        delay = 1000 * delay
        message += '\nretry: %d\n\n' % delay

        return message
    update_wrapper._cp_config = {'tools.encode.encoding':'utf-8'}

    @cherrypy.expose
    @cherrypy.tools.auth_kerberos()
    @cherrypy.tools.auth_members(users=members)
    def account(self, **kwargs):
        """Display the details of a user's account"""
        if datetime.datetime.now() < self.deadline:
            raise cherrypy.HTTPRedirect("home")

        if 'user' in kwargs:
            user = kwargs['user']
        else:
            user = cherrypy.request.login.split('@')[0].upper()

        if user not in members:
            raise cherrypy.HTTPRedirect("home")

        dict = self.get_account_details(user)
        dict['members'] = members
        return self.make_page('account.tmpl', dict)

    @cherrypy.expose
    @cherrypy.tools.auth_kerberos()
    @cherrypy.tools.auth_members(users=members)
    def purchase(self):
        """Page to purchase a stock"""
        tickers = sorted(stocks.keys())
        return self.make_page('purchase.tmpl', {'stocks':tickers})

    @cherrypy.expose
    @cherrypy.tools.auth_kerberos()
    @cherrypy.tools.auth_members(users=members)
    def confirm_purchase(self, stock, cost, cancel=False):
        """Page to confirm the purchase of a stock"""
        if cancel:
            raise cherrypy.HTTPRedirect('home')

        try:
            pounds = Decimal(cost).quantize(Decimal('.01'), rounding=ROUND_DOWN)
        except:
            raise cherrypy.HTTPRedirect('home')

        price = self.db.update_stock_price(stock)
        if not price:
            raise cherrypy.HTTPRedirect('home')

        pennies = int(100 * pounds)
        cherrypy.session['stock'] = stock
        cherrypy.session['price'] = price
        cherrypy.session['cost'] = pennies
        cherrypy.session['offerExpires'] = datetime.datetime.utcnow() + datetime.timedelta(seconds=30)

        return self.make_page('confirm_purchase.tmpl', {'stock':stock, 'cost':pounds, 'price':price})

    @cherrypy.expose
    @cherrypy.tools.auth_kerberos()
    @cherrypy.tools.auth_members(users=members)
    def submit_purchase(self, cancel=False):
        """Submit a purchase, after confirming that it is really what the user wants to do"""
        if cancel:
            raise cherrypy.HTTPRedirect('home')

        if datetime.datetime.now() > self.deadline:
            raise cherrypy.HTTPRedirect('home')

        # Retrieve, and then expire, session data containing details of purchase.
        try:
            stock = cherrypy.session.get('stock')
            price = cherrypy.session.get('price')
            cost = cherrypy.session.get('cost')
            offerExpires = cherrypy.session.get('offerExpires')
        finally:
            cherrypy.lib.sessions.expire()

        # Check that the offer hasn't expired.
        if datetime.datetime.utcnow() > offerExpires:
            raise cherrypy.HTTPRedirect('home')

        # If the purchase is allowed, make it.
        self.db_lock.acquire()
        try:
            user = cherrypy.request.login.split('@')[0].upper()
            if self.is_purchase_allowed(user, stock, price, cost):
                self.db.record_purchase(user, stock, price, cost)

        finally:
            self.db_lock.release()

        raise cherrypy.HTTPRedirect('home')

    @cherrypy.expose
    @cherrypy.tools.auth_kerberos()
    @cherrypy.tools.auth_members(users=members)
    def analysis(self):
        """Analysis page"""
        if datetime.datetime.now() < self.deadline:
            raise cherrypy.HTTPRedirect('home')

        # Figure out where the money went.
        spent = self.get_all_stock_expenditure()
        expenditure = json.dumps(spent)

        # Figure out how the race unfolded.
        series = [{'type':'line',
                   'id':member,
                   'name':member,
                   'data':self.get_user_history(member)} for member in members]
        race = json.dumps(series)
        return self.make_page('analysis.tmpl', {'expenditure':expenditure, 'race':race})

    def get_all_stock_expenditure(self):
        """Figure out how much was spent on each stock"""
        details = [(ticker, self.db.get_stock_expenditure(ticker)) for ticker in stocks]
        expenditure = [{'name':ticker, 'y':y} for (ticker, y) in details if y > 0]

        return sorted(expenditure, key=lambda val: val['y'], reverse=True)

    def make_page(self, template='home.tmpl', details={}):
        """Make a page: figure out the generic information required for the wrapper and then
        use the provided template"""
        make_data = lambda ticker, name: {'ticker': ticker, 'price': self.db.get_stock_price(ticker), 'full_name': name}
        stock_prices = [make_data(ticker, name) for (ticker, name) in stocks.iteritems()]
        stock_data = sorted(stock_prices, key=lambda x: x['ticker'])
        users = self.get_leaderboard()
        past_deadline = datetime.datetime.now() > self.deadline
        base = {'tickers':stock_data, 'users':users, 'past_deadline':past_deadline}
        t = Template(file=app_dir + '/templates/' + template, searchList=[base, details])
        return str(t)

    def get_account_details(self, user):
        """Get the details describing a user account"""
        transactions = self.db.get_user_transactions(user)

        total = 0
        spent = 0
        for transaction in transactions:
            # Get the current value, in pounds, of this transaction...
            value_pennies = self.db.get_current_value(transaction)
            transaction['value'] = self.pennies_to_pounds(value_pennies)

            # ... and convert the cost into pounds.
            transaction['cost'] = self.pennies_to_pounds(transaction['cost'])

            # Update the total value and spend.
            total = total + transaction['value']
            spent = spent + transaction['cost']

        if datetime.datetime.now() < self.deadline:
            cash = 1000 - spent
        else:
            cash = 0

        account = {'user':user, 'transactions':transactions, 'total':total, 'spent':spent, 'cash':cash}
        return account

    def get_leaderboard(self):
        """Calculates the leaderboard"""
        def details(user):
            pennies = self.db.get_current_user_value(user)
            pounds = self.pennies_to_pounds(pennies)
            return {'initials':user, 'value':pounds}

        users = [details(member) for member in members]
        return sorted(users, key=lambda x: x['value'], reverse=True)

    def is_purchase_allowed(self, user, stock, price, cost):
        """Decide whether a purchase is allowed"""
        # Only allow positive expenditure!
        if cost <= 0:
            return False

        # Only allow purchases of the permitted stocks.
        if stock not in stocks:
            return False

        # Get the transactions that this user has already made.
        user_transactions = self.db.get_user_transactions(user)

        # Don't allow more than three purchases per user.
        if len(user_transactions) > 2:
            return False

        # Figure out how much the user has so far spent (in pennies).
        spent = 0
        for transaction in user_transactions:
            spent = spent + transaction['cost']

        # Don't allow over-spending.
        if spent + cost > 100000:
            return False

        return True

    def pennies_to_pounds(self, pennies):
        """Utility function for converting pennies to pounds"""
        pounds = Decimal(pennies) / 100
        pounds = pounds.quantize(Decimal('.01'), rounding=ROUND_DOWN)
        return pounds

    def get_user_history(self, user):
        """Get the historical value of a user's portfolio"""
        make_pair = lambda date, value: [1000 * time.mktime(date.timetuple()), value]
        data = self.db.get_user_history(user, self.start_date)
        values = [make_pair(date, value) for (date, value) in data.iteritems() if value > 0]

        # If we don't have a 'historical' value for today, add the current
        # value.
        today = datetime.date.today()
        timenow = datetime.datetime.combine(today, datetime.time())
        if timenow.date() > date.date():
            value = self.db.get_current_user_value(user)
            if value > 0:
                final_point = make_pair(timenow, value)
                values.append(final_point)

        return values

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return json.JSONEncoder.default(self, obj)

def configure_logging():
    # Remove the default FileHandlers if present.
    log = cherrypy.log
    log.error_file = ""
    log.access_file = ""

    # Make sure we have a directory to put the logs in.
    if not os.path.exists("logs"):
        os.makedirs("logs")

    # Utility to create a RotatingFileHandler.
    def getRotatingFileHandler(filename):
        handler = handlers.RotatingFileHandler(filename, 'a', 10000000, 100)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(cherrypy._cplogging.logfmt)
        return handler

    # Make a new RotatingFileHandler for the error log.
    handler = getRotatingFileHandler("logs/error.log")
    log.error_log.addHandler(handler)

    # Make a new RotatingFileHandler for the access log.
    handler = getRotatingFileHandler("logs/access.log")
    log.access_log.addHandler(handler)

def start_server(contest, port=7070, use_gevent=True):
    """Start the server"""
    app = cherrypy.tree.mount(contest, '/drinc/', config=app_config)
    if use_gevent:
        pywsgi.WSGIServer(('', port), app, log=None).serve_forever()
    else:
        cherrypy.config.update({'server.socket_host': '0.0.0.0',
                                'server.socket_port': port})
        cherrypy.engine.start()
        cherrypy.engine.block()

start_date = datetime.datetime(2012, 12, 18, 18)
deadline = datetime.datetime(2012, 12, 24, 18)

if __name__ == "__main__":
    db = DatabaseManager(members, stocks.keys())
    db.start()
    contest = PredictionContest(db, start_date, deadline)
    configure_logging()
    start_server(contest)
