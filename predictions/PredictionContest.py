from gevent import monkey; monkey.patch_all()
import cherrypy
from apscheduler.scheduler import Scheduler
from Cheetah.Template import Template
from decimal import Decimal, ROUND_DOWN
import csv
import datetime
from gevent import pywsgi
import logging
from logging import handlers
import os.path
import pycassa
import random
import simplejson as json
import threading
import time
import tools.auth_kerberos
import tools.auth_members
import urllib2
import uuid
import sys
sys.path.append('templates')

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
start_date = datetime.datetime(2012, 12, 18, 18)
deadline = datetime.datetime(2012, 12, 24, 18)
current_dir = os.path.dirname(os.path.abspath(__file__))

# Database access.
db_lock = threading.Lock()
pool = pycassa.ConnectionPool('PredictionContest', server_list=['flash:9160'])
transactions_by_user_col = pycassa.ColumnFamily(pool, 'TransactionsByUser')
transactions_by_stock_col = pycassa.ColumnFamily(pool, 'TransactionsByStock')
transactions_col = pycassa.ColumnFamily(pool, 'Transactions')
user_history_col = pycassa.ColumnFamily(pool, 'UserHist')
stock_history_col = pycassa.ColumnFamily(pool, 'StockHist')
stocks_col = pycassa.ColumnFamily(pool, 'Stocks')

