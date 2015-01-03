DRINC prediction contest
========================

The website for the DRINC monthly prediction contest.

A CherryPy application, using a Postgres database and running on Heroku.

Developing locally
------------------

### Requirements
- The Heroku toolkit (includes _foreman_ to run the project locally)
- Python 2.7
- Virtualenv
- PostgreSQL 9.3 

### Getting started 

- Set up your Python environment using Virtualenv.  The required packages are in requirements.txt.
- Start a Postgres database database and set up the base tables (see `predictions/sql/schema.sql`).
- Configure the application environment in a file called .env in the project root directory.
- Run the server using foreman: `foreman start web`

### Resources

Example .env

	DATABASE_URL=postgres:///drinc
	START_DATE=2014-12-04 20:00:00
	DEADLINE=2014-12-05 20:00:00
	PORT=8080

Deploying to Heroku
-------------------

- Create your Heroku application.
- `git push heroku master`
