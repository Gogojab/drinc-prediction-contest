import cherrypy
from classes.application import Application
from apscheduler.scheduler import Scheduler
from Cheetah.Template import Template
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timedelta
import csv
import pycassa
import simplejson as json
import threading
import time
import urllib2
import uuid
import locale
locale.setlocale(locale.LC_NUMERIC, '')

application_class_name = 'PredictionsContest'
members = ['CRS', 'DCH', 'DHM', 'DT', 'ENH', 'GJC', 'JAC', 'JAG2', 'JJL', 'JTR', 'MAM', 'MRR']
stocks = ['LON:BYG', 'LON:CINE', 'LON:CMX', 'LON:DLAR', 'LON:EMG', 'LON:FSTA', 'LON:GAW',
          'LON:GRG', 'LON:HIK', 'LON:LLOY', 'LON:MRO', 'LON:NETD', 'LON:NXR', 'LON:OMG',
          'LON:PSN', 'LON:SHP', 'LON:SLN', 'LON:TSCO', 'LON:ZZZ']
deadline = datetime(2012, 11, 26, 18)

# Database access.
db_lock = threading.Lock()
pool = pycassa.ConnectionPool('PredictionContest')
transactions_by_user_col = pycassa.ColumnFamily(pool, 'TransactionsByUser')
transactions_by_stock_col = pycassa.ColumnFamily(pool, 'TransactionsByStock')
transactions_col = pycassa.ColumnFamily(pool, 'Transactions')
stock_history_col = pycassa.ColumnFamily(pool, 'StockHist')
stocks_col = pycassa.ColumnFamily(pool, 'Stocks')

class PredictionsContest(Application):
    def __init__(self, root_url='', cwd=''):
        Application.__init__(self, root_url, cwd)
        self.sched = Scheduler()

    def build(self):
        self.set_config(self.cwd + '/application.conf')
        self.add_page('/home', self.home)
        self.add_page('/purchase', self.purchase)
        self.add_page('/submit_purchase', self.submit_purchase)
        self.add_page('/confirm_purchase', self.confirm_purchase)

    def setup(self):
        self.sched.start()
        self.sched.add_cron_job(self.update_stock_histories, day_of_week='0-4', hour=9)
        self.sched.add_cron_job(self.update_stock_prices, day_of_week='0-4', hour='8-17', minute='0,15,30,45')

    @cherrypy.expose
    @cherrypy.tools.auth_kerberos()
    @cherrypy.tools.auth_members(users=members)
    def home(self):
        """Home page for the predictions contest"""
        user = cherrypy.request.login.split('@')[0].upper()
        account = self.get_account_details(user)
        innerTemplate = Template(file=self.cwd + '/account.tmpl', searchList=[account])
        page = self.make_page(str(innerTemplate))
        return page

    def make_page(self, inner):
        """Make a page, by putting the inner section into our wrapper"""
        data = [{'ticker':ticker, 'price':self.get_stock_price(ticker)} for ticker in stocks]
        users = self.get_leaderboard()
        t = Template(file=self.cwd + '/wrapper.tmpl',
                     searchList=[{'inner':inner,
                                  'stocks':data,
                                  'users':users}])
        return str(t)

    def get_account_details(self, user):
        """Get the details describing a user account"""
        try:
            transaction_ids = transactions_by_user_col.get(user)
            transactions = [transactions_col.get(tid) for tid in transaction_ids]
        except:
            transactions = []

        total = 0
        spent = 0
        for transaction in transactions:
            # Get the current value, in pounds, of this transaction...
            value = self.get_current_value(transaction)
            transaction['value'] = value

            # ... and the cost.
            cost = Decimal(transaction['cost']) / 100
            cost = cost.quantize(Decimal('.01'), rounding=ROUND_DOWN)
            transaction['cost'] = cost

            # Update the total value and spend.
            total = total + value
            spent = spent + cost

        if datetime.now() < deadline:
            cash = 1000 - spent
        else:
            cash = 0

        account = {'transactions':transactions, 'total':total, 'spent':spent, 'cash':cash}
        return account

    def get_current_value(self, transaction):
        """Gets the current value of a transaction, as read from the database"""
        stock = stocks_col.get(transaction['stock'])
        cost = transaction['cost']
        value = (cost * stock['price']) / transaction['price']
        value = Decimal(str(value)) / 100
        value = value.quantize(Decimal('.01'), rounding=ROUND_DOWN)
        return value

    def get_leaderboard(self):
        """Calculates the leaderboard"""
        users = []
        for member in members:
            data = {'initials':member}
            try:
                tids = transactions_by_user_col.get(member)
            except:
                tids = {}

            total = 0
            for tid in tids:
                transaction = transactions_col.get(tid)
                total = total + self.get_current_value(transaction)
            data['value'] = total
            users.append(data)

        sort_key = lambda data: data['value']
        users = sorted(users, key=sort_key, reverse=True)
        return users

    @cherrypy.expose
    @cherrypy.tools.auth_kerberos()
    @cherrypy.tools.auth_members(users=members)
    def purchase(self):
        """Page to purchase a stock"""
        innerTemplate = Template(file=self.cwd + '/purchase.tmpl', searchList=[{'stocks':stocks}])
        page = self.make_page(str(innerTemplate))
        return page

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

        price = self.get_stock_price_from_google(stock)
        if not price:
            raise cherrypy.HTTPRedirect('home')

        pennies = int(100 * pounds)
        cherrypy.session['stock'] = stock
        cherrypy.session['price'] = price
        cherrypy.session['cost'] = pennies
        cherrypy.session['offerExpires'] = datetime.utcnow() + timedelta(seconds=30)
        innerTemplate = Template(file=self.cwd + '/confirm_purchase.tmpl',
                                 searchList=[{'stock':stock, 'cost': pounds, 'price':price}])
        page = self.make_page(str(innerTemplate))
        return page

    @cherrypy.expose
    @cherrypy.tools.auth_kerberos()
    @cherrypy.tools.auth_members(users=members)
    def submit_purchase(self, cancel=False):
        """Submit a purchase, after confirming that it is really what the user wants to do"""
        if cancel:
            raise cherrypy.HTTPRedirect('home')

        if datetime.now() > deadline:
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
        if datetime.utcnow() > offerExpires:
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
                       'date':datetime.utcnow(),
                       'price':price,
                       'cost':cost}
        transaction_id = uuid.uuid4()

        transactions_col.insert(transaction_id, transaction)
        transactions_by_user_col.insert(user, {transaction_id:stock})
        transactions_by_stock_col.insert(stock, {transaction_id:cost})

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
            dt = datetime(*struct[:6])
            price = float(closing)
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
            price = quote['l_cur']
            price = locale.atof(price[3:])
        except:
            price = None

        return price

    def update_stock_histories(self):
        """Update the StockHist column family"""
        for stock in stocks:
            dict = self.get_stock_history_from_google(stock)
            stock_history_col.insert(stock, dict)

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
