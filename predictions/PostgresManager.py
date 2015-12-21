import os
import datetime
import psycopg2
import urlparse


class PostgresManager(object):
    def __init__(self):
        urlparse.uses_netloc.append("postgres")
        url = urlparse.urlparse(os.environ["DATABASE_URL"])

        self.conn = psycopg2.connect(
            database=url.path[1:],
            user=url.username,
            password=url.password,
            host=url.hostname,
            port=url.port)

    def get_stock_expenditure(self, ticker, short):
        """Figure out how much was spent on a given stock"""

        with self.conn.cursor() as cur:
            sql = "SELECT cost FROM transactions INNER JOIN stocks ON stocks.pkey = transactions.stock " \
                  "WHERE ticker = %s AND short = %s"
            cur.execute(sql, (ticker, short))
            self.conn.commit()
            spent = sum([x for (x,) in (cur.fetchall())])

        return spent

    def get_member_transactions(self, member):
        """Get the transactions associated with a member"""

        with self.conn.cursor() as cur:
            sql = "SELECT s.ticker, t.price, t.cost, t.short FROM transactions t " \
                  "INNER JOIN stocks s ON t.stock = s.pkey " \
                  "INNER JOIN members m ON t.member = m.pkey " \
                  "WHERE m.username = %s;"
            cur.execute(sql, (member,))
            transactions = [{'stock': stock, 'price': price, 'cost': cost, 'short':short} for (stock, price, cost, short) in cur.fetchall()]

        return transactions

    def get_current_value(self, transaction):
        """Gets the current value of a transaction, in pennies"""

        with self.conn.cursor() as cur:
            cur = self.conn.cursor()
            sql = "SELECT price FROM stocks WHERE ticker = %s"
            cur.execute(sql, (transaction['stock'],))

            (price,) = cur.fetchone()
            cost = transaction['cost']
            value = (cost * price) / transaction['price']

            if transaction['short']:
                value = cost + cost - value

        return int(value)

    def get_current_member_value(self, member):
        """Get a member's current value, in pennies"""

        transactions = self.get_member_transactions(member)

        total = 0

        for t in transactions:
            total += self.get_current_value(t)

        return total

    def record_purchase(self, member, stock, price, cost, short):
        """Updates the database with a record of a purchase."""

        sql = "INSERT INTO transactions (price, cost, member, stock, short) " \
              "VALUES (%s, %s, (SELECT pkey FROM members WHERE username = %s), " \
              "(SELECT pkey from stocks WHERE ticker = %s), %s)"

        with self.conn.cursor() as cur:
            cur.execute(sql, (price, cost, member, stock, short))
            self.conn.commit()

    def get_stock_price_from_db(self, ticker):
        """Gets a recent stock price from the database"""

        with self.conn.cursor() as cur:
            sql = "SELECT price FROM stocks WHERE ticker = %s"
            cur.execute(sql, (ticker,))
            (price,) = cur.fetchone()

        return price

    def get_member_history(self, member, start_date):
        """Get the historical value of a member's portfolio"""

        sql = "SELECT timestamp, value FROM member_history h INNER JOIN members m ON h.member = m.pkey " \
              "WHERE m.username = %s AND timestamp >= %s"
        with self.conn.cursor() as cur:
            cur.execute(sql, (member, start_date))
            history = {date: value for (date, value) in cur.fetchall()}
        return history

    def update_member_history(self, member, timestamp, worth):
        """Update the UserHist column family"""

        print "Updating history for member %s with value %d" % (member, worth)
        sql = "UPDATE member_history SET value = %(worth)s WHERE timestamp = %(timestamp)s AND " \
              "member = (SELECT pkey FROM members WHERE username = %(member)s); " \
              "INSERT INTO member_history (member, timestamp, value) " \
              "SELECT (SELECT pkey FROM members WHERE username = %(member)s), %(timestamp)s, %(worth)s " \
              "WHERE NOT EXISTS (SELECT 1 FROM member_history WHERE timestamp = %(timestamp)s AND " \
              "member = (SELECT pkey FROM members WHERE username = %(member)s))"
        with self.conn.cursor() as cur:
            try:
                cur.execute(sql, {'member': member, 'timestamp': timestamp, 'worth': worth})
                self.conn.commit()
            except Exception, e:
                print e

    def update_stock_histories(self):
        """Update the StockHist column family"""
        # for stock in self.tickers:
        #     dict = self.get_stock_history_from_google(stock)
        #     stock_history_col.insert(stock, dict)

        # I'm not sure what the stock history is actually for.
        print "Not updating stock histories."


    def update_stock_price(self, ticker, price):
        """Update the Stocks column family with the latest price for a stock"""
        sql = "UPDATE stocks SET price = %(price)s WHERE ticker = %(ticker)s; " \
              "INSERT INTO stocks (ticker, price) SELECT %(ticker)s, %(price)s " \
              "WHERE NOT EXISTS (SELECT 1 FROM stocks WHERE ticker = %(ticker)s);"
        with self.conn.cursor() as cur:
            cur.execute(sql, {'price' : price, 'ticker' : ticker})
            self.conn.commit()

    def get_members(self):
        """Get the list of DRINC members"""
        sql = "SELECT username, password FROM members;"
        with self.conn.cursor() as cur:
            cur.execute(sql)
            members = [(x,y) for (x,y) in cur.fetchall()]
            print "get_members"
            members
        return members

    def get_stocks(self):
        """Get the list of current stocks"""
        sql = "SELECT ticker, name FROM current_stocks;"
        with self.conn.cursor() as cur:
            cur.execute(sql)
            stocks = {t : n for (t, n) in cur.fetchall()}
        return stocks

    def get_password_hash(self, member):
        sql = "SELECT password FROM members WHERE username = %s"

        with self.conn.cursor() as cur:
            cur.execute(sql, (member,))
            password_tuple = cur.fetchone()
        if password_tuple is not None:
            return password_tuple[0]
        else:
            return None

    def change_password(self, member, new_password_hash):
        sql = "UPDATE members SET password = %s WHERE username = %s"
        with self.conn.cursor() as cur:
            try:
                cur.execute(sql, (new_password_hash, member))
                self.conn.commit()
                return True
            except Exception, e:
                print "Failed to change password for %s" % member
                return False

if __name__ == '__main__':
    pgm = PostgresManager()
    # pgm.get_stock_expenditure("TEST")

    # trans = pgm.get_member_transactions("WAN")
    # current_value = pgm.get_current_value(trans[0])
    # print current_value
    #
    # value = pgm.get_current_member_value("WAN")
    # print "Value of WAN is %s" % value
    #
    # pgm.record_purchase("WAN", 'TREE', 243, 34)
    #
    # price = pgm.get_stock_price_from_db('TREE')
    # print "Price of tree is %s" % price
    #
    # today = datetime.date.today()
    # timestamp = datetime.datetime.combine(today, datetime.time())
    # pgm.update_member_history('WAN', timestamp, 123.23)
    #
    # start_date = datetime.datetime(2014, 10, 20)
    # history = pgm.get_member_history('WAN', start_date)
    # print history
    #
    # pgm.update_stock_price('GOOG', 234.25)

    print pgm.get_members()

    print pgm.get_stocks()

    print pgm.get_password_hash('WAN')
    print pgm.get_password_hash('WAA')