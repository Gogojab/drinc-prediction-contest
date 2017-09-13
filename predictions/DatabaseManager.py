from apscheduler.scheduler import Scheduler
from decimal import Decimal
import datetime
import pytz
import requests
import threading
from bs4 import BeautifulSoup
from PostgresManager import PostgresManager


class DatabaseManager(object):
    def __init__(self):
        """Initialization"""
        self._updated = threading.Condition()
        london = pytz.timezone('Europe/London')
        self._sched = Scheduler(timezone=london)
        self._db_manager = PostgresManager()
        self.tickers = self._db_manager.get_stocks()
        users_passwords = self._db_manager.get_members()
        self.members = [x for (x, y) in users_passwords]
        self.auth_details = {x: y for (x, y) in users_passwords}

    def start(self):
        """Start the database manager"""
        self._sched.start()
        self._sched.add_cron_job(
            self.update_stock_prices,
            day_of_week='0-4',
            hour='8-17',
            minute='0,15,30,45'
        )

    def wait_for_update(self):
        """Block until the database is updated"""
        with self._updated:
            self._updated.wait()

    def get_requery_delay(self):
        """Say how many seconds it'll be before it's worth re-querying the database"""
        # How long is it until the next 15-minute boundary?
        london = pytz.timezone('Europe/London')
        london_now = datetime.datetime.now(london)
        london_nine_am = london_now.replace(hour=9, minute=0, second=0)
        london_five_pm = london_now.replace(hour=17, minute=0, second=0)

        if london_nine_am <= london_now < london_five_pm:
            # Between 9am and 5pm: wait until next fifteen-minute boundary
            delay = 900 - (((60 * london_now.minute) + london_now.second) % 900)
        else:
            # Wait until 9am - which might be tomorrow
            if london_nine_am < london_now:
                london_nine_am += datetime.timedelta(days=1)

            delay = (london_nine_am - london_now).total_seconds()

        return delay

    def get_stock_expenditure(self, ticker, short):
        """Figure out how much was spent on a given stock"""
        return self._db_manager.get_stock_expenditure(ticker, short)

    def get_member_transactions(self, member):
        """Get the transactions associated with a member"""
        return self._db_manager.get_member_transactions(member)

    def get_current_value(self, transaction):
        """Gets the current value of a transaction, in pennies"""
        return self._db_manager.get_current_value(transaction)

    def get_current_member_value(self, member):
        """Get a member's current value, in pennies"""
        return self._db_manager.get_current_member_value(member)

    def record_purchase(self, member, stock, price, cost, short):
        """Updates the database with a record of a purchase."""
        self._db_manager.record_purchase(member, stock, price, cost, short)

    def get_member_history(self, member, start_date):
        """Get the historical value of a member's portfolio"""
        return self._db_manager.get_member_history(member, start_date)

    def get_stock_price(self, ticker):
        """Gets a stock price, first trying the database and if that fails then
        going to Google and updating the database with the result"""
        price = self.get_stock_price_from_db(ticker)
        if not price:
            price = self.update_stock_price(ticker)

        if price:
            return format(price, '.2f')

    def get_stock_price_from_db(self, ticker):
        """Gets a recent stock price from the database"""
        return self._db_manager.get_stock_price_from_db(ticker)

    def get_stock_price_from_google(self, ticker):
        """Returns the latest stock price from Google Finance"""
        url = 'http://www.google.com/finance?q=%s' % ticker
        try:
            rsp = requests.get(url)
            price = (
                BeautifulSoup(rsp.text, "html.parser")
                .find("div", {"id": "price-panel"})
                .find("span", {"class": "pr"})
                .text
            )
            price = price.strip().replace(',', '')
            price = Decimal(price)
        except:
            price = None

        return price

    def update_member_history(self, member, timestamp, worth):
        """Update the UserHist column family"""
        self._db_manager.update_member_history(member, timestamp, worth)

    def update_stock_prices(self):
        """Update the Stocks column family with all the latest prices"""
        for ticker in self.tickers:
            self.update_stock_price(ticker)

        # Also notify anyone who is waiting to know that this has happened.
        with self._updated:
            self._updated.notifyAll()

    def update_stock_price(self, ticker):
        """Update the Stocks column family with the latest price for a stock"""
        price = self.get_stock_price_from_google(ticker)

        if price:
            self._db_manager.update_stock_price(ticker, price)
        return price

    def get_members(self):
        """Get the list of members"""
        self._db_manager.get_members()

    def get_password_hash(self, member):
        """Get the password hash of a member"""
        return self._db_manager.get_password_hash(member)

    def change_password(self, member, new_password_hash):
        """Update the user's password"""
        return self._db_manager.change_password(member, new_password_hash)
