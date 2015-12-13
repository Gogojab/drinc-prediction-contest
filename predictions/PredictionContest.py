from gevent import monkey;

monkey.patch_all()
import cherrypy
from apscheduler.scheduler import Scheduler
from Cheetah.Template import Template
from DatabaseManager import DatabaseManager
from decimal import Decimal, ROUND_DOWN
import datetime
from gevent import pywsgi
import json
import logging
from logging import handlers
import os.path
import random
import threading
import time
import calendar
import sys
import hashlib
from cherrypy.lib import auth_basic
sys.path.append('predictions/templates')

DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

app_dir = os.path.dirname(os.path.abspath(__file__))

class PredictionContest(object):
    """CherryPy application running the monthly prediction contest"""
    def __init__(self, db, start_date, deadline):
        """Initialization"""
        self.db = db
        self.start_date = start_date
        self.deadline = deadline
        self._db_lock = threading.Lock()
        self._sched = Scheduler()
        self.stocks = self.db.tickers
        self.members = self.db.members

    def start(self):
        """Start the PredictionContest"""
        self._sched.start()
        self._sched.add_cron_job(self.update_member_histories, day_of_week='0-4', hour=18, minute=1, second=0,
                                 misfire_grace_time=10800)

    @cherrypy.expose
    def home(self):
        """Home page for the prediction contest"""
        user = cherrypy.session['user']
        account = self.get_account_details(user)
        return self.make_page('home.tmpl', account)

    @cherrypy.expose
    def update_page(self, member=None):
        """Server Sent Events updating the stock prices and standings"""
        # Set headers and data.
        cherrypy.response.headers['Content-Type'] = 'text/event-stream'
        cherrypy.response.headers['Cache-Control'] = 'no-cache'

        # Figure out the stock prices...
        make_data = lambda x: {'ticker': x, 'price': self.db.get_stock_price(x)}
        stock_prices = [make_data(ticker) for ticker in self.stocks]
        stock_data = sorted(stock_prices, key=lambda x: x['ticker'])

        # ... the standings...
        standings = self.get_leaderboard()
        data = {'stocks':stock_data, 'standings':standings}

        # ... and, maybe, the details of an individual account.
        if member:
            user = cherrypy.session['user']
            if member == user or self.deadline_passed():
                account = self.get_account_details(member)
                data['account'] = account

        message = 'data: ' + json.dumps(data, cls=DecimalEncoder)

        # Don't ask again until there might be new data available (randomising
        # a bit to spread the load).
        delay = self.db.get_requery_delay()
        delay += random.randint(1,11)
        delay = 1000 * delay
        message += '\nretry: %d\n\n' % delay

        return message
    update_page._cp_config = {'tools.encode.encoding':'utf-8'}

    @cherrypy.expose
    def account(self, member=None):
        """Display the details of a member's account"""
        if not self.deadline_passed():
            raise cherrypy.HTTPRedirect('home')

        if not member:
            member = cherrypy.session['user']

        if member not in self.members:
            raise cherrypy.HTTPRedirect('home')

        dict = self.get_account_details(member)
        dict['members'] = self.members
        return self.make_page('account.tmpl', dict)

    @cherrypy.expose
    def purchase(self):
        """Page to purchase a stock"""
        tickers = sorted(self.stocks.keys())
        return self.make_page('purchase.tmpl', {'stocks':tickers})

    @cherrypy.expose
    def confirm_purchase(self, stock, cost, long_short, cancel=False):
        """Page to confirm the purchase of a stock"""
        print("Confirm purchase")
        if cancel:
            raise cherrypy.HTTPRedirect('home')

        try:
            pounds = Decimal(cost).quantize(Decimal('.01'), rounding=ROUND_DOWN)
        except:
            raise cherrypy.HTTPRedirect('home')

        price = self.db.update_stock_price(stock)
        if not price:
            raise cherrypy.HTTPRedirect('home')

        short = long_short == 'short'

        pennies = int(100 * pounds)
        cherrypy.session['stock'] = stock
        cherrypy.session['price'] = price
        cherrypy.session['cost'] = pennies
        cherrypy.session['short'] = short
        cherrypy.session['offerExpires'] = datetime.datetime.utcnow() + datetime.timedelta(seconds=30)

        return self.make_page('confirm_purchase.tmpl', {'stock':stock, 'cost':pounds, 'price':price, 'short':short})

    @cherrypy.expose
    def submit_purchase(self, cancel=False):
        """Submit a purchase, after confirming that it is really what the user wants to do"""
        if cancel:
            raise cherrypy.HTTPRedirect('home')

        # Retrieve, and then expire, session data containing details of purchase.
        try:
            stock = cherrypy.session.get('stock')
            price = cherrypy.session.get('price')
            cost = cherrypy.session.get('cost')
            short = cherrypy.session.get('short')
            offerExpires = cherrypy.session.get('offerExpires')
        finally:
            cherrypy.lib.sessions.expire()

        # Check that the offer hasn't expired.
        if datetime.datetime.utcnow() > offerExpires:
            raise cherrypy.HTTPRedirect('home')

        # If the purchase is allowed, make it.
        user = cherrypy.session['user']
        with self._db_lock:
            if self.is_purchase_allowed(user, stock, cost):
                self.db.record_purchase(user, stock, price, cost, short)

        raise cherrypy.HTTPRedirect('home')

    @cherrypy.expose
    def analysis(self):
        """Analysis page"""
        # Figure out where the money went.
        spent = self.get_all_stock_expenditure()
        expenditure = json.dumps(spent)

        # Figure out how the race unfolded.
        series = [{'type':'line',
                   'id':member,
                   'name':member,
                   'data':self.get_member_history(member)} for member in self.members]
        race = json.dumps(series)
        return self.make_page('analysis.tmpl', {'expenditure':expenditure, 'race':race, 'member':cherrypy.session['user']})

    @cherrypy.expose
    def settings(self, status=""):
        """Settings page"""

        member = cherrypy.session['user']

        if member not in self.members:
            raise cherrypy.HTTPRedirect('home')

        return self.make_page('settings.tmpl', {'member': member, 'status': status})

    @cherrypy.expose
    def change_password(self, new_password, confirm_new_password, cancel=False):
        if cancel:
            raise cherrypy.HTTPRedirect('home')

        if new_password == confirm_new_password:
            hashed_pw = hashlib.sha256(new_password).hexdigest()
            success = self.db.change_password(cherrypy.session['user'], hashed_pw)

            if success:
                raise cherrypy.HTTPRedirect('settings?status=success')
            else: 
                raise cherrypy.HTTPRedirect('settings?status=failed')
        else:
            raise cherrypy.HTTPRedirect('settings?status=nomatch')

    def deadline_passed(self):
        """Have we passed the deadline?"""
        return datetime.datetime.now() > self.deadline

    def get_all_stock_expenditure(self):
        """Figure out how much was spent on each stock"""
        details = [(ticker, self.db.get_stock_expenditure(ticker)) for ticker in self.stocks]
        expenditure = [{'name':ticker, 'y':y} for (ticker, y) in details if y > 0]

        return sorted(expenditure, key=lambda val: val['y'], reverse=True)

    def make_page(self, template='home.tmpl', details={}):
        """Make a page: figure out the generic information required for the wrapper and then
        use the provided template"""
        make_data = lambda ticker, name: {'ticker': ticker, 'price': self.db.get_stock_price(ticker), 'full_name': name}
        stock_prices = [make_data(ticker, name) for (ticker, name) in self.stocks.iteritems()]
        stock_data = sorted(stock_prices, key=lambda x: x['ticker'])
        standings = self.get_leaderboard()
        user = cherrypy.session['user']
        base = {'tickers':stock_data, 'standings':standings, 'past_deadline':self.deadline_passed(), 'user':user}
        t = Template(file='predictions/templates/' + template, searchList=[base, details])
        return str(t)

    def get_account_details(self, member):
        """Get the details describing a member account"""
        def convert(transaction):
            value_pennies = self.db.get_current_value(transaction)
            detail = {'stock':transaction['stock'],
                      'price':transaction['price'],
                      'cost' :self.pennies_to_pounds(transaction['cost']),
                      'value':self.pennies_to_pounds(value_pennies),
                      'short':transaction['short']}
            return detail

        transactions = self.db.get_member_transactions(member)
        details = [convert(transaction) for transaction in transactions]
        total = sum([detail['value'] for detail in details])
        spent = sum([detail['cost'] for detail in details])

        cash = self.remaining_cash(transactions=transactions)
        cash = self.pennies_to_pounds(cash)

        account = {'member':member, 'transactions':details, 'total':total, 'spent':spent, 'cash':cash}
        return account

    def get_leaderboard(self):
        """Calculates the leaderboard"""
        def details(member):
            pennies = self.db.get_current_member_value(member)
            pounds = self.pennies_to_pounds(pennies)
            return {'initials':member, 'value':pounds}

        standings = [details(member) for member in self.members]
        return sorted(standings, key=lambda x: x['value'], reverse=True)

    def is_purchase_allowed(self, member, stock, cost):
        """Decide whether a purchase is allowed"""
        # Only allow positive expenditure!
        if cost <= 0:
            return False

        # Only allow purchases of the permitted stocks.
        if stock not in self.stocks:
            return False

        # Don't allow over-spending.
        if cost > self.remaining_cash(member=member):
            return False

        if stock in self.bought_stocks(member):
            return False

        # Allow the purchase.
        return True

    def remaining_cash(self, member="", transactions=None):
        """Figure out how much cash a member has left to spend, in pennies"""

        # After the deadline, no expenditure is allowed.
        if self.deadline_passed():
            return 0

        # If we're not told the member's transactions, go get them.
        if transactions is None:
            transactions = self.db.get_member_transactions(member)

        # Don't allow more than three purchases.
        if len(transactions) > 2:
            return 0

        # Cash remaining is cash allowed, minus cash spent.
        spent = sum([transaction['cost'] for transaction in transactions])
        cash = 100000 - spent
        return cash

    def bought_stocks(self, member):
        """List the stocks that the member has already bought"""

        transactions = self.db.get_member_transactions(member)
        return transaction['stock'] for transaction in transactions]
        
    def pennies_to_pounds(self, pennies):
        """Utility function for converting pennies to pounds"""
        pounds = Decimal(pennies) / 100
        pounds = pounds.quantize(Decimal('.01'), rounding=ROUND_DOWN)
        return pounds

    def get_member_history(self, member):
        """Get the historical value of a member's portfolio for this month"""
        make_pair = lambda date, value: [1000 * calendar.timegm(date.timetuple()), value]
        data = self.db.get_member_history(member, self.start_date)
        values = [make_pair(date, value) for (date, value) in data.iteritems() if value > 0]
        values.sort(key=lambda (d, _): d)

        # If we don't have a 'historical' value for today, add the current
        # value.
        today = datetime.date.today()
        timenow = datetime.datetime.combine(today, datetime.time())
        if not values or timenow.date() > date.date():
            value = self.db.get_current_member_value(member)
            if value > 0:
                final_point = make_pair(timenow, value)
                values.append(final_point)

        return values

    def update_member_histories(self):
        """Update the member histories in the database"""
        today = datetime.date.today()
        timestamp = datetime.datetime.combine(today, datetime.time())
        print "Updating members for timestamp %s" % timestamp
        for member in self.members:
            if self.remaining_cash(member) == 0:
                worth = self.db.get_current_member_value(member)
                self.db.update_member_history(member, timestamp, worth)

    def get_password_hash(self, member):
        """Get the password hash of the member, or None if the member does not exist"""
        return self.db.get_password_hash(member)

