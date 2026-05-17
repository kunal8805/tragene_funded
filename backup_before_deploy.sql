--
-- PostgreSQL database dump
--

\restrict 0IOUdwOcBKUH0eNr6E3F4xGGCzQfbVV8CJ2uTDjiuUdmUJ8QaweairMKoB88Wu5

-- Dumped from database version 18.3 (Ubuntu 18.3-1)
-- Dumped by pg_dump version 18.3 (Ubuntu 18.3-1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: tragene_user
--

-- *not* creating schema, since initdb creates it


ALTER SCHEMA public OWNER TO tragene_user;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: account_snapshot; Type: TABLE; Schema: public; Owner: tragene_user
--

CREATE TABLE public.account_snapshot (
    id integer NOT NULL,
    challenge_purchase_id integer NOT NULL,
    "timestamp" timestamp with time zone,
    ea_version character varying(20),
    terminal_build integer,
    mt5_login character varying(100),
    broker_server character varying(200),
    balance double precision NOT NULL,
    equity double precision NOT NULL,
    free_margin double precision,
    margin_used double precision,
    credit double precision,
    leverage integer,
    currency character varying(10),
    profit_from_start double precision,
    drawdown_from_peak double precision,
    open_positions_count integer,
    is_archived boolean,
    archived_at timestamp with time zone
);


ALTER TABLE public.account_snapshot OWNER TO tragene_user;

--
-- Name: account_snapshot_id_seq; Type: SEQUENCE; Schema: public; Owner: tragene_user
--

CREATE SEQUENCE public.account_snapshot_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.account_snapshot_id_seq OWNER TO tragene_user;

--
-- Name: account_snapshot_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tragene_user
--

ALTER SEQUENCE public.account_snapshot_id_seq OWNED BY public.account_snapshot.id;


--
-- Name: admin_log; Type: TABLE; Schema: public; Owner: tragene_user
--

CREATE TABLE public.admin_log (
    id integer NOT NULL,
    admin_id integer NOT NULL,
    action character varying(100) NOT NULL,
    target_type character varying(50),
    target_id integer,
    details text,
    ip_address character varying(50),
    created_at timestamp with time zone
);


ALTER TABLE public.admin_log OWNER TO tragene_user;

--
-- Name: admin_log_id_seq; Type: SEQUENCE; Schema: public; Owner: tragene_user
--

CREATE SEQUENCE public.admin_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.admin_log_id_seq OWNER TO tragene_user;

--
-- Name: admin_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tragene_user
--

ALTER SEQUENCE public.admin_log_id_seq OWNED BY public.admin_log.id;


--
-- Name: challenge_purchase; Type: TABLE; Schema: public; Owner: tragene_user
--

CREATE TABLE public.challenge_purchase (
    id integer NOT NULL,
    user_id integer NOT NULL,
    challenge_template_id integer NOT NULL,
    purchase_date timestamp with time zone,
    amount double precision NOT NULL,
    payment_method character varying(50),
    mt5_server character varying(200),
    mt5_login character varying(100),
    mt5_password character varying(200),
    credentials_assigned_at timestamp with time zone,
    credentials_revoked_at timestamp with time zone,
    serial_no integer,
    challenge_code character varying(6),
    challenge_token character varying(100),
    ea_connected boolean,
    ea_first_connection timestamp with time zone,
    last_heartbeat timestamp with time zone,
    start_date timestamp with time zone,
    end_date timestamp with time zone,
    current_profit double precision,
    current_loss double precision,
    max_drawdown_used double precision,
    starting_balance double precision,
    starting_equity double precision,
    current_balance double precision,
    current_equity double precision,
    peak_equity double precision,
    daily_start_equity double precision,
    daily_start_date date,
    last_verified_balance double precision,
    last_verified_equity double precision,
    last_balance_check_time timestamp with time zone,
    balance_check_hash character varying(64),
    status character varying(20),
    phase integer,
    violation_reason text,
    violation_timestamp timestamp with time zone,
    pass_reason text,
    progress_percentage double precision,
    days_remaining integer,
    trading_days_completed integer,
    mt5_account character varying(100),
    account_balance double precision,
    equity double precision,
    last_updated timestamp with time zone,
    completed_at timestamp with time zone
);


ALTER TABLE public.challenge_purchase OWNER TO tragene_user;

--
-- Name: challenge_purchase_id_seq; Type: SEQUENCE; Schema: public; Owner: tragene_user
--

CREATE SEQUENCE public.challenge_purchase_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.challenge_purchase_id_seq OWNER TO tragene_user;

--
-- Name: challenge_purchase_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tragene_user
--

ALTER SEQUENCE public.challenge_purchase_id_seq OWNED BY public.challenge_purchase.id;


--
-- Name: challenge_template; Type: TABLE; Schema: public; Owner: tragene_user
--

CREATE TABLE public.challenge_template (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    price integer NOT NULL,
    account_size integer NOT NULL,
    phase integer NOT NULL,
    profit_target double precision NOT NULL,
    max_daily_loss double precision NOT NULL,
    max_overall_loss double precision NOT NULL,
    min_trading_days integer NOT NULL,
    duration_days integer NOT NULL,
    leverage character varying(20),
    user_profit_share integer NOT NULL,
    payout_cycle character varying(20),
    weekend_trading boolean,
    is_active boolean,
    description text,
    created_at timestamp with time zone,
    updated_at timestamp with time zone
);


ALTER TABLE public.challenge_template OWNER TO tragene_user;

--
-- Name: challenge_template_id_seq; Type: SEQUENCE; Schema: public; Owner: tragene_user
--

CREATE SEQUENCE public.challenge_template_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.challenge_template_id_seq OWNER TO tragene_user;

--
-- Name: challenge_template_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tragene_user
--

ALTER SEQUENCE public.challenge_template_id_seq OWNED BY public.challenge_template.id;


--
-- Name: daily_snapshot; Type: TABLE; Schema: public; Owner: tragene_user
--

CREATE TABLE public.daily_snapshot (
    id integer NOT NULL,
    challenge_purchase_id integer NOT NULL,
    snapshot_date date NOT NULL,
    start_equity double precision NOT NULL,
    end_equity double precision NOT NULL,
    start_balance double precision NOT NULL,
    end_balance double precision NOT NULL,
    lowest_equity double precision,
    highest_equity double precision,
    trades_opened integer,
    trades_closed integer,
    closed_profit double precision,
    closed_loss double precision,
    net_pnl double precision,
    is_trading_day boolean,
    violated_daily_dd boolean,
    had_manual_trades boolean,
    created_at timestamp with time zone
);


ALTER TABLE public.daily_snapshot OWNER TO tragene_user;

--
-- Name: daily_snapshot_id_seq; Type: SEQUENCE; Schema: public; Owner: tragene_user
--

CREATE SEQUENCE public.daily_snapshot_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.daily_snapshot_id_seq OWNER TO tragene_user;

--
-- Name: daily_snapshot_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tragene_user
--

ALTER SEQUENCE public.daily_snapshot_id_seq OWNED BY public.daily_snapshot.id;


--
-- Name: ea_trade; Type: TABLE; Schema: public; Owner: tragene_user
--

CREATE TABLE public.ea_trade (
    id integer NOT NULL,
    challenge_purchase_id integer NOT NULL,
    ticket bigint NOT NULL,
    symbol character varying(20) NOT NULL,
    trade_type integer NOT NULL,
    lots double precision NOT NULL,
    open_price double precision,
    close_price double precision,
    current_price double precision,
    profit double precision,
    floating_pnl double precision,
    sl double precision,
    tp double precision,
    magic bigint,
    open_time timestamp with time zone,
    close_time timestamp with time zone,
    status character varying(20),
    created_at timestamp with time zone,
    updated_at timestamp with time zone,
    is_archived boolean
);


ALTER TABLE public.ea_trade OWNER TO tragene_user;

--
-- Name: ea_trade_id_seq; Type: SEQUENCE; Schema: public; Owner: tragene_user
--

CREATE SEQUENCE public.ea_trade_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.ea_trade_id_seq OWNER TO tragene_user;

--
-- Name: ea_trade_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tragene_user
--

ALTER SEQUENCE public.ea_trade_id_seq OWNED BY public.ea_trade.id;


--
-- Name: faq; Type: TABLE; Schema: public; Owner: tragene_user
--

CREATE TABLE public.faq (
    id integer NOT NULL,
    question character varying(500) NOT NULL,
    answer text NOT NULL,
    category character varying(100),
    is_pinned boolean,
    helpful_yes integer,
    helpful_no integer,
    created_at timestamp with time zone,
    updated_at timestamp with time zone
);


ALTER TABLE public.faq OWNER TO tragene_user;

--
-- Name: faq_id_seq; Type: SEQUENCE; Schema: public; Owner: tragene_user
--

CREATE SEQUENCE public.faq_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.faq_id_seq OWNER TO tragene_user;

--
-- Name: faq_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tragene_user
--

ALTER SEQUENCE public.faq_id_seq OWNED BY public.faq.id;


--
-- Name: notification; Type: TABLE; Schema: public; Owner: tragene_user
--

CREATE TABLE public.notification (
    id integer NOT NULL,
    user_id integer NOT NULL,
    title character varying(200) NOT NULL,
    message text NOT NULL,
    notification_type character varying(50),
    is_read boolean,
    action_url character varying(500),
    icon character varying(50),
    created_at timestamp with time zone,
    read_at timestamp with time zone
);


ALTER TABLE public.notification OWNER TO tragene_user;

--
-- Name: notification_id_seq; Type: SEQUENCE; Schema: public; Owner: tragene_user
--

CREATE SEQUENCE public.notification_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.notification_id_seq OWNER TO tragene_user;

--
-- Name: notification_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tragene_user
--

ALTER SEQUENCE public.notification_id_seq OWNED BY public.notification.id;


--
-- Name: payment; Type: TABLE; Schema: public; Owner: tragene_user
--

CREATE TABLE public.payment (
    id integer NOT NULL,
    user_id integer NOT NULL,
    challenge_purchase_id integer,
    payment_id character varying(100) NOT NULL,
    amount double precision NOT NULL,
    currency character varying(10),
    payment_method character varying(20) NOT NULL,
    gateway character varying(50),
    status character varying(20),
    gateway_id character varying(100),
    gateway_order_id character varying(100),
    gateway_response text,
    notes text,
    ip_address character varying(50),
    user_agent text,
    created_at timestamp with time zone,
    updated_at timestamp with time zone,
    expected_amount double precision DEFAULT 0.0,
    challenge_template_id integer
);


ALTER TABLE public.payment OWNER TO tragene_user;

--
-- Name: payment_id_seq; Type: SEQUENCE; Schema: public; Owner: tragene_user
--

CREATE SEQUENCE public.payment_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payment_id_seq OWNER TO tragene_user;

--
-- Name: payment_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tragene_user
--

ALTER SEQUENCE public.payment_id_seq OWNED BY public.payment.id;


--
-- Name: payout; Type: TABLE; Schema: public; Owner: tragene_user
--

CREATE TABLE public.payout (
    id integer NOT NULL,
    user_id integer NOT NULL,
    challenge_purchase_id integer NOT NULL,
    amount double precision NOT NULL,
    profit_share_percentage double precision NOT NULL,
    status character varying(20),
    admin_notes text,
    payout_date timestamp with time zone,
    due_date timestamp with time zone,
    payment_method character varying(50),
    transaction_id character varying(100),
    bank_account_details text,
    created_at timestamp with time zone,
    updated_at timestamp with time zone
);


ALTER TABLE public.payout OWNER TO tragene_user;

--
-- Name: payout_id_seq; Type: SEQUENCE; Schema: public; Owner: tragene_user
--

CREATE SEQUENCE public.payout_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.payout_id_seq OWNER TO tragene_user;

--
-- Name: payout_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tragene_user
--

ALTER SEQUENCE public.payout_id_seq OWNED BY public.payout.id;


--
-- Name: rule_violation; Type: TABLE; Schema: public; Owner: tragene_user
--

CREATE TABLE public.rule_violation (
    id integer NOT NULL,
    challenge_purchase_id integer NOT NULL,
    rule_name character varying(100) NOT NULL,
    rule_value_limit double precision,
    rule_value_actual double precision,
    violation_message text NOT NULL,
    snapshot_id integer,
    severity character varying(20),
    is_hard_fail boolean,
    action_taken character varying(50),
    violated_at timestamp with time zone
);


ALTER TABLE public.rule_violation OWNER TO tragene_user;

--
-- Name: rule_violation_id_seq; Type: SEQUENCE; Schema: public; Owner: tragene_user
--

CREATE SEQUENCE public.rule_violation_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.rule_violation_id_seq OWNER TO tragene_user;

--
-- Name: rule_violation_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tragene_user
--

ALTER SEQUENCE public.rule_violation_id_seq OWNED BY public.rule_violation.id;


--
-- Name: support_ticket; Type: TABLE; Schema: public; Owner: tragene_user
--

CREATE TABLE public.support_ticket (
    id integer NOT NULL,
    user_id integer NOT NULL,
    subject character varying(200) NOT NULL,
    message text,
    status character varying(20),
    priority character varying(20),
    assigned_to integer,
    resolution text,
    created_at timestamp with time zone,
    updated_at timestamp with time zone,
    resolved_at timestamp with time zone,
    ticket_number character varying(50),
    category character varying(50) DEFAULT 'General'::character varying,
    admin_note text,
    is_deleted boolean DEFAULT false,
    last_reply_at timestamp without time zone,
    last_user_read_at timestamp without time zone,
    last_admin_read_at timestamp without time zone,
    attachment character varying(255),
    closed_by integer
);


ALTER TABLE public.support_ticket OWNER TO tragene_user;

--
-- Name: support_ticket_id_seq; Type: SEQUENCE; Schema: public; Owner: tragene_user
--

CREATE SEQUENCE public.support_ticket_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.support_ticket_id_seq OWNER TO tragene_user;

--
-- Name: support_ticket_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tragene_user
--

ALTER SEQUENCE public.support_ticket_id_seq OWNED BY public.support_ticket.id;


--
-- Name: ticket_message; Type: TABLE; Schema: public; Owner: tragene_user
--

CREATE TABLE public.ticket_message (
    id integer NOT NULL,
    ticket_id integer NOT NULL,
    sender_id integer NOT NULL,
    message text NOT NULL,
    is_admin_reply boolean,
    attachment_url character varying(500),
    created_at timestamp with time zone
);


ALTER TABLE public.ticket_message OWNER TO tragene_user;

--
-- Name: ticket_message_id_seq; Type: SEQUENCE; Schema: public; Owner: tragene_user
--

CREATE SEQUENCE public.ticket_message_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.ticket_message_id_seq OWNER TO tragene_user;

--
-- Name: ticket_message_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tragene_user
--

ALTER SEQUENCE public.ticket_message_id_seq OWNED BY public.ticket_message.id;


--
-- Name: trade; Type: TABLE; Schema: public; Owner: tragene_user
--

CREATE TABLE public.trade (
    id integer NOT NULL,
    challenge_purchase_id integer NOT NULL,
    trade_id character varying(100),
    symbol character varying(20) NOT NULL,
    trade_type character varying(10) NOT NULL,
    volume double precision NOT NULL,
    open_price double precision NOT NULL,
    close_price double precision,
    open_time timestamp with time zone NOT NULL,
    close_time timestamp with time zone,
    swap double precision,
    commission double precision,
    profit double precision,
    status character varying(20),
    notes text,
    created_at timestamp with time zone,
    updated_at timestamp with time zone
);


ALTER TABLE public.trade OWNER TO tragene_user;

--
-- Name: trade_id_seq; Type: SEQUENCE; Schema: public; Owner: tragene_user
--

CREATE SEQUENCE public.trade_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.trade_id_seq OWNER TO tragene_user;

--
-- Name: trade_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tragene_user
--

ALTER SEQUENCE public.trade_id_seq OWNED BY public.trade.id;


--
-- Name: user; Type: TABLE; Schema: public; Owner: tragene_user
--

CREATE TABLE public."user" (
    id integer NOT NULL,
    first_name character varying(50) NOT NULL,
    last_name character varying(50) NOT NULL,
    email character varying(100) NOT NULL,
    phone character varying(20) NOT NULL,
    dob date NOT NULL,
    country character varying(50) NOT NULL,
    state character varying(50),
    password character varying(200) NOT NULL,
    is_admin boolean,
    is_banned boolean,
    created_at timestamp with time zone,
    phone_verified boolean,
    email_verified boolean,
    kyc_status character varying(20),
    id_front_url character varying(500),
    id_back_url character varying(500),
    document_type character varying(20),
    document_number character varying(50),
    kyc_submitted_at timestamp with time zone,
    kyc_notes text,
    email_verification_token character varying(100),
    phone_verification_code character varying(6),
    phone_verification_sent_at double precision,
    phone_verification_attempts integer,
    last_balance_check timestamp with time zone,
    balance_check_hash character varying(64),
    trading_alias character varying(100),
    trader_level character varying(50) DEFAULT 'Beginner'::character varying,
    is_compact_view boolean DEFAULT false
);


ALTER TABLE public."user" OWNER TO tragene_user;

--
-- Name: user_id_seq; Type: SEQUENCE; Schema: public; Owner: tragene_user
--

CREATE SEQUENCE public.user_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.user_id_seq OWNER TO tragene_user;

--
-- Name: user_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tragene_user
--

ALTER SEQUENCE public.user_id_seq OWNED BY public."user".id;


--
-- Name: waitlist_leads; Type: TABLE; Schema: public; Owner: tragene_user
--

CREATE TABLE public.waitlist_leads (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    email character varying(100) NOT NULL,
    phone character varying(20) NOT NULL,
    experience character varying(50),
    platform character varying(50),
    plan_interest character varying(100),
    problem text,
    feedback text,
    early_access boolean,
    status character varying(20),
    created_at timestamp with time zone
);


ALTER TABLE public.waitlist_leads OWNER TO tragene_user;

--
-- Name: waitlist_leads_id_seq; Type: SEQUENCE; Schema: public; Owner: tragene_user
--

CREATE SEQUENCE public.waitlist_leads_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.waitlist_leads_id_seq OWNER TO tragene_user;

--
-- Name: waitlist_leads_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tragene_user
--

ALTER SEQUENCE public.waitlist_leads_id_seq OWNED BY public.waitlist_leads.id;


--
-- Name: webhook_log; Type: TABLE; Schema: public; Owner: tragene_user
--

CREATE TABLE public.webhook_log (
    id integer NOT NULL,
    event_type character varying(100),
    order_id character varying(100),
    raw_payload text NOT NULL,
    headers text,
    signature character varying(500),
    status character varying(50),
    error_message text,
    created_at timestamp with time zone,
    processed_at timestamp with time zone
);


ALTER TABLE public.webhook_log OWNER TO tragene_user;

--
-- Name: webhook_log_id_seq; Type: SEQUENCE; Schema: public; Owner: tragene_user
--

CREATE SEQUENCE public.webhook_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.webhook_log_id_seq OWNER TO tragene_user;

--
-- Name: webhook_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: tragene_user
--

ALTER SEQUENCE public.webhook_log_id_seq OWNED BY public.webhook_log.id;


--
-- Name: account_snapshot id; Type: DEFAULT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.account_snapshot ALTER COLUMN id SET DEFAULT nextval('public.account_snapshot_id_seq'::regclass);


--
-- Name: admin_log id; Type: DEFAULT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.admin_log ALTER COLUMN id SET DEFAULT nextval('public.admin_log_id_seq'::regclass);


--
-- Name: challenge_purchase id; Type: DEFAULT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.challenge_purchase ALTER COLUMN id SET DEFAULT nextval('public.challenge_purchase_id_seq'::regclass);


--
-- Name: challenge_template id; Type: DEFAULT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.challenge_template ALTER COLUMN id SET DEFAULT nextval('public.challenge_template_id_seq'::regclass);


--
-- Name: daily_snapshot id; Type: DEFAULT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.daily_snapshot ALTER COLUMN id SET DEFAULT nextval('public.daily_snapshot_id_seq'::regclass);


--
-- Name: ea_trade id; Type: DEFAULT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.ea_trade ALTER COLUMN id SET DEFAULT nextval('public.ea_trade_id_seq'::regclass);


--
-- Name: faq id; Type: DEFAULT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.faq ALTER COLUMN id SET DEFAULT nextval('public.faq_id_seq'::regclass);


--
-- Name: notification id; Type: DEFAULT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.notification ALTER COLUMN id SET DEFAULT nextval('public.notification_id_seq'::regclass);


--
-- Name: payment id; Type: DEFAULT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.payment ALTER COLUMN id SET DEFAULT nextval('public.payment_id_seq'::regclass);


--
-- Name: payout id; Type: DEFAULT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.payout ALTER COLUMN id SET DEFAULT nextval('public.payout_id_seq'::regclass);


--
-- Name: rule_violation id; Type: DEFAULT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.rule_violation ALTER COLUMN id SET DEFAULT nextval('public.rule_violation_id_seq'::regclass);


--
-- Name: support_ticket id; Type: DEFAULT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.support_ticket ALTER COLUMN id SET DEFAULT nextval('public.support_ticket_id_seq'::regclass);


--
-- Name: ticket_message id; Type: DEFAULT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.ticket_message ALTER COLUMN id SET DEFAULT nextval('public.ticket_message_id_seq'::regclass);


--
-- Name: trade id; Type: DEFAULT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.trade ALTER COLUMN id SET DEFAULT nextval('public.trade_id_seq'::regclass);


--
-- Name: user id; Type: DEFAULT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public."user" ALTER COLUMN id SET DEFAULT nextval('public.user_id_seq'::regclass);


--
-- Name: waitlist_leads id; Type: DEFAULT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.waitlist_leads ALTER COLUMN id SET DEFAULT nextval('public.waitlist_leads_id_seq'::regclass);


--
-- Name: webhook_log id; Type: DEFAULT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.webhook_log ALTER COLUMN id SET DEFAULT nextval('public.webhook_log_id_seq'::regclass);


--
-- Data for Name: account_snapshot; Type: TABLE DATA; Schema: public; Owner: tragene_user
--

COPY public.account_snapshot (id, challenge_purchase_id, "timestamp", ea_version, terminal_build, mt5_login, broker_server, balance, equity, free_margin, margin_used, credit, leverage, currency, profit_from_start, drawdown_from_peak, open_positions_count, is_archived, archived_at) FROM stdin;
\.


--
-- Data for Name: admin_log; Type: TABLE DATA; Schema: public; Owner: tragene_user
--

COPY public.admin_log (id, admin_id, action, target_type, target_id, details, ip_address, created_at) FROM stdin;
\.


--
-- Data for Name: challenge_purchase; Type: TABLE DATA; Schema: public; Owner: tragene_user
--

COPY public.challenge_purchase (id, user_id, challenge_template_id, purchase_date, amount, payment_method, mt5_server, mt5_login, mt5_password, credentials_assigned_at, credentials_revoked_at, serial_no, challenge_code, challenge_token, ea_connected, ea_first_connection, last_heartbeat, start_date, end_date, current_profit, current_loss, max_drawdown_used, starting_balance, starting_equity, current_balance, current_equity, peak_equity, daily_start_equity, daily_start_date, last_verified_balance, last_verified_equity, last_balance_check_time, balance_check_hash, status, phase, violation_reason, violation_timestamp, pass_reason, progress_percentage, days_remaining, trading_days_completed, mt5_account, account_balance, equity, last_updated, completed_at) FROM stdin;
1	4	7	2026-05-15 11:02:53.531047+00	5	cashfree	\N	\N	\N	\N	\N	1111	984792	52642236db867d9f72ca07f8c9edbe62cc5acf0a23fe56214d5a45080e8e0637	f	\N	\N	2026-05-15 11:02:53.531052+00	2026-06-14 11:02:53.531052+00	0	0	0	0	0	0	0	0	0	\N	0	0	\N		active	1	\N	\N	\N	0	30	0	TRG_4_7_20260515	0	0	2026-05-15 11:02:53.69693+00	\N
2	4	7	2026-05-15 11:02:53.975324+00	5	cashfree	\N	\N	\N	\N	\N	1112	110771	d6c7221521c2910cbb35edccb36d50d3e68bf21f32ed83472e786594a9c84800	f	\N	\N	2026-05-15 11:02:53.975328+00	2026-06-14 11:02:53.975328+00	0	0	0	0	0	0	0	0	0	\N	0	0	\N		active	1	\N	\N	\N	0	30	0	TRG_4_7_20260515	0	0	2026-05-15 11:02:53.983151+00	\N
5	4	7	2026-05-15 13:20:27.915992+00	5	cashfree	\N	\N	\N	\N	\N	1115	821110	ebf59c96d15316684fb05e5c9130edac25013d82d648111ee73684fbe7f082e5	f	\N	\N	2026-05-15 13:20:27.915998+00	2026-06-14 13:20:27.915998+00	0	0	0	0	0	0	0	0	0	\N	0	0	\N		active	1	\N	\N	\N	0	30	0	TRG_4_7_20260515	0	0	2026-05-15 13:20:27.926811+00	\N
4	4	7	2026-05-15 11:24:29.062208+00	5	cashfree	\N	\N	\N	\N	\N	1114	195128	de73e4b0fa1bb723e1c8118c67288d362a746cc3441a3370ab9ec6d1684ffe75	f	\N	\N	2026-05-15 11:24:29.062213+00	2026-06-14 11:24:29.062213+00	0	0	0	0	0	0	0	0	0	\N	0	0	\N		failed	1	\N	\N	\N	0	30	0	TRG_4_7_20260515	0	0	2026-05-15 11:24:29.065655+00	\N
6	4	7	2026-05-16 10:50:10.585263+00	1	cashfree	\N	\N	\N	\N	\N	1116	361937	dd68829f14a6bdc3e1b33ec294f0805354546f97cecb59aa055a369d84c9f875	f	\N	\N	2026-05-16 10:50:10.585266+00	2026-06-15 10:50:10.585267+00	0	0	0	0	0	0	0	0	0	\N	0	0	\N		active	1	\N	\N	\N	0	30	0	TRG_4_7_20260516	0	0	2026-05-16 10:50:10.592678+00	\N
3	4	7	2026-05-15 11:24:28.634112+00	5	cashfree	\N	\N	\N	\N	\N	1113	886774	eb3411da41f2d16c8e16f6e4a22abdc85c0f04baee61b40896f0f6c17d7702f3	f	\N	\N	2026-05-15 11:24:28.634116+00	2026-06-14 11:24:28.634117+00	0	0	0	0	0	0	0	0	0	\N	0	0	\N		active	1	\N	\N	\N	0	30	0	TRG_4_7_20260515	0	0	2026-05-15 11:24:28.641839+00	\N
\.


--
-- Data for Name: challenge_template; Type: TABLE DATA; Schema: public; Owner: tragene_user
--

COPY public.challenge_template (id, name, price, account_size, phase, profit_target, max_daily_loss, max_overall_loss, min_trading_days, duration_days, leverage, user_profit_share, payout_cycle, weekend_trading, is_active, description, created_at, updated_at) FROM stdin;
4	professional	399	400	1	12	5	8	4	30	1:100	80	weekly	f	t		2026-05-15 10:31:25.330119+00	2026-05-15 10:31:25.330123+00
5	advance	499	500	1	12	5	8	4	30	1:100	80	weekly	f	t		2026-05-15 10:31:53.475857+00	2026-05-15 10:31:53.475861+00
7	testing	1	0	1	12	5	8	4	30	1:100	70	weekly	f	f		2026-05-15 11:01:53.402714+00	2026-05-17 03:52:37.866369+00
3	Pro Challenge	199	200	1	12	5	8	4	30	1:100	70	biweekly	t	t	Pro challenge	2026-05-06 09:57:14.402254+00	2026-05-17 03:54:09.27341+00
\.


--
-- Data for Name: daily_snapshot; Type: TABLE DATA; Schema: public; Owner: tragene_user
--

COPY public.daily_snapshot (id, challenge_purchase_id, snapshot_date, start_equity, end_equity, start_balance, end_balance, lowest_equity, highest_equity, trades_opened, trades_closed, closed_profit, closed_loss, net_pnl, is_trading_day, violated_daily_dd, had_manual_trades, created_at) FROM stdin;
\.


--
-- Data for Name: ea_trade; Type: TABLE DATA; Schema: public; Owner: tragene_user
--

COPY public.ea_trade (id, challenge_purchase_id, ticket, symbol, trade_type, lots, open_price, close_price, current_price, profit, floating_pnl, sl, tp, magic, open_time, close_time, status, created_at, updated_at, is_archived) FROM stdin;
\.


--
-- Data for Name: faq; Type: TABLE DATA; Schema: public; Owner: tragene_user
--

COPY public.faq (id, question, answer, category, is_pinned, helpful_yes, helpful_no, created_at, updated_at) FROM stdin;
1	What is Tragene Funded?	Tragene Funded is a trading challenge platform where traders can participate in evaluation programs and qualify for funded opportunities.	General	t	0	0	2026-05-15 09:51:54.330824+00	2026-05-15 09:51:54.330829+00
2	How do challenge purchases work?	Select a challenge, complete payment, and your account will be activated automatically.	Challenges	f	0	0	2026-05-15 09:51:54.333366+00	2026-05-15 09:51:54.33337+00
3	What payment methods are available?	Payments are processed securely through Cashfree.	Payments	f	0	0	2026-05-15 09:51:54.333371+00	2026-05-15 09:51:54.333372+00
4	How long does KYC take?	KYC verification usually takes 24–48 hours.	KYC	f	0	0	2026-05-15 09:51:54.333373+00	2026-05-15 09:51:54.333373+00
5	How do I contact support?	Use the Help Center ticket system or contact support@tragenefunded.com	Support	f	0	0	2026-05-15 09:51:54.333374+00	2026-05-15 09:51:54.333375+00
6	How do I get started?	Create an account, complete your profile and KYC if required, choose a challenge, and purchase it from the Challenges page.	General	f	0	0	2026-05-15 10:11:10.353802+00	2026-05-15 10:11:10.353807+00
7	Do I need prior trading experience?	No. Beginners and experienced traders can participate, but understanding risk management is strongly recommended.	General	f	0	0	2026-05-15 10:11:10.355601+00	2026-05-15 10:11:10.355604+00
8	Can I create multiple accounts?	Creating multiple accounts for abuse, rule evasion, or exploiting platform systems may lead to restrictions.	General	f	0	0	2026-05-15 10:11:10.35689+00	2026-05-15 10:11:10.356893+00
9	Is Tragene Funded available internationally?	Availability may depend on compliance, supported payment methods, and future platform policies.	General	f	0	0	2026-05-15 10:11:10.3581+00	2026-05-15 10:11:10.358103+00
10	How do I buy a challenge?	Go to the Challenges section, select your preferred challenge, and complete payment securely.	Challenge & Trading	f	0	0	2026-05-15 10:11:10.359289+00	2026-05-15 10:11:10.359292+00
11	What challenge sizes are available?	Challenge options and account sizes are displayed directly on the challenge page.	Challenge & Trading	f	0	0	2026-05-15 10:11:10.360558+00	2026-05-15 10:11:10.36056+00
12	What happens after successful payment?	Your challenge should appear in your dashboard after successful processing.	Challenge & Trading	f	0	0	2026-05-15 10:11:10.361749+00	2026-05-15 10:11:10.361751+00
13	I paid but did not receive my challenge. What should I do?	Contact support through the Help Center. If payment succeeded but delivery failed, we will investigate and assist.	Challenge & Trading	f	0	0	2026-05-15 10:11:10.362921+00	2026-05-15 10:11:10.362924+00
14	Can I retry a failed challenge?	Retry policies may vary by challenge type and promotional offers.	Challenge & Trading	f	0	0	2026-05-15 10:11:10.364112+00	2026-05-15 10:11:10.364115+00
15	What happens if I violate challenge rules?	Rule violations may result in challenge failure or restrictions according to platform rules.	Challenge & Trading	f	0	0	2026-05-15 10:11:10.365291+00	2026-05-15 10:11:10.365294+00
16	Where can I see challenge rules?	Rules are displayed on challenge pages and within your dashboard.	Challenge & Trading	f	0	0	2026-05-15 10:11:10.366495+00	2026-05-15 10:11:10.366497+00
17	Can challenge rules change?	Platform rules and policies may be updated to improve fairness and platform operations.	Challenge & Trading	f	0	0	2026-05-15 10:11:10.367678+00	2026-05-15 10:11:10.367681+00
18	Which payment methods are supported?	Supported methods may include UPI, debit cards, credit cards, net banking, and other available payment options.	Payments	f	0	0	2026-05-15 10:11:10.368919+00	2026-05-15 10:11:10.368922+00
19	Are payments secure?	Yes. Payments are processed through secure payment gateway systems.	Payments	f	0	0	2026-05-15 10:11:10.37011+00	2026-05-15 10:11:10.370112+00
20	Why was my payment marked failed?	This can happen due to banking issues, payment interruptions, network failures, or gateway issues.	Payments	f	0	0	2026-05-15 10:11:10.371291+00	2026-05-15 10:11:10.371294+00
21	I was charged twice. What should I do?	Open a support ticket immediately. Duplicate payments may be reviewed and handled accordingly.	Payments	f	0	0	2026-05-15 10:11:10.372622+00	2026-05-15 10:11:10.372624+00
22	Why is my payment pending?	Some payment methods require extra processing time before final confirmation.	Payments	f	0	0	2026-05-15 10:11:10.373808+00	2026-05-15 10:11:10.373811+00
23	Can I cancel a payment after completion?	Completed transactions generally cannot be cancelled after successful processing.	Payments	f	0	0	2026-05-15 10:11:10.374975+00	2026-05-15 10:11:10.374977+00
24	Are challenge purchases refundable?	Challenge purchases are generally non-refundable except in specific eligible situations.	Refunds	f	0	0	2026-05-15 10:11:10.376183+00	2026-05-15 10:11:10.376185+00
25	When can a refund request be reviewed?	Refund requests may be reviewed for duplicate payments, technical failures, or service delivery issues.	Refunds	f	0	0	2026-05-15 10:11:10.377361+00	2026-05-15 10:11:10.377364+00
26	I paid but received no challenge. Can I get a refund?	We may provide challenge delivery or review the issue according to platform policies.	Refunds	f	0	0	2026-05-15 10:11:10.378573+00	2026-05-15 10:11:10.378575+00
27	How long do refund investigations take?	Review times vary depending on payment verification and investigation requirements.	Refunds	f	0	0	2026-05-15 10:11:10.379751+00	2026-05-15 10:11:10.379753+00
28	Will failed trading performance qualify for refunds?	No. Trading outcomes or challenge performance do not qualify for refunds.	Refunds	f	0	0	2026-05-15 10:11:10.380979+00	2026-05-15 10:11:10.380982+00
29	Can suspicious activity affect refunds?	Yes. Suspicious activity or fraud indicators may lead to investigation before processing.	Refunds	f	0	0	2026-05-15 10:11:10.382184+00	2026-05-15 10:11:10.382187+00
30	Why do I need KYC?	KYC helps maintain security and platform integrity.	KYC & Account	f	0	0	2026-05-15 10:11:10.383335+00	2026-05-15 10:11:10.383338+00
31	How long does KYC verification take?	Verification generally takes between 24–48 business hours.	KYC & Account	f	0	0	2026-05-15 10:11:10.384566+00	2026-05-15 10:11:10.384568+00
32	Which documents are accepted?	Accepted documents are listed on the KYC page.	KYC & Account	f	0	0	2026-05-15 10:11:10.385784+00	2026-05-15 10:11:10.385787+00
33	Why was my KYC rejected?	Common reasons include unclear images, incorrect information, or unsupported documents.	KYC & Account	f	0	0	2026-05-15 10:11:10.386969+00	2026-05-15 10:11:10.386972+00
34	Can I resubmit KYC?	Yes. Users can usually resubmit corrected information.	KYC & Account	f	0	0	2026-05-15 10:11:10.388173+00	2026-05-15 10:11:10.388176+00
35	Can I email support directly?	support@tragenefunded.com or tragene.co@gmail.com	Support	f	0	0	2026-05-15 10:11:10.389969+00	2026-05-15 10:11:10.389972+00
36	What is the fastest way to get help?	The Help Center ticket system is generally the fastest support channel.	Support	f	0	0	2026-05-15 10:11:10.391137+00	2026-05-15 10:11:10.391139+00
37	Can I track my support request?	Yes. Ticket status and conversations can be viewed from your dashboard.	Support	f	0	0	2026-05-15 10:11:10.392348+00	2026-05-15 10:11:10.392351+00
38	What if I cannot find my answer here?	Create a support ticket and our team will review your issue.	Support	f	0	0	2026-05-15 10:11:10.393409+00	2026-05-15 10:11:10.393411+00
\.


--
-- Data for Name: notification; Type: TABLE DATA; Schema: public; Owner: tragene_user
--

COPY public.notification (id, user_id, title, message, notification_type, is_read, action_url, icon, created_at, read_at) FROM stdin;
\.


--
-- Data for Name: payment; Type: TABLE DATA; Schema: public; Owner: tragene_user
--

COPY public.payment (id, user_id, challenge_purchase_id, payment_id, amount, currency, payment_method, gateway, status, gateway_id, gateway_order_id, gateway_response, notes, ip_address, user_agent, created_at, updated_at, expected_amount, challenge_template_id) FROM stdin;
1	4	\N	ORDER_4_1778830458_bcb71c03	149	INR	cashfree	cashfree	pending		\N	{"payment_session_id": "session_2ierLyI0-Y9RPpMa6gNw30DSayomIzVIwla4ZfHNlMYll3dUapKFD4tz77-fN4hqxhb-bSPLJI8yY5v1V8j0Sygqx46Q73Q8bW1_7jibNrYrCTaSlLI4zOl3VYhz"}	\N	\N	\N	2026-05-15 07:34:18.872815+00	2026-05-15 07:34:18.87282+00	149	2
2	4	\N	ORDER_4_1778838224_fe355776	199	INR	cashfree	cashfree	pending		\N	{"payment_session_id": "session_eFJroW50dWsH8D5pmROEmL2olfeKkPI2FZ5ET2QEPB4KPJ8XQBjfJ3XjUdeP5J39VrvKW6FABqYJXfllI-c0KckPxD3tYfk6PBXfZKH6ErQ7PGDEBERW8RF4PS0F"}	\N	\N	\N	2026-05-15 09:43:44.785641+00	2026-05-15 09:43:44.785646+00	199	3
3	5	\N	ORDER_5_1778840843_221b6921	199	INR	cashfree	cashfree	pending		\N	{"payment_session_id": "session_6bNDByfrKoe2R-Z5koxleFQZ9kN2N9SYP_NbPQ1BSIV4rsiptVX-q1ukPc2wANPf5bzjz2NE6lnD4zVNzF_v66jCRjb3vPc7oJrAi-iM4xYNFDKebOXD_QCccQhP"}	\N	\N	\N	2026-05-15 10:27:24.436791+00	2026-05-15 10:27:24.436796+00	199	3
4	5	\N	ORDER_5_1778841151_e8340687	399	INR	cashfree	cashfree	pending		\N	{"payment_session_id": "session_9IsrcIkbVyTd-UoHHwJSt-c-7Dlg6vWtUYICIa7K9jJBcp6WJfvswQs8ObCm_eBSaTROKniGrwI3ILYgenjmnoPXbz2lEzadyS1kCfYBvQrbvmGjy_1CikUqNatj"}	\N	\N	\N	2026-05-15 10:32:32.528865+00	2026-05-15 10:32:32.528871+00	399	4
5	5	\N	ORDER_5_1778841204_58a2c8eb	199	INR	cashfree	cashfree	pending		\N	{"payment_session_id": "session_iOb3wlOoyuraW--MP2iYdfgHM-OlumCyrh1hvlSvdJLQktNpEjb-_-0Sc_cXNnAlw3N4OMKkLRLV4r-Qjxsk74WDLzNYm6ZYtiaVe4YV7JsPRvOGEXS1E6fC-olu"}	\N	\N	\N	2026-05-15 10:33:24.888108+00	2026-05-15 10:33:24.888112+00	199	3
6	5	\N	ORDER_5_1778841223_a4e0c769	399	INR	cashfree	cashfree	pending		\N	{"payment_session_id": "session_jiwvCKuOcso2xGzrb-mpnvqavLKRVWRQhJ81H2OhNrHHoEPbUUo1-MCJNDWDHRwukL_mH3rDjBSnVDO-d42N1mhJKcQEflikelz1IaDVEqxI1c6sIZf6pyvOVJuj"}	\N	\N	\N	2026-05-15 10:33:44.248342+00	2026-05-15 10:33:44.248347+00	399	4
7	5	\N	ORDER_5_1778841285_c1ee84ae	199	INR	cashfree	cashfree	pending		\N	{"payment_session_id": "session_Ptg4UYZNYIxyQUdVG48thhe5hooU_gY3R6HWemK6l4S9Blw-2Q5WLr_HiCAmrrJF_SWpXHJS9b6LBf-IZfysrqBNjcdOB95hqFI0Tur9vOQBHEXZ9qeWKwT86zYI"}	\N	\N	\N	2026-05-15 10:34:45.420973+00	2026-05-15 10:34:45.420977+00	199	3
8	4	2	ORDER_4_1778842931_d9e5c67c	5	INR	cashfree	cashfree	success	5584846019	\N	{"data": {"order": {"order_id": "ORDER_4_1778842931_d9e5c67c", "order_amount": 5.0, "order_currency": "INR", "order_tags": null}, "payment": {"cf_payment_id": "5584846019", "payment_status": "SUCCESS", "payment_amount": 5.0, "payment_currency": "INR", "payment_message": "00::Transaction Success", "payment_time": "2026-05-15T16:32:34+05:30", "bank_reference": "125526494410", "auth_id": null, "payment_method": {"upi": {"channel": "qrcode", "upi_id": "9067326513@axl"}}, "payment_group": "upi"}, "customer_details": {"customer_name": "jay sharma", "customer_id": "USER_4", "customer_email": "kunaldhade40@gmail.com", "customer_phone": "8888888888"}, "payment_gateway_details": {"gateway_name": "CASHFREE", "gateway_order_id": null, "gateway_payment_id": null, "gateway_status_code": null, "gateway_order_reference_id": null, "gateway_settlement": "CASHFREE", "gateway_reference_name": null}, "payment_offers": null}, "event_time": "2026-05-15T16:32:52+05:30", "type": "PAYMENT_SUCCESS_WEBHOOK"}	\N	\N	\N	2026-05-15 11:02:11.6849+00	2026-05-15 11:02:53.985818+00	5	7
9	4	4	ORDER_4_1778844227_ce0bc21b	5	INR	cashfree	cashfree	success	5584963873	\N	{"data": {"order": {"order_id": "ORDER_4_1778844227_ce0bc21b", "order_amount": 5.0, "order_currency": "INR", "order_tags": null}, "payment": {"cf_payment_id": "5584963873", "payment_status": "SUCCESS", "payment_amount": 5.0, "payment_currency": "INR", "payment_message": "00::TRANSACTION HAS BEEN APPROVED", "payment_time": "2026-05-15T16:53:55+05:30", "bank_reference": "500044712169", "auth_id": null, "payment_method": {"upi": {"channel": "qrcode", "upi_id": "9067326513@axl"}}, "payment_group": "upi"}, "customer_details": {"customer_name": "jay sharma", "customer_id": "USER_4", "customer_email": "kunaldhade40@gmail.com", "customer_phone": "8888888888"}, "payment_gateway_details": {"gateway_name": "CASHFREE", "gateway_order_id": null, "gateway_payment_id": null, "gateway_status_code": null, "gateway_order_reference_id": null, "gateway_settlement": "CASHFREE", "gateway_reference_name": null}, "payment_offers": null}, "event_time": "2026-05-15T16:54:27+05:30", "type": "PAYMENT_SUCCESS_WEBHOOK"}	\N	\N	\N	2026-05-15 11:23:47.347702+00	2026-05-15 11:24:29.066958+00	5	7
10	4	5	ORDER_4_1778851194_d6616de6	5	INR	cashfree	cashfree	success	5585504727	\N	{"data": {"order": {"order_id": "ORDER_4_1778851194_d6616de6", "order_amount": 5.0, "order_currency": "INR", "order_tags": null}, "payment": {"cf_payment_id": "5585504727", "payment_status": "SUCCESS", "payment_amount": 5.0, "payment_currency": "INR", "payment_message": "00::Transaction Success", "payment_time": "2026-05-15T18:50:02+05:30", "bank_reference": "526240222293", "auth_id": null, "payment_method": {"upi": {"channel": "qrcode", "upi_id": "9067326513@ybl", "upi_payer_ifsc": null, "upi_payer_account_number": null, "upi_instrument": "UPI", "upi_instrument_number": null}}, "payment_group": "upi", "international_payment": null, "payment_surcharge": {"payment_surcharge_service_charge": 0, "payment_surcharge_service_tax": 0}}, "customer_details": {"customer_name": "jay sharma", "customer_id": "USER_4", "customer_email": "kunaldhade40@gmail.com", "customer_phone": "8888888888"}, "payment_gateway_details": {"gateway_name": "CASHFREE", "gateway_order_id": null, "gateway_payment_id": null, "gateway_status_code": null, "gateway_order_reference_id": null, "gateway_settlement": "CASHFREE", "gateway_reference_name": null}, "payment_offers": null, "terminal_details": null}, "event_time": "2026-05-15T18:50:27+05:30", "type": "PAYMENT_SUCCESS_WEBHOOK"}	\N	\N	\N	2026-05-15 13:19:54.382939+00	2026-05-15 13:20:27.929497+00	5	7
11	4	6	ORDER_4_1778928586_8ba7b868	1	INR	cashfree	cashfree	success	5592011140	\N	{"data": {"order": {"order_id": "ORDER_4_1778928586_8ba7b868", "order_amount": 1.0, "order_currency": "INR", "order_tags": null}, "payment": {"cf_payment_id": "5592011140", "payment_status": "SUCCESS", "payment_amount": 1.0, "payment_currency": "INR", "payment_message": "00::TRANSACTION HAS BEEN APPROVED", "payment_time": "2026-05-16T16:19:52+05:30", "bank_reference": "194165445323", "auth_id": null, "payment_method": {"upi": {"channel": "qrcode", "upi_id": "9067326513@axl"}}, "payment_group": "upi"}, "customer_details": {"customer_name": "jay sharma", "customer_id": "USER_4", "customer_email": "kunaldhade40@gmail.com", "customer_phone": "8888888888"}, "payment_gateway_details": {"gateway_name": "CASHFREE", "gateway_order_id": null, "gateway_payment_id": null, "gateway_status_code": null, "gateway_order_reference_id": null, "gateway_settlement": "CASHFREE", "gateway_reference_name": null}, "payment_offers": null}, "event_time": "2026-05-16T16:20:09+05:30", "type": "PAYMENT_SUCCESS_WEBHOOK"}	\N	\N	\N	2026-05-16 10:49:46.304462+00	2026-05-16 10:50:10.594823+00	1	7
\.


--
-- Data for Name: payout; Type: TABLE DATA; Schema: public; Owner: tragene_user
--

COPY public.payout (id, user_id, challenge_purchase_id, amount, profit_share_percentage, status, admin_notes, payout_date, due_date, payment_method, transaction_id, bank_account_details, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: rule_violation; Type: TABLE DATA; Schema: public; Owner: tragene_user
--

COPY public.rule_violation (id, challenge_purchase_id, rule_name, rule_value_limit, rule_value_actual, violation_message, snapshot_id, severity, is_hard_fail, action_taken, violated_at) FROM stdin;
\.


--
-- Data for Name: support_ticket; Type: TABLE DATA; Schema: public; Owner: tragene_user
--

COPY public.support_ticket (id, user_id, subject, message, status, priority, assigned_to, resolution, created_at, updated_at, resolved_at, ticket_number, category, admin_note, is_deleted, last_reply_at, last_user_read_at, last_admin_read_at, attachment, closed_by) FROM stdin;
4	5	hello	\N	in_progress	normal	\N	\N	2026-05-15 10:28:25.717007+00	2026-05-15 10:29:44.300786+00	\N	TICK-1778840905-5817	General Questions		f	2026-05-15 10:29:22.988797	2026-05-15 10:28:30.03715	2026-05-15 10:29:44.300412	\N	\N
3	4	fghjjk	\N	closed	normal	\N	\N	2026-05-15 10:15:13.592708+00	2026-05-16 10:06:22.280122+00	\N	TICK-1778840113-6708	KYC & Verification		f	2026-05-15 10:30:01.850008	2026-05-15 13:25:07.432344	2026-05-16 10:06:22.278668	\N	\N
\.


--
-- Data for Name: ticket_message; Type: TABLE DATA; Schema: public; Owner: tragene_user
--

COPY public.ticket_message (id, ticket_id, sender_id, message, is_admin_reply, attachment_url, created_at) FROM stdin;
1	3	4	qwertyuiop	f	uploads/tickets/TICK-1778840113-6708_deadpool.jpg	2026-05-15 10:15:13.596862+00
2	3	1	qwertyuiopasdfghjklzxcvbnm	t	\N	2026-05-15 10:15:47.641135+00
3	3	4	working \r\n	f	\N	2026-05-15 10:20:34.256495+00
4	4	5	this site is fully working	f	uploads/tickets/TICK-1778840905-5817_logo.png	2026-05-15 10:28:25.718626+00
5	3	1	ok	t	\N	2026-05-15 10:29:05.595657+00
6	4	1	yes	t	\N	2026-05-15 10:29:22.990916+00
7	3	1	yes	t	\N	2026-05-15 10:30:01.858359+00
\.


--
-- Data for Name: trade; Type: TABLE DATA; Schema: public; Owner: tragene_user
--

COPY public.trade (id, challenge_purchase_id, trade_id, symbol, trade_type, volume, open_price, close_price, open_time, close_time, swap, commission, profit, status, notes, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: user; Type: TABLE DATA; Schema: public; Owner: tragene_user
--

COPY public."user" (id, first_name, last_name, email, phone, dob, country, state, password, is_admin, is_banned, created_at, phone_verified, email_verified, kyc_status, id_front_url, id_back_url, document_type, document_number, kyc_submitted_at, kyc_notes, email_verification_token, phone_verification_code, phone_verification_sent_at, phone_verification_attempts, last_balance_check, balance_check_hash, trading_alias, trader_level, is_compact_view) FROM stdin;
1	Tragene	Admin	admin@tragene.com	0000000000	1990-01-01	India	Maharashtra	scrypt:32768:8:1$DakzQVGVVlhBW70d$59d552bd3bc69e4d826d22a9735ae22babc483e28d0e3613c574a2a1eda36013a10e274fa8a787cbc3265519dc1bd0b2a9d1f4af73081f9c69d29ced0fb872a4	t	f	2026-05-06 09:57:14.383605+00	t	t	approved					\N		\N	\N	\N	0	\N		\N	Beginner	f
3	kunal	dhade	dhadekunal11@gmail.com	9067326513	2007-08-30	India	Maharashtra	scrypt:32768:8:1$OFjyzx9cHu3obq9I$ef76f81babaeefeb196a28938dfec8ba78030490f2df22c223ccb975d81251976b97c9509a7854ad787eb2648fe4f3b733a2545e90aab46cd5cbfea75b264dc2	f	f	2026-05-07 08:43:43.789797+00	f	f	pending					\N		QpGbOR4QAgBuC8y0T0x8CAQXtr6ePCqvJ5ZiaNvleaI	\N	\N	0	\N		\N	Beginner	f
5	tragene	funded	tragene.co@gmail.com	9067326513	2004-10-12	India	Tamil Nadu	scrypt:32768:8:1$QGPMNkYNm7pNpnXz$1c13dcfccf503691bf7299ee17477ddb4e09a62a11aa8e3b6af8ee3d722b0f3b53973626899987657d17f1ae67b2b5a1dde981684d20a58c1c4179cb7196dbfd	f	f	2026-05-15 10:24:42.514052+00	f	t	approved	uploads/kyc/5_1778840819_front.jpg	uploads/kyc/5_1778840819_back.jpg	aadhaar	1234567890	2026-05-15 10:26:59.702415+00		\N	\N	\N	0	\N			Starter	f
6	Amol 	Jadhav 	amoldj87@gmail.com	8957410001	1987-09-18	India	Maharashtra	scrypt:32768:8:1$hZW2FkI1bqZbKJXn$13f0e6a7a46d78a8caa7f70d95b7765f3accfa71f290bac1335f4bc63ce3f843e731b58ed857e4a7fceeb787f97d95c6f1b86eb01b482e32b04bf463e2b7f0b8	f	f	2026-05-15 18:02:47.001874+00	f	f	pending					\N		\N	\N	\N	0	\N			Starter	f
7	Samaya	Prasanth	prasanth01236@gmail.com	8778907605	2007-11-19	India	Tamil Nadu	scrypt:32768:8:1$Wp8CaGsUjsjp7K0A$1d683e17477d42115364293cddee568e78fe7ad90ee42c6d24f6f5323c417462631f57eadb8fca3e7af9ee086c4bd9cf92d427fec0fa6e47109ec4ddfd9571ba	f	f	2026-05-16 13:52:11.472019+00	f	f	pending					\N		\N	\N	\N	0	\N			Starter	f
4	jay	sharma	kunaldhade40@gmail.com	8888888888	2004-10-13	UK	\N	scrypt:32768:8:1$KK29tXrKCDPQO0pL$260e8372f8be2ffc8bfafcd7831a92e7efbf8b061e1e8bcd625801d4b44562fc5627c0dd59dbbfa5cf3b367de8f7c741f6db6c4caf823a101e927fd0a70347c5	f	f	2026-05-15 06:46:30.44162+00	t	t	approved	uploads/kyc/4_1778828565_front.jpg	uploads/kyc/4_1778828566_back.jpg	pan	1234567890	2026-05-15 07:02:46.130656+00		\N	\N	\N	0	\N		\N	Beginner	f
\.


--
-- Data for Name: waitlist_leads; Type: TABLE DATA; Schema: public; Owner: tragene_user
--

COPY public.waitlist_leads (id, name, email, phone, experience, platform, plan_interest, problem, feedback, early_access, status, created_at) FROM stdin;
1	kunal	kunal@gmail.com	8888888888	Beginner	MT4	199rs for 200$	se	dfsgjk	t	new	2026-05-06 09:58:58.408889+00
2	Kunal	kunal@gmail.com	8888888888	Beginner	MT5	199rs for 200$	Hi	Hi	t	new	2026-05-06 10:23:32.792691+00
3	Rahul Pramanik	rahulpramanik492@gmail.com	7477638340	Beginner	MT4	199rs for 200$			t	new	2026-05-15 07:35:45.367564+00
4	Rahul Pramanik	rahulpramanik492@gmail.com	7477638340	Beginner	MT4	199rs for 200$			t	new	2026-05-15 07:36:48.908385+00
5	Rahul Pramanik	rahulpramanik492@gmail.com	7477638340	Beginner	MT4	199rs for 200$			t	new	2026-05-15 07:38:43.081692+00
\.


--
-- Data for Name: webhook_log; Type: TABLE DATA; Schema: public; Owner: tragene_user
--

COPY public.webhook_log (id, event_type, order_id, raw_payload, headers, signature, status, error_message, created_at, processed_at) FROM stdin;
2	PAYMENT_SUCCESS_WEBHOOK	ORDER_4_1778842931_d9e5c67c	{"data":{"order":{"order_id":"ORDER_4_1778842931_d9e5c67c","order_amount":5.00,"order_currency":"INR","order_tags":null},"payment":{"cf_payment_id":"5584846019","payment_status":"SUCCESS","payment_amount":5.00,"payment_currency":"INR","payment_message":"00::Transaction Success","payment_time":"2026-05-15T16:32:34+05:30","bank_reference":"125526494410","auth_id":null,"payment_method":{"upi":{"channel":"qrcode","upi_id":"9067326513@axl","upi_payer_ifsc":null,"upi_payer_account_number":null,"upi_instrument":"UPI","upi_instrument_number":null}},"payment_group":"upi","international_payment":null,"payment_surcharge":{"payment_surcharge_service_charge":0,"payment_surcharge_service_tax":0}},"customer_details":{"customer_name":"jay sharma","customer_id":"USER_4","customer_email":"kunaldhade40@gmail.com","customer_phone":"8888888888"},"payment_gateway_details":{"gateway_name":"CASHFREE","gateway_order_id":null,"gateway_payment_id":null,"gateway_status_code":null,"gateway_order_reference_id":null,"gateway_settlement":"CASHFREE","gateway_reference_name":null},"payment_offers":null,"terminal_details":null},"event_time":"2026-05-15T16:32:52+05:30","type":"PAYMENT_SUCCESS_WEBHOOK"}	{"Host": "www.tragenefunded.com", "X-Real-Ip": "52.66.101.190", "X-Forwarded-For": "52.66.101.190", "Connection": "close", "Content-Length": "1185", "User-Agent": "ReactorNetty/1.2.16", "Accept": "*/*", "X-Webhook-Version": "2025-01-01", "X-Webhook-Timestamp": "1778842972801", "X-Idempotency-Key": "m9PPIn7HYxcgdb2ZB1/iW12ycU3/4ZF8bK5O9Xs0rs8=", "X-Webhook-Signature": "+WGUzF2idpvqL5cb1qYEESCHo7YWh/9kefIvpO+69MI=", "Content-Type": "application/json", "X-Webhook-Attempt": "1", "X-Datadog-Trace-Id": "4264888550462351617", "X-Datadog-Parent-Id": "8994251651387641632", "X-Datadog-Sampling-Priority": "-1", "X-Datadog-Tags": "_dd.p.tid=6a06fd5c00000000", "Traceparent": "00-6a06fd5c000000003b2fed8a50f06901-7cd200392d6e4f20-00", "Tracestate": "dd=s:-1;p:7cd200392d6e4f20;t.tid:6a06fd5c00000000"}	+WGUzF2idpvqL5cb1qYEESCHo7YWh/9kefIvpO+69MI=	processed	\N	2026-05-15 11:02:53.330117+00	2026-05-15 11:02:53.699119+00
1	PAYMENT_SUCCESS_WEBHOOK	ORDER_4_1778842931_d9e5c67c	{"data":{"order":{"order_id":"ORDER_4_1778842931_d9e5c67c","order_amount":5.00,"order_currency":"INR","order_tags":null},"payment":{"cf_payment_id":"5584846019","payment_status":"SUCCESS","payment_amount":5.00,"payment_currency":"INR","payment_message":"00::Transaction Success","payment_time":"2026-05-15T16:32:34+05:30","bank_reference":"125526494410","auth_id":null,"payment_method":{"upi":{"channel":"qrcode","upi_id":"9067326513@axl"}},"payment_group":"upi"},"customer_details":{"customer_name":"jay sharma","customer_id":"USER_4","customer_email":"kunaldhade40@gmail.com","customer_phone":"8888888888"},"payment_gateway_details":{"gateway_name":"CASHFREE","gateway_order_id":null,"gateway_payment_id":null,"gateway_status_code":null,"gateway_order_reference_id":null,"gateway_settlement":"CASHFREE","gateway_reference_name":null},"payment_offers":null},"event_time":"2026-05-15T16:32:52+05:30","type":"PAYMENT_SUCCESS_WEBHOOK"}	{"Host": "www.tragenefunded.com", "X-Real-Ip": "52.66.101.190", "X-Forwarded-For": "52.66.101.190", "Connection": "close", "Content-Length": "933", "User-Agent": "ReactorNetty/1.2.16", "Accept": "*/*", "X-Webhook-Version": "2023-08-01", "X-Webhook-Timestamp": "1778842972792", "X-Webhook-Signature": "sL1TAAsWYXWgWGOw3jEYJleCDrXlBEyqYKvPBkMB4NM=", "Content-Type": "application/json", "X-Webhook-Attempt": "1", "X-Datadog-Trace-Id": "4264888550462351617", "X-Datadog-Parent-Id": "294641028651950130", "X-Datadog-Sampling-Priority": "-1", "X-Datadog-Tags": "_dd.p.tid=6a06fd5c00000000", "Traceparent": "00-6a06fd5c000000003b2fed8a50f06901-0416c674590e2032-00", "Tracestate": "dd=s:-1;p:0416c674590e2032;t.tid:6a06fd5c00000000"}	sL1TAAsWYXWgWGOw3jEYJleCDrXlBEyqYKvPBkMB4NM=	processed	\N	2026-05-15 11:02:53.326521+00	2026-05-15 11:02:53.98469+00
4	PAYMENT_SUCCESS_WEBHOOK	ORDER_4_1778844227_ce0bc21b	{"data":{"order":{"order_id":"ORDER_4_1778844227_ce0bc21b","order_amount":5.00,"order_currency":"INR","order_tags":null},"payment":{"cf_payment_id":"5584963873","payment_status":"SUCCESS","payment_amount":5.00,"payment_currency":"INR","payment_message":"00::TRANSACTION HAS BEEN APPROVED","payment_time":"2026-05-15T16:53:55+05:30","bank_reference":"500044712169","auth_id":null,"payment_method":{"upi":{"channel":"qrcode","upi_id":"9067326513@axl","upi_payer_ifsc":null,"upi_payer_account_number":null,"upi_instrument":"UPI","upi_instrument_number":null}},"payment_group":"upi","international_payment":null,"payment_surcharge":{"payment_surcharge_service_charge":0,"payment_surcharge_service_tax":0}},"customer_details":{"customer_name":"jay sharma","customer_id":"USER_4","customer_email":"kunaldhade40@gmail.com","customer_phone":"8888888888"},"payment_gateway_details":{"gateway_name":"CASHFREE","gateway_order_id":null,"gateway_payment_id":null,"gateway_status_code":null,"gateway_order_reference_id":null,"gateway_settlement":"CASHFREE","gateway_reference_name":null},"payment_offers":null,"terminal_details":null},"event_time":"2026-05-15T16:54:27+05:30","type":"PAYMENT_SUCCESS_WEBHOOK"}	{"Host": "www.tragenefunded.com", "X-Real-Ip": "52.66.101.190", "X-Forwarded-For": "52.66.101.190", "Connection": "close", "Content-Length": "1195", "User-Agent": "ReactorNetty/1.2.16", "Accept": "*/*", "X-Webhook-Version": "2025-01-01", "X-Webhook-Timestamp": "1778844267897", "X-Idempotency-Key": "thAjk/8i2qGaMxrRkERmYLFounHnkTLDvF/c5vKlVOI=", "X-Webhook-Signature": "iigix8fiXWNkfnkKD1DPpZ/I7Ebur17aGNrZwQWIiPM=", "Content-Type": "application/json", "X-Webhook-Attempt": "1", "X-Datadog-Trace-Id": "5227501260816865759", "X-Datadog-Parent-Id": "5299444596869895735", "X-Datadog-Sampling-Priority": "-1", "X-Datadog-Tags": "_dd.p.tid=6a07026b00000000", "Traceparent": "00-6a07026b00000000488bd0b341e559df-498b68c87f4b1637-00", "Tracestate": "dd=s:-1;p:498b68c87f4b1637;t.tid:6a07026b00000000"}	iigix8fiXWNkfnkKD1DPpZ/I7Ebur17aGNrZwQWIiPM=	processed	\N	2026-05-15 11:24:28.422803+00	2026-05-15 11:24:28.643229+00
3	PAYMENT_SUCCESS_WEBHOOK	ORDER_4_1778844227_ce0bc21b	{"data":{"order":{"order_id":"ORDER_4_1778844227_ce0bc21b","order_amount":5.00,"order_currency":"INR","order_tags":null},"payment":{"cf_payment_id":"5584963873","payment_status":"SUCCESS","payment_amount":5.00,"payment_currency":"INR","payment_message":"00::TRANSACTION HAS BEEN APPROVED","payment_time":"2026-05-15T16:53:55+05:30","bank_reference":"500044712169","auth_id":null,"payment_method":{"upi":{"channel":"qrcode","upi_id":"9067326513@axl"}},"payment_group":"upi"},"customer_details":{"customer_name":"jay sharma","customer_id":"USER_4","customer_email":"kunaldhade40@gmail.com","customer_phone":"8888888888"},"payment_gateway_details":{"gateway_name":"CASHFREE","gateway_order_id":null,"gateway_payment_id":null,"gateway_status_code":null,"gateway_order_reference_id":null,"gateway_settlement":"CASHFREE","gateway_reference_name":null},"payment_offers":null},"event_time":"2026-05-15T16:54:27+05:30","type":"PAYMENT_SUCCESS_WEBHOOK"}	{"Host": "www.tragenefunded.com", "X-Real-Ip": "52.66.101.190", "X-Forwarded-For": "52.66.101.190", "Connection": "close", "Content-Length": "943", "User-Agent": "ReactorNetty/1.2.16", "Accept": "*/*", "X-Webhook-Version": "2023-08-01", "X-Webhook-Timestamp": "1778844267896", "X-Webhook-Signature": "PhBHuKwBU0wf0kHORL2ny8Xmm/P+7SAS2JV68kqa/3s=", "Content-Type": "application/json", "X-Webhook-Attempt": "1", "X-Datadog-Trace-Id": "5227501260816865759", "X-Datadog-Parent-Id": "5427602342697762549", "X-Datadog-Sampling-Priority": "-1", "X-Datadog-Tags": "_dd.p.tid=6a07026b00000000", "Traceparent": "00-6a07026b00000000488bd0b341e559df-4b52b792f293fef5-00", "Tracestate": "dd=s:-1;p:4b52b792f293fef5;t.tid:6a07026b00000000"}	PhBHuKwBU0wf0kHORL2ny8Xmm/P+7SAS2JV68kqa/3s=	processed	\N	2026-05-15 11:24:28.418808+00	2026-05-15 11:24:29.066711+00
5	PAYMENT_SUCCESS_WEBHOOK	ORDER_4_1778851194_d6616de6	{"data":{"order":{"order_id":"ORDER_4_1778851194_d6616de6","order_amount":5.00,"order_currency":"INR","order_tags":null},"payment":{"cf_payment_id":"5585504727","payment_status":"SUCCESS","payment_amount":5.00,"payment_currency":"INR","payment_message":"00::Transaction Success","payment_time":"2026-05-15T18:50:02+05:30","bank_reference":"526240222293","auth_id":null,"payment_method":{"upi":{"channel":"qrcode","upi_id":"9067326513@ybl","upi_payer_ifsc":null,"upi_payer_account_number":null,"upi_instrument":"UPI","upi_instrument_number":null}},"payment_group":"upi","international_payment":null,"payment_surcharge":{"payment_surcharge_service_charge":0,"payment_surcharge_service_tax":0}},"customer_details":{"customer_name":"jay sharma","customer_id":"USER_4","customer_email":"kunaldhade40@gmail.com","customer_phone":"8888888888"},"payment_gateway_details":{"gateway_name":"CASHFREE","gateway_order_id":null,"gateway_payment_id":null,"gateway_status_code":null,"gateway_order_reference_id":null,"gateway_settlement":"CASHFREE","gateway_reference_name":null},"payment_offers":null,"terminal_details":null},"event_time":"2026-05-15T18:50:27+05:30","type":"PAYMENT_SUCCESS_WEBHOOK"}	{"Host": "www.tragenefunded.com", "X-Real-Ip": "52.66.101.190", "X-Forwarded-For": "52.66.101.190", "Connection": "close", "Content-Length": "1185", "User-Agent": "ReactorNetty/1.2.16", "Accept": "*/*", "X-Webhook-Version": "2025-01-01", "X-Webhook-Timestamp": "1778851227122", "X-Idempotency-Key": "DEMQ5ZVLLUx9Zb+uh/DBjega7mUICj0qbxVvZB7Oe5I=", "X-Webhook-Signature": "hbC0qxk1kOdPzNhXiNgmH4xM0pmhy6+YzQNPusDUeC4=", "Content-Type": "application/json", "X-Webhook-Attempt": "1", "X-Datadog-Trace-Id": "7211060905887452129", "X-Datadog-Parent-Id": "307035260691418778", "X-Datadog-Sampling-Priority": "-1", "X-Datadog-Tags": "_dd.p.tid=6a071d9b00000000", "Traceparent": "00-6a071d9b000000006412d5b02520cbe1-0442cef15f080e9a-00", "Tracestate": "dd=s:-1;p:0442cef15f080e9a;t.tid:6a071d9b00000000"}	hbC0qxk1kOdPzNhXiNgmH4xM0pmhy6+YzQNPusDUeC4=	processed	\N	2026-05-15 13:20:27.717184+00	2026-05-15 13:20:27.92833+00
6	PAYMENT_SUCCESS_WEBHOOK	ORDER_4_1778851194_d6616de6	{"data":{"order":{"order_id":"ORDER_4_1778851194_d6616de6","order_amount":5.00,"order_currency":"INR","order_tags":null},"payment":{"cf_payment_id":"5585504727","payment_status":"SUCCESS","payment_amount":5.00,"payment_currency":"INR","payment_message":"00::Transaction Success","payment_time":"2026-05-15T18:50:02+05:30","bank_reference":"526240222293","auth_id":null,"payment_method":{"upi":{"channel":"qrcode","upi_id":"9067326513@ybl"}},"payment_group":"upi"},"customer_details":{"customer_name":"jay sharma","customer_id":"USER_4","customer_email":"kunaldhade40@gmail.com","customer_phone":"8888888888"},"payment_gateway_details":{"gateway_name":"CASHFREE","gateway_order_id":null,"gateway_payment_id":null,"gateway_status_code":null,"gateway_order_reference_id":null,"gateway_settlement":"CASHFREE","gateway_reference_name":null},"payment_offers":null},"event_time":"2026-05-15T18:50:27+05:30","type":"PAYMENT_SUCCESS_WEBHOOK"}	{"Host": "www.tragenefunded.com", "X-Real-Ip": "52.66.101.190", "X-Forwarded-For": "52.66.101.190", "Connection": "close", "Content-Length": "933", "User-Agent": "ReactorNetty/1.2.16", "Accept": "*/*", "X-Webhook-Version": "2023-08-01", "X-Webhook-Timestamp": "1778851227124", "X-Webhook-Signature": "IOduyZ86D5ya7NfyNlrwXQbdYYx/a3jlx/TtC9u3z7g=", "Content-Type": "application/json", "X-Webhook-Attempt": "1", "X-Datadog-Trace-Id": "7211060905887452129", "X-Datadog-Parent-Id": "313164124191954726", "X-Datadog-Sampling-Priority": "-1", "X-Datadog-Tags": "_dd.p.tid=6a071d9b00000000", "Traceparent": "00-6a071d9b000000006412d5b02520cbe1-0458951c9adb9726-00", "Tracestate": "dd=s:-1;p:0458951c9adb9726;t.tid:6a071d9b00000000"}	IOduyZ86D5ya7NfyNlrwXQbdYYx/a3jlx/TtC9u3z7g=	duplicate	\N	2026-05-15 13:20:27.729655+00	\N
7	PAYMENT_SUCCESS_WEBHOOK	ORDER_4_1778928586_8ba7b868	{"data":{"order":{"order_id":"ORDER_4_1778928586_8ba7b868","order_amount":1.00,"order_currency":"INR","order_tags":null},"payment":{"cf_payment_id":"5592011140","payment_status":"SUCCESS","payment_amount":1.00,"payment_currency":"INR","payment_message":"00::TRANSACTION HAS BEEN APPROVED","payment_time":"2026-05-16T16:19:52+05:30","bank_reference":"194165445323","auth_id":null,"payment_method":{"upi":{"channel":"qrcode","upi_id":"9067326513@axl"}},"payment_group":"upi"},"customer_details":{"customer_name":"jay sharma","customer_id":"USER_4","customer_email":"kunaldhade40@gmail.com","customer_phone":"8888888888"},"payment_gateway_details":{"gateway_name":"CASHFREE","gateway_order_id":null,"gateway_payment_id":null,"gateway_status_code":null,"gateway_order_reference_id":null,"gateway_settlement":"CASHFREE","gateway_reference_name":null},"payment_offers":null},"event_time":"2026-05-16T16:20:09+05:30","type":"PAYMENT_SUCCESS_WEBHOOK"}	{"Host": "www.tragenefunded.com", "X-Real-Ip": "52.66.101.190", "X-Forwarded-For": "52.66.101.190", "Connection": "close", "Content-Length": "943", "User-Agent": "ReactorNetty/1.2.16", "Accept": "*/*", "X-Webhook-Version": "2023-08-01", "X-Webhook-Timestamp": "1778928609792", "X-Webhook-Signature": "U8JU6XWdb+h7VmERVcewjGnS3XT2F91e0eES78HPJgk=", "Content-Type": "application/json", "X-Webhook-Attempt": "1", "X-Datadog-Trace-Id": "5826860754889120650", "X-Datadog-Parent-Id": "8776232767097566414", "X-Datadog-Sampling-Priority": "-1", "X-Datadog-Tags": "_dd.p.tid=6a084be100000000", "Traceparent": "00-6a084be10000000050dd2afc0ad49b8a-79cb713404fe74ce-00", "Tracestate": "dd=s:-1;p:79cb713404fe74ce;t.tid:6a084be100000000"}	U8JU6XWdb+h7VmERVcewjGnS3XT2F91e0eES78HPJgk=	processed	\N	2026-05-16 10:50:10.365537+00	2026-05-16 10:50:10.594009+00
8	PAYMENT_SUCCESS_WEBHOOK	ORDER_4_1778928586_8ba7b868	{"data":{"order":{"order_id":"ORDER_4_1778928586_8ba7b868","order_amount":1.00,"order_currency":"INR","order_tags":null},"payment":{"cf_payment_id":"5592011140","payment_status":"SUCCESS","payment_amount":1.00,"payment_currency":"INR","payment_message":"00::TRANSACTION HAS BEEN APPROVED","payment_time":"2026-05-16T16:19:52+05:30","bank_reference":"194165445323","auth_id":null,"payment_method":{"upi":{"channel":"qrcode","upi_id":"9067326513@axl","upi_payer_ifsc":null,"upi_payer_account_number":null,"upi_instrument":"UPI","upi_instrument_number":null}},"payment_group":"upi","international_payment":null,"payment_surcharge":{"payment_surcharge_service_charge":0,"payment_surcharge_service_tax":0}},"customer_details":{"customer_name":"jay sharma","customer_id":"USER_4","customer_email":"kunaldhade40@gmail.com","customer_phone":"8888888888"},"payment_gateway_details":{"gateway_name":"CASHFREE","gateway_order_id":null,"gateway_payment_id":null,"gateway_status_code":null,"gateway_order_reference_id":null,"gateway_settlement":"CASHFREE","gateway_reference_name":null},"payment_offers":null,"terminal_details":null},"event_time":"2026-05-16T16:20:09+05:30","type":"PAYMENT_SUCCESS_WEBHOOK"}	{"Host": "www.tragenefunded.com", "X-Real-Ip": "52.66.101.190", "X-Forwarded-For": "52.66.101.190", "Connection": "close", "Content-Length": "1195", "User-Agent": "ReactorNetty/1.2.16", "Accept": "*/*", "X-Webhook-Version": "2025-01-01", "X-Webhook-Timestamp": "1778928609800", "X-Idempotency-Key": "EvD7XC1jDP9m8q5L5GagIl/bSk4M4wJ1yOe3dm/JIbY=", "X-Webhook-Signature": "lHUr4p7ZoY3qowdB8h/gxDmIFNk5VqDatBP4yvTGddo=", "Content-Type": "application/json", "X-Webhook-Attempt": "1", "X-Datadog-Trace-Id": "5826860754889120650", "X-Datadog-Parent-Id": "4948424494031983570", "X-Datadog-Sampling-Priority": "-1", "X-Datadog-Tags": "_dd.p.tid=6a084be100000000", "Traceparent": "00-6a084be10000000050dd2afc0ad49b8a-44ac55dc049e53d2-00", "Tracestate": "dd=s:-1;p:44ac55dc049e53d2;t.tid:6a084be100000000"}	lHUr4p7ZoY3qowdB8h/gxDmIFNk5VqDatBP4yvTGddo=	duplicate	\N	2026-05-16 10:50:10.367372+00	\N
\.


--
-- Name: account_snapshot_id_seq; Type: SEQUENCE SET; Schema: public; Owner: tragene_user
--

SELECT pg_catalog.setval('public.account_snapshot_id_seq', 1, false);


--
-- Name: admin_log_id_seq; Type: SEQUENCE SET; Schema: public; Owner: tragene_user
--

SELECT pg_catalog.setval('public.admin_log_id_seq', 1, false);


--
-- Name: challenge_purchase_id_seq; Type: SEQUENCE SET; Schema: public; Owner: tragene_user
--

SELECT pg_catalog.setval('public.challenge_purchase_id_seq', 6, true);


--
-- Name: challenge_template_id_seq; Type: SEQUENCE SET; Schema: public; Owner: tragene_user
--

SELECT pg_catalog.setval('public.challenge_template_id_seq', 7, true);


--
-- Name: daily_snapshot_id_seq; Type: SEQUENCE SET; Schema: public; Owner: tragene_user
--

SELECT pg_catalog.setval('public.daily_snapshot_id_seq', 1, false);


--
-- Name: ea_trade_id_seq; Type: SEQUENCE SET; Schema: public; Owner: tragene_user
--

SELECT pg_catalog.setval('public.ea_trade_id_seq', 1, false);


--
-- Name: faq_id_seq; Type: SEQUENCE SET; Schema: public; Owner: tragene_user
--

SELECT pg_catalog.setval('public.faq_id_seq', 38, true);


--
-- Name: notification_id_seq; Type: SEQUENCE SET; Schema: public; Owner: tragene_user
--

SELECT pg_catalog.setval('public.notification_id_seq', 1, false);


--
-- Name: payment_id_seq; Type: SEQUENCE SET; Schema: public; Owner: tragene_user
--

SELECT pg_catalog.setval('public.payment_id_seq', 11, true);


--
-- Name: payout_id_seq; Type: SEQUENCE SET; Schema: public; Owner: tragene_user
--

SELECT pg_catalog.setval('public.payout_id_seq', 1, false);


--
-- Name: rule_violation_id_seq; Type: SEQUENCE SET; Schema: public; Owner: tragene_user
--

SELECT pg_catalog.setval('public.rule_violation_id_seq', 1, false);


--
-- Name: support_ticket_id_seq; Type: SEQUENCE SET; Schema: public; Owner: tragene_user
--

SELECT pg_catalog.setval('public.support_ticket_id_seq', 4, true);


--
-- Name: ticket_message_id_seq; Type: SEQUENCE SET; Schema: public; Owner: tragene_user
--

SELECT pg_catalog.setval('public.ticket_message_id_seq', 7, true);


--
-- Name: trade_id_seq; Type: SEQUENCE SET; Schema: public; Owner: tragene_user
--

SELECT pg_catalog.setval('public.trade_id_seq', 1, false);


--
-- Name: user_id_seq; Type: SEQUENCE SET; Schema: public; Owner: tragene_user
--

SELECT pg_catalog.setval('public.user_id_seq', 7, true);


--
-- Name: waitlist_leads_id_seq; Type: SEQUENCE SET; Schema: public; Owner: tragene_user
--

SELECT pg_catalog.setval('public.waitlist_leads_id_seq', 5, true);


--
-- Name: webhook_log_id_seq; Type: SEQUENCE SET; Schema: public; Owner: tragene_user
--

SELECT pg_catalog.setval('public.webhook_log_id_seq', 8, true);


--
-- Name: account_snapshot account_snapshot_pkey; Type: CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.account_snapshot
    ADD CONSTRAINT account_snapshot_pkey PRIMARY KEY (id);


--
-- Name: admin_log admin_log_pkey; Type: CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.admin_log
    ADD CONSTRAINT admin_log_pkey PRIMARY KEY (id);


--
-- Name: challenge_purchase challenge_purchase_pkey; Type: CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.challenge_purchase
    ADD CONSTRAINT challenge_purchase_pkey PRIMARY KEY (id);


--
-- Name: challenge_template challenge_template_pkey; Type: CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.challenge_template
    ADD CONSTRAINT challenge_template_pkey PRIMARY KEY (id);


--
-- Name: daily_snapshot daily_snapshot_pkey; Type: CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.daily_snapshot
    ADD CONSTRAINT daily_snapshot_pkey PRIMARY KEY (id);


--
-- Name: ea_trade ea_trade_pkey; Type: CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.ea_trade
    ADD CONSTRAINT ea_trade_pkey PRIMARY KEY (id);


--
-- Name: faq faq_pkey; Type: CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.faq
    ADD CONSTRAINT faq_pkey PRIMARY KEY (id);


--
-- Name: notification notification_pkey; Type: CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_pkey PRIMARY KEY (id);


--
-- Name: payment payment_pkey; Type: CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.payment
    ADD CONSTRAINT payment_pkey PRIMARY KEY (id);


--
-- Name: payout payout_pkey; Type: CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.payout
    ADD CONSTRAINT payout_pkey PRIMARY KEY (id);


--
-- Name: rule_violation rule_violation_pkey; Type: CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.rule_violation
    ADD CONSTRAINT rule_violation_pkey PRIMARY KEY (id);


--
-- Name: support_ticket support_ticket_pkey; Type: CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.support_ticket
    ADD CONSTRAINT support_ticket_pkey PRIMARY KEY (id);


--
-- Name: ticket_message ticket_message_pkey; Type: CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.ticket_message
    ADD CONSTRAINT ticket_message_pkey PRIMARY KEY (id);


--
-- Name: trade trade_pkey; Type: CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.trade
    ADD CONSTRAINT trade_pkey PRIMARY KEY (id);


--
-- Name: daily_snapshot unique_challenge_date; Type: CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.daily_snapshot
    ADD CONSTRAINT unique_challenge_date UNIQUE (challenge_purchase_id, snapshot_date);


--
-- Name: ea_trade unique_challenge_ticket; Type: CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.ea_trade
    ADD CONSTRAINT unique_challenge_ticket UNIQUE (challenge_purchase_id, ticket);


--
-- Name: user user_pkey; Type: CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public."user"
    ADD CONSTRAINT user_pkey PRIMARY KEY (id);


--
-- Name: waitlist_leads waitlist_leads_pkey; Type: CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.waitlist_leads
    ADD CONSTRAINT waitlist_leads_pkey PRIMARY KEY (id);


--
-- Name: webhook_log webhook_log_pkey; Type: CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.webhook_log
    ADD CONSTRAINT webhook_log_pkey PRIMARY KEY (id);


--
-- Name: idx_daily_challenge_date; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX idx_daily_challenge_date ON public.daily_snapshot USING btree (challenge_purchase_id, snapshot_date, is_trading_day);


--
-- Name: idx_daily_trading_status; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX idx_daily_trading_status ON public.daily_snapshot USING btree (challenge_purchase_id, is_trading_day, snapshot_date);


--
-- Name: idx_snapshot_challenge_archived; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX idx_snapshot_challenge_archived ON public.account_snapshot USING btree (challenge_purchase_id, is_archived);


--
-- Name: idx_snapshot_challenge_timestamp; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX idx_snapshot_challenge_timestamp ON public.account_snapshot USING btree (challenge_purchase_id, "timestamp");


--
-- Name: idx_trade_challenge_close; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX idx_trade_challenge_close ON public.ea_trade USING btree (challenge_purchase_id, close_time);


--
-- Name: idx_trade_challenge_status; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX idx_trade_challenge_status ON public.ea_trade USING btree (challenge_purchase_id, status);


--
-- Name: idx_trade_magic; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX idx_trade_magic ON public.ea_trade USING btree (magic, challenge_purchase_id);


--
-- Name: idx_violation_challenge_rule; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX idx_violation_challenge_rule ON public.rule_violation USING btree (challenge_purchase_id, rule_name);


--
-- Name: idx_violation_severity_date; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX idx_violation_severity_date ON public.rule_violation USING btree (severity, violated_at);


--
-- Name: ix_account_snapshot_challenge_purchase_id; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_account_snapshot_challenge_purchase_id ON public.account_snapshot USING btree (challenge_purchase_id);


--
-- Name: ix_account_snapshot_drawdown_from_peak; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_account_snapshot_drawdown_from_peak ON public.account_snapshot USING btree (drawdown_from_peak);


--
-- Name: ix_account_snapshot_is_archived; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_account_snapshot_is_archived ON public.account_snapshot USING btree (is_archived);


--
-- Name: ix_account_snapshot_mt5_login; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_account_snapshot_mt5_login ON public.account_snapshot USING btree (mt5_login);


--
-- Name: ix_account_snapshot_profit_from_start; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_account_snapshot_profit_from_start ON public.account_snapshot USING btree (profit_from_start);


--
-- Name: ix_account_snapshot_timestamp; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_account_snapshot_timestamp ON public.account_snapshot USING btree ("timestamp");


--
-- Name: ix_admin_log_action; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_admin_log_action ON public.admin_log USING btree (action);


--
-- Name: ix_admin_log_admin_id; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_admin_log_admin_id ON public.admin_log USING btree (admin_id);


--
-- Name: ix_admin_log_created_at; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_admin_log_created_at ON public.admin_log USING btree (created_at);


--
-- Name: ix_admin_log_target_id; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_admin_log_target_id ON public.admin_log USING btree (target_id);


--
-- Name: ix_admin_log_target_type; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_admin_log_target_type ON public.admin_log USING btree (target_type);


--
-- Name: ix_challenge_purchase_challenge_code; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_challenge_purchase_challenge_code ON public.challenge_purchase USING btree (challenge_code);


--
-- Name: ix_challenge_purchase_challenge_template_id; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_challenge_purchase_challenge_template_id ON public.challenge_purchase USING btree (challenge_template_id);


--
-- Name: ix_challenge_purchase_challenge_token; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE UNIQUE INDEX ix_challenge_purchase_challenge_token ON public.challenge_purchase USING btree (challenge_token);


--
-- Name: ix_challenge_purchase_completed_at; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_challenge_purchase_completed_at ON public.challenge_purchase USING btree (completed_at);


--
-- Name: ix_challenge_purchase_daily_start_date; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_challenge_purchase_daily_start_date ON public.challenge_purchase USING btree (daily_start_date);


--
-- Name: ix_challenge_purchase_ea_connected; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_challenge_purchase_ea_connected ON public.challenge_purchase USING btree (ea_connected);


--
-- Name: ix_challenge_purchase_end_date; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_challenge_purchase_end_date ON public.challenge_purchase USING btree (end_date);


--
-- Name: ix_challenge_purchase_last_heartbeat; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_challenge_purchase_last_heartbeat ON public.challenge_purchase USING btree (last_heartbeat);


--
-- Name: ix_challenge_purchase_last_updated; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_challenge_purchase_last_updated ON public.challenge_purchase USING btree (last_updated);


--
-- Name: ix_challenge_purchase_mt5_login; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_challenge_purchase_mt5_login ON public.challenge_purchase USING btree (mt5_login);


--
-- Name: ix_challenge_purchase_purchase_date; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_challenge_purchase_purchase_date ON public.challenge_purchase USING btree (purchase_date);


--
-- Name: ix_challenge_purchase_serial_no; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_challenge_purchase_serial_no ON public.challenge_purchase USING btree (serial_no);


--
-- Name: ix_challenge_purchase_start_date; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_challenge_purchase_start_date ON public.challenge_purchase USING btree (start_date);


--
-- Name: ix_challenge_purchase_status; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_challenge_purchase_status ON public.challenge_purchase USING btree (status);


--
-- Name: ix_challenge_purchase_trading_days_completed; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_challenge_purchase_trading_days_completed ON public.challenge_purchase USING btree (trading_days_completed);


--
-- Name: ix_challenge_purchase_user_id; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_challenge_purchase_user_id ON public.challenge_purchase USING btree (user_id);


--
-- Name: ix_challenge_purchase_violation_timestamp; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_challenge_purchase_violation_timestamp ON public.challenge_purchase USING btree (violation_timestamp);


--
-- Name: ix_challenge_template_created_at; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_challenge_template_created_at ON public.challenge_template USING btree (created_at);


--
-- Name: ix_challenge_template_is_active; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_challenge_template_is_active ON public.challenge_template USING btree (is_active);


--
-- Name: ix_challenge_template_name; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_challenge_template_name ON public.challenge_template USING btree (name);


--
-- Name: ix_daily_snapshot_challenge_purchase_id; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_daily_snapshot_challenge_purchase_id ON public.daily_snapshot USING btree (challenge_purchase_id);


--
-- Name: ix_daily_snapshot_had_manual_trades; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_daily_snapshot_had_manual_trades ON public.daily_snapshot USING btree (had_manual_trades);


--
-- Name: ix_daily_snapshot_is_trading_day; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_daily_snapshot_is_trading_day ON public.daily_snapshot USING btree (is_trading_day);


--
-- Name: ix_daily_snapshot_snapshot_date; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_daily_snapshot_snapshot_date ON public.daily_snapshot USING btree (snapshot_date);


--
-- Name: ix_daily_snapshot_violated_daily_dd; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_daily_snapshot_violated_daily_dd ON public.daily_snapshot USING btree (violated_daily_dd);


--
-- Name: ix_ea_trade_challenge_purchase_id; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_ea_trade_challenge_purchase_id ON public.ea_trade USING btree (challenge_purchase_id);


--
-- Name: ix_ea_trade_close_time; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_ea_trade_close_time ON public.ea_trade USING btree (close_time);


--
-- Name: ix_ea_trade_created_at; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_ea_trade_created_at ON public.ea_trade USING btree (created_at);


--
-- Name: ix_ea_trade_is_archived; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_ea_trade_is_archived ON public.ea_trade USING btree (is_archived);


--
-- Name: ix_ea_trade_magic; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_ea_trade_magic ON public.ea_trade USING btree (magic);


--
-- Name: ix_ea_trade_open_time; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_ea_trade_open_time ON public.ea_trade USING btree (open_time);


--
-- Name: ix_ea_trade_status; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_ea_trade_status ON public.ea_trade USING btree (status);


--
-- Name: ix_ea_trade_symbol; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_ea_trade_symbol ON public.ea_trade USING btree (symbol);


--
-- Name: ix_ea_trade_ticket; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_ea_trade_ticket ON public.ea_trade USING btree (ticket);


--
-- Name: ix_faq_category; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_faq_category ON public.faq USING btree (category);


--
-- Name: ix_faq_is_pinned; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_faq_is_pinned ON public.faq USING btree (is_pinned);


--
-- Name: ix_notification_created_at; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_notification_created_at ON public.notification USING btree (created_at);


--
-- Name: ix_notification_is_read; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_notification_is_read ON public.notification USING btree (is_read);


--
-- Name: ix_notification_notification_type; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_notification_notification_type ON public.notification USING btree (notification_type);


--
-- Name: ix_notification_user_id; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_notification_user_id ON public.notification USING btree (user_id);


--
-- Name: ix_payment_challenge_purchase_id; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_payment_challenge_purchase_id ON public.payment USING btree (challenge_purchase_id);


--
-- Name: ix_payment_created_at; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_payment_created_at ON public.payment USING btree (created_at);


--
-- Name: ix_payment_payment_id; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE UNIQUE INDEX ix_payment_payment_id ON public.payment USING btree (payment_id);


--
-- Name: ix_payment_status; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_payment_status ON public.payment USING btree (status);


--
-- Name: ix_payment_user_id; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_payment_user_id ON public.payment USING btree (user_id);


--
-- Name: ix_payout_challenge_purchase_id; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_payout_challenge_purchase_id ON public.payout USING btree (challenge_purchase_id);


--
-- Name: ix_payout_created_at; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_payout_created_at ON public.payout USING btree (created_at);


--
-- Name: ix_payout_due_date; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_payout_due_date ON public.payout USING btree (due_date);


--
-- Name: ix_payout_payout_date; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_payout_payout_date ON public.payout USING btree (payout_date);


--
-- Name: ix_payout_status; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_payout_status ON public.payout USING btree (status);


--
-- Name: ix_payout_user_id; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_payout_user_id ON public.payout USING btree (user_id);


--
-- Name: ix_rule_violation_challenge_purchase_id; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_rule_violation_challenge_purchase_id ON public.rule_violation USING btree (challenge_purchase_id);


--
-- Name: ix_rule_violation_is_hard_fail; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_rule_violation_is_hard_fail ON public.rule_violation USING btree (is_hard_fail);


--
-- Name: ix_rule_violation_rule_name; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_rule_violation_rule_name ON public.rule_violation USING btree (rule_name);


--
-- Name: ix_rule_violation_severity; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_rule_violation_severity ON public.rule_violation USING btree (severity);


--
-- Name: ix_rule_violation_violated_at; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_rule_violation_violated_at ON public.rule_violation USING btree (violated_at);


--
-- Name: ix_support_ticket_assigned_to; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_support_ticket_assigned_to ON public.support_ticket USING btree (assigned_to);


--
-- Name: ix_support_ticket_created_at; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_support_ticket_created_at ON public.support_ticket USING btree (created_at);


--
-- Name: ix_support_ticket_priority; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_support_ticket_priority ON public.support_ticket USING btree (priority);


--
-- Name: ix_support_ticket_resolved_at; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_support_ticket_resolved_at ON public.support_ticket USING btree (resolved_at);


--
-- Name: ix_support_ticket_status; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_support_ticket_status ON public.support_ticket USING btree (status);


--
-- Name: ix_support_ticket_user_id; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_support_ticket_user_id ON public.support_ticket USING btree (user_id);


--
-- Name: ix_ticket_message_ticket_id; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_ticket_message_ticket_id ON public.ticket_message USING btree (ticket_id);


--
-- Name: ix_trade_challenge_purchase_id; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_trade_challenge_purchase_id ON public.trade USING btree (challenge_purchase_id);


--
-- Name: ix_trade_close_time; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_trade_close_time ON public.trade USING btree (close_time);


--
-- Name: ix_trade_created_at; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_trade_created_at ON public.trade USING btree (created_at);


--
-- Name: ix_trade_open_time; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_trade_open_time ON public.trade USING btree (open_time);


--
-- Name: ix_trade_status; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_trade_status ON public.trade USING btree (status);


--
-- Name: ix_trade_symbol; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_trade_symbol ON public.trade USING btree (symbol);


--
-- Name: ix_trade_trade_id; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE UNIQUE INDEX ix_trade_trade_id ON public.trade USING btree (trade_id);


--
-- Name: ix_user_country; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_user_country ON public."user" USING btree (country);


--
-- Name: ix_user_created_at; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_user_created_at ON public."user" USING btree (created_at);


--
-- Name: ix_user_email; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE UNIQUE INDEX ix_user_email ON public."user" USING btree (email);


--
-- Name: ix_user_email_verification_token; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_user_email_verification_token ON public."user" USING btree (email_verification_token);


--
-- Name: ix_user_email_verified; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_user_email_verified ON public."user" USING btree (email_verified);


--
-- Name: ix_user_first_name; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_user_first_name ON public."user" USING btree (first_name);


--
-- Name: ix_user_is_admin; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_user_is_admin ON public."user" USING btree (is_admin);


--
-- Name: ix_user_is_banned; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_user_is_banned ON public."user" USING btree (is_banned);


--
-- Name: ix_user_kyc_status; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_user_kyc_status ON public."user" USING btree (kyc_status);


--
-- Name: ix_user_last_name; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_user_last_name ON public."user" USING btree (last_name);


--
-- Name: ix_user_phone; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_user_phone ON public."user" USING btree (phone);


--
-- Name: ix_user_phone_verified; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_user_phone_verified ON public."user" USING btree (phone_verified);


--
-- Name: ix_waitlist_leads_email; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_waitlist_leads_email ON public.waitlist_leads USING btree (email);


--
-- Name: ix_waitlist_leads_status; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_waitlist_leads_status ON public.waitlist_leads USING btree (status);


--
-- Name: ix_webhook_log_created_at; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_webhook_log_created_at ON public.webhook_log USING btree (created_at);


--
-- Name: ix_webhook_log_event_type; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_webhook_log_event_type ON public.webhook_log USING btree (event_type);


--
-- Name: ix_webhook_log_order_id; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_webhook_log_order_id ON public.webhook_log USING btree (order_id);


--
-- Name: ix_webhook_log_status; Type: INDEX; Schema: public; Owner: tragene_user
--

CREATE INDEX ix_webhook_log_status ON public.webhook_log USING btree (status);


--
-- Name: account_snapshot account_snapshot_challenge_purchase_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.account_snapshot
    ADD CONSTRAINT account_snapshot_challenge_purchase_id_fkey FOREIGN KEY (challenge_purchase_id) REFERENCES public.challenge_purchase(id);


--
-- Name: admin_log admin_log_admin_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.admin_log
    ADD CONSTRAINT admin_log_admin_id_fkey FOREIGN KEY (admin_id) REFERENCES public."user"(id);


--
-- Name: challenge_purchase challenge_purchase_challenge_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.challenge_purchase
    ADD CONSTRAINT challenge_purchase_challenge_template_id_fkey FOREIGN KEY (challenge_template_id) REFERENCES public.challenge_template(id);


--
-- Name: challenge_purchase challenge_purchase_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.challenge_purchase
    ADD CONSTRAINT challenge_purchase_user_id_fkey FOREIGN KEY (user_id) REFERENCES public."user"(id);


--
-- Name: daily_snapshot daily_snapshot_challenge_purchase_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.daily_snapshot
    ADD CONSTRAINT daily_snapshot_challenge_purchase_id_fkey FOREIGN KEY (challenge_purchase_id) REFERENCES public.challenge_purchase(id);


--
-- Name: ea_trade ea_trade_challenge_purchase_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.ea_trade
    ADD CONSTRAINT ea_trade_challenge_purchase_id_fkey FOREIGN KEY (challenge_purchase_id) REFERENCES public.challenge_purchase(id);


--
-- Name: notification notification_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_user_id_fkey FOREIGN KEY (user_id) REFERENCES public."user"(id);


--
-- Name: payment payment_challenge_purchase_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.payment
    ADD CONSTRAINT payment_challenge_purchase_id_fkey FOREIGN KEY (challenge_purchase_id) REFERENCES public.challenge_purchase(id);


--
-- Name: payment payment_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.payment
    ADD CONSTRAINT payment_user_id_fkey FOREIGN KEY (user_id) REFERENCES public."user"(id);


--
-- Name: payout payout_challenge_purchase_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.payout
    ADD CONSTRAINT payout_challenge_purchase_id_fkey FOREIGN KEY (challenge_purchase_id) REFERENCES public.challenge_purchase(id);


--
-- Name: payout payout_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.payout
    ADD CONSTRAINT payout_user_id_fkey FOREIGN KEY (user_id) REFERENCES public."user"(id);


--
-- Name: rule_violation rule_violation_challenge_purchase_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.rule_violation
    ADD CONSTRAINT rule_violation_challenge_purchase_id_fkey FOREIGN KEY (challenge_purchase_id) REFERENCES public.challenge_purchase(id);


--
-- Name: rule_violation rule_violation_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.rule_violation
    ADD CONSTRAINT rule_violation_snapshot_id_fkey FOREIGN KEY (snapshot_id) REFERENCES public.account_snapshot(id);


--
-- Name: support_ticket support_ticket_assigned_to_fkey; Type: FK CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.support_ticket
    ADD CONSTRAINT support_ticket_assigned_to_fkey FOREIGN KEY (assigned_to) REFERENCES public."user"(id);


--
-- Name: support_ticket support_ticket_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.support_ticket
    ADD CONSTRAINT support_ticket_user_id_fkey FOREIGN KEY (user_id) REFERENCES public."user"(id);


--
-- Name: ticket_message ticket_message_sender_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.ticket_message
    ADD CONSTRAINT ticket_message_sender_id_fkey FOREIGN KEY (sender_id) REFERENCES public."user"(id);


--
-- Name: ticket_message ticket_message_ticket_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.ticket_message
    ADD CONSTRAINT ticket_message_ticket_id_fkey FOREIGN KEY (ticket_id) REFERENCES public.support_ticket(id);


--
-- Name: trade trade_challenge_purchase_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: tragene_user
--

ALTER TABLE ONLY public.trade
    ADD CONSTRAINT trade_challenge_purchase_id_fkey FOREIGN KEY (challenge_purchase_id) REFERENCES public.challenge_purchase(id);


--
-- PostgreSQL database dump complete
--

\unrestrict 0IOUdwOcBKUH0eNr6E3F4xGGCzQfbVV8CJ2uTDjiuUdmUJ8QaweairMKoB88Wu5

