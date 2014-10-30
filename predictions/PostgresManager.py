import os
import datetime
import psycopg2
import urlparse


class PostgresManager(object):
    def __init__(self, members, tickers):
        self.members = members
        self.tickers = tickers

        urlparse.uses_netloc.append("postgres")
        url = urlparse.urlparse(os.environ["DATABASE_URL"])

        self.conn = psycopg2.connect(
            database=url.path[1:],
            user=url.username,
            password=url.password,
            host=url.hostname,
            port=url.port)

    def get_stock_expenditure(self, ticker):
        """Figure out how much was spent on a given stock"""
        # try:
        # transactions = transactions_by_stock_col.get(ticker)

        with self.conn.cursor() as cur:
          sql = "SELECT cost FROM transactions INNER JOIN stocks ON stocks.pkey = transactions.stock WHERE ticker = %s"
          cur.execute(sql, (ticker,))
          self.conn.commit()
          spent = sum([x for (x,) in (cur.fetchall())])
          print "Spent %d" % spent

        return spent


    def get_member_transactions(self, member):
        """Get the transactions associated with a member"""

        with self.conn.cursor() as cur:
            sql = "SELECT stock, price, cost FROM transactions_stocks WHERE member = %s"
            cur.execute(sql, (member,))

            transactions = [{'stock': stock, 'price': price, 'cost': cost} for (stock, price, cost) in cur.fetchall()]

            # print transactions
            # transaction_ids = transactions_by_member_col.get(member)
            #     transactions = [transactions_col.get(tid) for tid in transaction_ids]
            # except:
            #     transactions = []
        return transactions

    def get_current_value(self, transaction):
        """Gets the current value of a transaction, in pennies"""

        with self.conn.cursor() as cur:
            cur = self.conn.cursor()
            sql = "SELECT price FROM stocks WHERE ticker = %s"
            cur.execute(sql, (transaction['stock'],))

            (price,) = cur.fetchone()

            print "Price is %s" % price
            # stock = stocks_col.get(transaction['stock'])
            cost = transaction['cost']
            print cost
            print price
            print transaction['price']
            value = (cost * price) / transaction['price']

        return int(value)

    def get_current_member_value(self, member):
        """Get a member's current value, in pennies"""
        # try:
        #tids = transactions_by_member_col.get(member)

        #except:
        #    tids = {}

        transactions = self.get_member_transactions(member)

        total = 0

        for t in transactions:
            total += self.get_current_value(t)

        return total

    def record_purchase(self, member, stock, price, cost):
        """Updates the database with a record of a purchase."""
        # transaction = {'user': member,
        #                'stock': stock,
        #                'date': datetime.datetime.utcnow(),
        #                'price': price,
        #                'cost': cost}
        # transaction_id = uuid.uuid4()
        #
        # transactions_col.insert(transaction_id, transaction)
        # transactions_by_member_col.insert(member, {transaction_id: stock})
        # transactions_by_stock_col.insert(stock, {transaction_id: cost})

        sql = "INSERT INTO transactions (price, cost, member, stock) " \
              "VALUES (%s, %s, %s, (SELECT pkey from stocks WHERE ticker = %s))"

        with self.conn.cursor() as cur:
            cur.execute(sql, (price, cost, member, stock))


    def get_stock_price_from_db(self, ticker):
        """Gets a recent stock price from the database"""
        # try:
        #     price = stocks_col.get(ticker)['price']
        # except:
        #     price = None

        with self.conn.cursor() as cur:
            sql = "SELECT price FROM stocks WHERE ticker = %s"
            cur.execute(sql, (ticker,))
            (price,) = cur.fetchone()

        return price


    def get_member_history(self, member, start_date):
        """Get the historical value of a member's portfolio"""
        # try:
        #
        #     history = member_history_col.get(member, column_start=start_date)
        # except:
        #     history = {}

        sql = "SELECT timestamp, value FROM member_history WHERE member = %s AND timestamp >= %s;"
        with self.conn.cursor() as cur:
            cur.execute(sql, (member, start_date))
            history = cur.fetchall()

        # Convert this into a dictionary.
        # History is a list of date, value pairs.

        return history


    def update_member_history(self, member, timestamp, worth):
        """Update the UserHist column family"""
        # member_history_col.insert(member, {timestamp: worth})

        sql = "INSERT INTO member_history (member, timestamp, value) VALUES (%s, %s, %s)"
        with self.conn.cursor() as cur:
            cur.execute(sql, (member, timestamp, worth))

    def update_stock_histories(self):
        """Update the StockHist column family"""
        # for stock in self.tickers:
        #     dict = self.get_stock_history_from_google(stock)
        #     stock_history_col.insert(stock, dict)

        # I'm not sure what the stock history is actually for.
        print "Not updating stock histories."


    def update_stock_price(self, ticker, price):
        """Update the Stocks column family with the latest price for a stock"""
        sql = "UPDATE stocks SET price = %(price)s WHERE ticker = %(ticker)s; INSERT INTO stocks (ticker, price) SELECT %(ticker)s, %(price)s WHERE NOT EXISTS (SELECT 1 FROM stocks WHERE ticker = %(ticker)s);"
        with self.conn.cursor() as cur:
            cur.execute(sql, {'price' : price, 'ticker' : ticker})


if __name__ == '__main__':
    pgm = PostgresManager(['WAN', 'DCH'], ['TEST'])
    # pgm.get_stock_expenditure("TEST")

    trans = pgm.get_member_transactions("WAN")
    current_value = pgm.get_current_value(trans[0])
    print current_value

    value = pgm.get_current_member_value("WAN")
    print "Value of WAN is %s" % value

    pgm.record_purchase("WAN", 'TREE', 243, 34)

    price = pgm.get_stock_price_from_db('TREE')
    print "Price of tree is %s" % price

    today = datetime.date.today()
    timestamp = datetime.datetime.combine(today, datetime.time())
    pgm.update_member_history('WAN', timestamp, 123.23)

    start_date = datetime.datetime(2014, 10, 20)
    history = pgm.get_member_history('WAN', start_date)
    print history

    pgm.update_stock_price('GOOG', 234.25)