class PredictionContest(object):
    def __init__(self):
        self.sched = Scheduler()

    def start(self):
        self.sched.start()
        self.sched.add_cron_job(self.update_stock_histories, day_of_week='0-4', hour=9)
        self.sched.add_cron_job(self.update_user_histories, day_of_week='0-4', hour=18)
        self.sched.add_cron_job(self.update_stock_prices, day_of_week='0-4', hour='8-17', minute='0,15,30,45')

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
        stocks = self.get_stock_data(full=False)
        users = self.get_leaderboard()
        data = {'stocks':stocks, 'users':users}
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
        if datetime.datetime.now() < deadline:
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

        price = self.update_stock_price(stock)
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

        if datetime.datetime.now() > deadline:
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
        db_lock.acquire()
        try:
            user = cherrypy.request.login.split('@')[0].upper()
            if self.is_purchase_allowed(user, stock, price, cost):
                self.commit_purchase(user, stock, price, cost)

        finally:
            db_lock.release()

        raise cherrypy.HTTPRedirect('home')

    @cherrypy.expose
    @cherrypy.tools.auth_kerberos()
    @cherrypy.tools.auth_members(users=members)
    def analysis(self):
        """Analysis page"""
        if datetime.datetime.now() < deadline:
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
        expenditure = []
        for ticker in stocks:
            spent = self.get_stock_expenditure(ticker)
            if spent != 0:
                expenditure.append({'name':ticker, 'y':spent})

        return sorted(expenditure, key=lambda val: val['y'], reverse=True)

    def get_stock_expenditure(self, ticker):
        """Figure out how much was spent on a given stock"""
        try:
            transactions = transactions_by_stock_col.get(ticker)
            spent = sum([int(x) for x in transactions.values()])
        except:
            spent = 0

        return spent

    def make_page(self, template='home.tmpl', details={}):
        """Make a page: figure out the generic information required for the wrapper and then
        use the provided template"""
        data = self.get_stock_data()
        users = self.get_leaderboard()
        past_deadline = datetime.datetime.now() > deadline
        base = {'tickers':data, 'users':users, 'past_deadline':past_deadline}
        t = Template(file=current_dir + '/templates/' + template, searchList=[base, details])
        return str(t)

    def get_stock_data(self, full=True):
        """Get the latest stock prices"""
        if full:
            make_data = lambda x: {'ticker': x, 'price': self.get_stock_price(x), 'full_name': stocks[x]}
        else:
            make_data = lambda x: {'ticker': x, 'price': self.get_stock_price(x)}
        data = [make_data(stock) for stock in stocks]
        return sorted(data, key=lambda x: x['ticker'])

    def get_user_transactions(self, user):
        """Get the transactions associated with a user"""
        try:
            transaction_ids = transactions_by_user_col.get(user)
            transactions = [transactions_col.get(tid) for tid in transaction_ids]
        except:
            transactions = []
        return transactions

    def get_account_details(self, user):
        """Get the details describing a user account"""
        transactions = self.get_user_transactions(user)

        total = 0
        spent = 0
        for transaction in transactions:
            # Get the current value, in pounds, of this transaction...
            value = self.get_current_value(transaction)
            value = self.pennies_to_pounds(value)
            transaction['value'] = value

            # ... and the cost.
            cost = self.pennies_to_pounds(transaction['cost'])
            transaction['cost'] = cost

            # Update the total value and spend.
            total = total + value
            spent = spent + cost

        if datetime.datetime.now() < deadline:
            cash = 1000 - spent
        else:
            cash = 0

        account = {'user':user, 'transactions':transactions, 'total':total, 'spent':spent, 'cash':cash}
        return account

    def get_current_value(self, transaction):
        """Gets the current value of a transaction, in pennies"""
        stock = stocks_col.get(transaction['stock'])
        cost = transaction['cost']
        value = (cost * stock['price']) / transaction['price']
        return int(value)

    def get_value_at(self, transaction, date):
        """Gets the value of a transaction on a particular date, in pennies"""
        cost = transaction['cost']
        stock = transaction['stock']
        purchase_price = transaction['price']
        if transaction['date'] < date:
            try:
                history = stock_history_col.get(stock, column_start=date, column_count=1, column_reversed=True)
                for (date, price) in history.items():
                    value = (cost * price) / purchase_price
            except:
                value = 0
        else:
            value = 0

        return int(value)

    def get_current_user_value(self, member):
        """Get a user's current value, in pennies"""
        try:
            tids = transactions_by_user_col.get(member)
        except:
            tids = {}

        total = 0
        for tid in tids:
            transaction = transactions_col.get(tid)
            total = total + self.get_current_value(transaction)

        return total

    def get_user_value_at(self, member, date):
        """Get a user's current value on a particular date, in pennies"""
        try:
            tids = transactions_by_user_col.get(member)
        except:
            tids = {}

        total = 0
        for tid in tids:
            transaction = transactions_col.get(tid)
            total = total + self.get_value_at(transaction, date)

        return total

    def get_leaderboard(self):
        """Calculates the leaderboard"""
        users = []
        for member in members:
            data = {'initials':member}
            worth = self.get_current_user_value(member)
            data['value'] = self.pennies_to_pounds(worth)
            users.append(data)

        sort_key = lambda data: data['value']
        users = sorted(users, key=sort_key, reverse=True)
        return users

    def is_purchase_allowed(self, user, stock, price, cost):
        """Decide whether a purchase is allowed"""
        # Only allow positive expenditure!
        if cost <= 0:
            return False

        # Only allow purchases of the permitted stocks.
        if stock not in stocks:
            return False

        # Get the transactions that this user has already made.
        try:
            user_transactions = transactions_by_user_col.get(user)
        except:
            user_transactions = {}

        # Don't allow more than three purchases per user.
        if len(user_transactions) > 2:
            return False

        # Figure out how much the user has so far spent.
        spend = 0
        for transaction_id in user_transactions:
            try:
                transaction = transactions_col.get(transaction_id)
                spend = spend + transaction['cost']
            except:
                pass

        # Don't allow over-spending.
        if spend + cost > 100000:
            return False

        return True

    def commit_purchase(self, user, stock, price, cost):
        """Updates the database with a record of a purchase."""
        transaction = {'user':user,
                       'stock':stock,
                       'date':datetime.datetime.utcnow(),
                       'price':price,
                       'cost':cost}
        transaction_id = uuid.uuid4()

        transactions_col.insert(transaction_id, transaction)
        transactions_by_user_col.insert(user, {transaction_id:stock})
        transactions_by_stock_col.insert(stock, {transaction_id:cost})

    def pennies_to_pounds(self, pennies):
        """Utility function for converting pennies to pounds"""
        pounds = Decimal(pennies) / 100
        pounds = pounds.quantize(Decimal('.01'))
        return pounds

    def get_user_history(self, user):
        """Get the historical value of a user's portfolio"""
        values=[]
        data = user_history_col.get(user, column_start=start_date)
        for (date,value) in data.iteritems():
            if value > 0:
                utc = time.mktime(date.timetuple())
                values.append([1000 * utc, value])

        today = datetime.date.today()
        timenow = datetime.datetime.combine(today, datetime.time())
        if timenow.date() > date.date():
            value = self.get_current_user_value(user)
            if value > 0:
                utc = time.mktime(timenow.timetuple())
                values.append([1000 * utc, value])

        return values

    def get_stock_history_from_google(self, ticker):
        """Goes to the internet, and returns a dictionary in which the keys are dates,
        and the values are prices"""
        url = 'http://www.google.com/finance/historical?q=%s&output=csv' % ticker
        data = urllib2.urlopen(url).read()

        reader = csv.reader(data.split())
        reader.next()

        dict = {}
        for row in reader:
            (date, closing) = (row[0], row[4])
            struct = time.strptime(date, '%d-%b-%y')
            dt = datetime.datetime(*struct[:6])
            price = Decimal(closing)
            dict[dt] = price

        return dict

    def get_stock_price(self, ticker):
        """Gets a stock price, first trying the database and if that fails then
        going to Google and updating the database with the result"""
        price = self.get_stock_price_from_db(ticker)
        if not price:
            price = self.update_stock_price(ticker)
        return price

    def get_stock_price_from_db(self, ticker):
        """Gets a recent stock price from the database"""
        try:
            price = stocks_col.get(ticker)['price']
        except:
            price = None

        return price

    def get_stock_price_from_google(self, ticker):
        """Returns the latest stock price from Google Finance"""
        url = 'http://finance.google.com/finance/info?q=%s' % ticker
        try:
            lines = urllib2.urlopen(url).read().splitlines()
            quote = json.loads(''.join([x for x in lines if x not in ('// [', ']')]))
            price = quote['l_cur'].replace(',','')
            price = Decimal(price[3:])
        except:
            price = None

        return price

    def update_stock_histories(self):
        """Update the StockHist column family"""
        for stock in stocks:
            dict = self.get_stock_history_from_google(stock)
            stock_history_col.insert(stock, dict)

    def update_user_histories(self):
        """Update the UserHist column family"""
        today = datetime.date.today()
        timestamp = datetime.datetime.combine(today, datetime.time())
        for member in members:
            worth = self.get_current_user_value(member)
            user_history_col.insert(member, {timestamp: worth})

    def update_stock_prices(self):
        """Update the Stocks column family with all the latest prices"""
        for ticker in stocks:
            self.update_stock_price(ticker)

    def update_stock_price(self, ticker):
        """Update the Stocks column family with the latest price for a stock"""
        price = self.get_stock_price_from_google(ticker)
        if price:
            stocks_col.insert(ticker, {'price':price})
        return price

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

    maxBytes = getattr(log, "rot_maxBytes", 10000000)
    backupCount = getattr(log, "rot_backupCount", 1000)

    # Make sure we have a directory to put the logs in.
    if not os.path.exists("logs"):
        os.makedirs("logs")

    # Make a new RotatingFileHandler for the error log.
    fname = getattr(log, "rot_error_file", "logs/error.log")
    h = handlers.RotatingFileHandler(fname, 'a', maxBytes, backupCount)
    h.setLevel(logging.DEBUG)
    h.setFormatter(cherrypy._cplogging.logfmt)
    log.error_log.addHandler(h)

    # Make a new RotatingFileHandler for the access log.
    fname = getattr(log, "rot_access_file", "logs/access.log")
    h = handlers.RotatingFileHandler(fname, 'a', maxBytes, backupCount)
    h.setLevel(logging.DEBUG)
    h.setFormatter(cherrypy._cplogging.logfmt)
    log.access_log.addHandler(h)

config = {'/': { 'tools.sessions.on':True },
          '/bootstrap.css': { 'tools.staticfile.on':True,
                              'tools.staticfile.filename':current_dir + '/css/bootstrap.min.css' },
          '/bootstrap.js':  { 'tools.staticfile.on':True,
                              'tools.staticfile.filename':current_dir + '/js/bootstrap.min.js' },
          '/jquery.js':     { 'tools.staticfile.on':True,
                              'tools.staticfile.filename':current_dir + '/js/jquery-1.8.3.min.js' },
          '/highcharts.js': { 'tools.staticfile.on':True,
                              'tools.staticfile.filename':current_dir + '/js/highcharts.js' }}

if __name__ == "__main__":
    configure_logging()

    contest = PredictionContest()
    contest.start()
    app = cherrypy.tree.mount(contest, '/drinc/', config=config)

    # cherrypy.config.update({'server.socket_host': '0.0.0.0',
    #                         'server.socket_port': 7070})
    # cherrypy.engine.start()
    # cherrypy.engine.block()
    pywsgi.WSGIServer(('', 7070), app, log=None).serve_forever()