class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that understands Decimal objects"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return json.JSONEncoder.default(self, obj)

def configure_logging():
    """Configure logging on our web server"""
    # Remove the default FileHandlers if present.
    log = cherrypy.log
    log.error_file = ''
    log.access_file = ''

    # Make sure we have a directory to put the logs in.
    if not os.path.exists('logs'):
        os.makedirs('logs')

    # Utility to create a RotatingFileHandler.
    def getRotatingFileHandler(filename):
        handler = handlers.RotatingFileHandler(filename, 'a', 10000000, 100)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(cherrypy._cplogging.logfmt)
        return handler

    # Make a new RotatingFileHandler for the error log.
    handler = getRotatingFileHandler('logs/error.log')
    log.error_log.addHandler(handler)

    # Make a new RotatingFileHandler for the access log.
    handler = getRotatingFileHandler('logs/access.log')
    log.access_log.addHandler(handler)

def start_server(contest, port=7070):
    """Start the server"""
    contest = contest

    def validate_password(self, username, password):

        hashed_pw = hashlib.sha256(password).hexdigest()
        stored_password = contest.get_password_hash(username)

        if stored_password is not None:
            if hashed_pw == stored_password:
                cherrypy.serving.request.login = username
                cherrypy.session['user'] = username
                return True
        return False

    basic_auth = {'tools.sessions.on': True,
                  'tools.auth_basic.on': True,
                  'tools.auth_basic.realm': 'localhost',
                  'tools.auth_basic.checkpassword': validate_password}
    app_config = {'/': basic_auth,
                  '/bootstrap.css': { 'tools.staticfile.on':True,
                                      'tools.staticfile.filename':app_dir + '/css/bootstrap.min.css' },
                  '/bootstrap.js':  { 'tools.staticfile.on':True,
                                      'tools.staticfile.filename':app_dir + '/js/bootstrap.min.js' },
                  '/jquery.js':     { 'tools.staticfile.on':True,
                                      'tools.staticfile.filename':app_dir + '/js/jquery-1.9.1.min.js' },
                  '/highcharts.js': { 'tools.staticfile.on':True,
                                      'tools.staticfile.filename':app_dir + '/js/highcharts.js' }}

    app = cherrypy.tree.mount(contest, '/drinc/', config=app_config)
    pywsgi.WSGIServer(('', port), app, log=None).serve_forever()

start_date = datetime.datetime.strptime(os.environ['START_DATE'], DATE_FORMAT)
deadline = datetime.datetime.strptime(os.environ['DEADLINE'], DATE_FORMAT)

if __name__ == '__main__':
    db = DatabaseManager()
    db.start()

    contest = PredictionContest(db, start_date, deadline)
    contest.start()
    configure_logging()
    start_server(contest, int(os.environ['PORT']))
