Resetting the contest each month
================================

The code runs on hans, under `/home/dch`.  This document describes how to reset the contest each month.

TODO: Implement an administrator web interface that does all this stuff!

First, remove last month's transactions from the database.  Note that _only_ the `TransactionsByUser` and `TransactionsByStock` column families are truncated - leave `Transactions` alone!

    [root@hans dch]# ./dsc-cassandra-1.0.9/bin/cassandra-cli -h localhost
    Connected to: "Test Cluster" on localhost/9160
    Welcome to Cassandra CLI version 1.0.9

    Type 'help;' or '?' for help.
    Type 'quit;' or 'exit;' to quit.

    [default@unknown] use PredictionContest ;
    Authenticated to keyspace: PredictionContest
    [default@PredictionContest] truncate TransactionsByUser ;
    TransactionsByUser truncated.
    [default@PredictionContest] truncate TransactionsByStock ;
    TransactionsByStock truncated.
    [default@PredictionContest] exit ;

Then edit `server/PredictionsContest.py`:

* Update the `stocks` dictionary (near the top of the file)
  * This should contains stocks that we own, plus zero or more bonus stocks that were discussed at the meeting
  * So remove last month's bonus stocks, add this month's bonus stocks, and make updates according to what we sold or bought
* Update the `start_date` and `deadline` (near the bottom of the file)
  * The start date should usually be 9pm on the day of the meeting
  * The deadline should usually be 6pm on the day one week after the meeting

Finally, restart the server:

* Make sure you're picking up the right python virtualenv:

    ```
    [root@hans dch]# source python26/bin/activate
    (python26)[root@hans dch]#
    ```

* Change into the server directory, and run the `start` script:

    ```
    (python26)[root@hans dch]# cd server
    (python26)[root@hans server]# ./start
    ```
