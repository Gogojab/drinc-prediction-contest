
--
-- PostgreSQL database dump
--

SET statement_timeout = 0;
SET lock_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET client_min_messages = warning;

--
-- Name: plpgsql; Type: EXTENSION; Schema: -; Owner: 
--

CREATE EXTENSION IF NOT EXISTS plpgsql WITH SCHEMA pg_catalog;


--
-- Name: EXTENSION plpgsql; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION plpgsql IS 'PL/pgSQL procedural language';


SET search_path = public, pg_catalog;

SET default_tablespace = '';

SET default_with_oids = false;

--
-- Name: member_history; Type: TABLE; Schema: public; Tablespace: 
--

CREATE TABLE member_history (
    pkey integer NOT NULL,
    "timestamp" timestamp without time zone,
    value double precision,
    member integer
);


--
-- Name: member_history_pkey_seq; Type: SEQUENCE; Schema: public; 
--

CREATE SEQUENCE member_history_pkey_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: member_history_pkey_seq; Type: SEQUENCE OWNED BY; Schema: public; 
--

ALTER SEQUENCE member_history_pkey_seq OWNED BY member_history.pkey;


--
-- Name: members; Type: TABLE; Schema: public; Tablespace: 
--

CREATE TABLE members (
    pkey integer NOT NULL,
    username text,
    password text
);


--
-- Name: members_pkey_seq; Type: SEQUENCE; Schema: public; 
--

CREATE SEQUENCE members_pkey_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: members_pkey_seq; Type: SEQUENCE OWNED BY; Schema: public; 
--

ALTER SEQUENCE members_pkey_seq OWNED BY members.pkey;


--
-- Name: stocks; Type: TABLE; Schema: public; Tablespace: 
--

CREATE TABLE stocks (
  pkey serial NOT NULL,
  ticker text NOT NULL,
  price double precision,
  name text,
  bought date DEFAULT ('now'::text)::date,
  sold date

);


--
-- Name: stocks_pkey_seq; Type: SEQUENCE; Schema: public; 
--

CREATE SEQUENCE stocks_pkey_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: stocks_pkey_seq; Type: SEQUENCE OWNED BY; Schema: public; 
--

ALTER SEQUENCE stocks_pkey_seq OWNED BY stocks.pkey;


--
-- Name: transactions; Type: TABLE; Schema: public; Tablespace: 
--

CREATE TABLE transactions (
    pkey integer NOT NULL,
    date date,
    price double precision,
    cost integer,
    stock integer,
    member integer
);


--
-- Name: transactions_pkey_seq; Type: SEQUENCE; Schema: public; 
--

CREATE SEQUENCE transactions_pkey_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


CREATE OR REPLACE VIEW current_stocks AS 
 SELECT stocks.pkey,
    stocks.ticker,
    stocks.price,
    stocks.name
   FROM stocks
  WHERE stocks.bought <= 'now'::text::date AND (stocks.sold IS NULL OR stocks.sold > 'now'::text::date);

--
-- Name: transactions_pkey_seq; Type: SEQUENCE OWNED BY; Schema: public; 
--

ALTER SEQUENCE transactions_pkey_seq OWNED BY transactions.pkey;


--
-- Name: pkey; Type: DEFAULT; Schema: public; 
--

ALTER TABLE ONLY member_history ALTER COLUMN pkey SET DEFAULT nextval('member_history_pkey_seq'::regclass);


--
-- Name: pkey; Type: DEFAULT; Schema: public; 
--

ALTER TABLE ONLY members ALTER COLUMN pkey SET DEFAULT nextval('members_pkey_seq'::regclass);


--
-- Name: pkey; Type: DEFAULT; Schema: public; 
--

ALTER TABLE ONLY stocks ALTER COLUMN pkey SET DEFAULT nextval('stocks_pkey_seq'::regclass);


--
-- Name: pkey; Type: DEFAULT; Schema: public; 
--

ALTER TABLE ONLY transactions ALTER COLUMN pkey SET DEFAULT nextval('transactions_pkey_seq'::regclass);


--
-- Name: member_history_pkey; Type: CONSTRAINT; Schema: public; Tablespace: 
--

ALTER TABLE ONLY member_history
    ADD CONSTRAINT member_history_pkey PRIMARY KEY (pkey);


--
-- Name: members_pkey; Type: CONSTRAINT; Schema: public; Tablespace: 
--

ALTER TABLE ONLY members
    ADD CONSTRAINT members_pkey PRIMARY KEY (pkey);


--
-- Name: members_username_unq; Type: CONSTRAINT; Schema: public; Tablespace: 
--

ALTER TABLE ONLY members
    ADD CONSTRAINT members_username_unq UNIQUE (username);


--
-- Name: primary_key; Type: CONSTRAINT; Schema: public; Tablespace: 
--

ALTER TABLE ONLY transactions
    ADD CONSTRAINT primary_key PRIMARY KEY (pkey);


--
-- Name: stocks_pkey; Type: CONSTRAINT; Schema: public; Tablespace: 
--

ALTER TABLE ONLY stocks
    ADD CONSTRAINT stocks_pkey PRIMARY KEY (pkey);


--
-- Name: unique_stocks; Type: CONSTRAINT; Schema: public; Tablespace: 
--

ALTER TABLE ONLY stocks
    ADD CONSTRAINT unique_stocks UNIQUE (ticker);


--
-- Name: member_fkey; Type: FK CONSTRAINT; Schema: public; 
--

ALTER TABLE ONLY transactions
    ADD CONSTRAINT member_fkey FOREIGN KEY (member) REFERENCES members(pkey);


--
-- Name: member_history_member_fkey; Type: FK CONSTRAINT; Schema: public; 
--

ALTER TABLE ONLY member_history
    ADD CONSTRAINT member_history_member_fkey FOREIGN KEY (member) REFERENCES members(pkey);


--
-- Name: stock_fkey; Type: FK CONSTRAINT; Schema: public; 
--

ALTER TABLE ONLY transactions
    ADD CONSTRAINT stock_fkey FOREIGN KEY (stock) REFERENCES stocks(pkey);


--
-- Name: public; Type: ACL; Schema: -; 
--

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO PUBLIC;


--
-- PostgreSQL database dump complete
--

