-- Grand Line Shipping Company (fictional) operations warehouse.
-- Tables only: data is loaded by infra/warehouse/generate.py (deterministic seed).
-- All money is in USD; all timestamps are UTC.

create schema network;
create schema commercial;
create schema equipment;
create schema finance;
create schema operations;
create schema hr;

-- ── network ─────────────────────────────────────────────────────────────
create table network.trade_lanes (
    lane_code text primary key,
    name text not null
);

create table network.ports (
    port_code text primary key,          -- UN/LOCODE, e.g. NLRTM
    name text not null,
    country_code char(2) not null,
    country text not null,
    region text not null,
    latitude numeric(8, 4) not null,
    longitude numeric(8, 4) not null
);

create table network.vessels (
    vessel_id integer primary key,
    imo_number text not null unique,
    name text not null,
    vessel_class text not null,
    teu_capacity integer not null,
    reefer_plugs integer not null,
    built_year integer not null,
    flag text not null,
    fuel_type text not null,
    ownership text not null,             -- owned | chartered
    daily_charter_cost_usd numeric(10, 2),
    in_fleet_from date not null,
    in_fleet_to date
);

create table network.services (
    service_code text primary key,
    name text not null,
    lane_code text not null references network.trade_lanes,
    frequency_days integer not null,
    round_trip_days integer not null,
    nominal_vessel_teu integer not null
);

create table network.service_rotations (
    service_code text not null references network.services,
    direction text not null,             -- headhaul | backhaul
    seq integer not null,
    port_code text not null references network.ports,
    days_from_previous integer not null,
    primary key (service_code, direction, seq)
);

create table network.voyages (
    voyage_id integer primary key,
    voyage_number text not null unique,
    service_code text not null references network.services,
    vessel_id integer not null references network.vessels,
    direction text not null,
    routing text not null,               -- standard | cape_of_good_hope
    departure_date date not null,
    status text not null                 -- completed | in_progress | scheduled
);

create table network.port_calls (
    port_call_id integer primary key,
    voyage_id integer not null references network.voyages,
    seq integer not null,
    port_code text not null references network.ports,
    scheduled_arrival timestamptz not null,
    actual_arrival timestamptz,
    scheduled_departure timestamptz not null,
    actual_departure timestamptz,
    container_moves integer,
    unique (voyage_id, seq)
);

-- ── commercial ──────────────────────────────────────────────────────────
create table commercial.customers (
    customer_id integer primary key,
    name text not null,
    industry text not null,
    country text not null,
    segment text not null,               -- strategic | key | sme | spot
    credit_limit_usd numeric(14, 2) not null,
    payment_terms_days integer not null,
    account_manager_id integer,
    contact_name text,
    contact_email text,
    contact_phone text,
    created_date date not null
);

create table commercial.contracts (
    contract_id integer primary key,
    contract_number text not null unique,
    customer_id integer not null references commercial.customers,
    lane_code text not null references network.trade_lanes,
    contract_type text not null,         -- fixed | index_linked
    start_date date not null,
    end_date date not null,
    committed_teu integer not null,
    status text not null
);

create table commercial.rate_cards (
    rate_id integer primary key,
    contract_id integer not null references commercial.contracts,
    origin_port text not null references network.ports,
    destination_port text not null references network.ports,
    container_type text not null,
    base_rate_usd numeric(10, 2) not null,
    valid_from date not null,
    valid_to date not null
);

create table commercial.bookings (
    booking_id integer primary key,
    booking_number text not null unique,
    customer_id integer not null references commercial.customers,
    contract_id integer references commercial.contracts,
    voyage_id integer references network.voyages,
    service_code text not null references network.services,
    origin_port text not null references network.ports,
    destination_port text not null references network.ports,
    booking_date date not null,
    cargo_ready_date date not null,
    commodity text not null,
    incoterm text not null,
    is_reefer boolean not null,
    is_hazardous boolean not null,
    container_count integer not null,
    teu numeric(8, 1) not null,
    status text not null,                -- confirmed | shipped | delivered | cancelled
    rolled_count integer not null,
    freight_revenue_usd numeric(12, 2) not null
);

-- ── equipment ───────────────────────────────────────────────────────────
create table equipment.containers (
    container_number text primary key,   -- ISO 6346, owner code GLSU
    container_type text not null,
    built_year integer not null,
    ownership text not null,             -- owned | leased
    lessor text,
    status text not null
);

create table commercial.booking_containers (
    booking_id integer not null references commercial.bookings,
    container_number text not null references equipment.containers,
    container_type text not null,
    gross_weight_kg integer not null,
    seal_number text,
    vgm_submitted boolean not null,
    temperature_setpoint_c numeric(4, 1),
    primary key (booking_id, container_number)
);

create table equipment.tracking_events (
    event_id bigint primary key,
    container_number text not null references equipment.containers,
    booking_id integer not null references commercial.bookings,
    event_type text not null,
    event_time timestamptz not null,
    port_code text references network.ports,
    voyage_id integer references network.voyages
);

-- ── finance ─────────────────────────────────────────────────────────────
create table finance.invoices (
    invoice_id integer primary key,
    invoice_number text not null unique,
    booking_id integer not null references commercial.bookings,
    customer_id integer not null references commercial.customers,
    invoice_date date not null,
    due_date date not null,
    amount_usd numeric(12, 2) not null,
    status text not null,                -- paid | open | overdue | disputed | written_off
    paid_date date
);

create table finance.invoice_lines (
    invoice_id integer not null references finance.invoices,
    line_no integer not null,
    charge_code text not null,
    description text not null,
    amount_usd numeric(12, 2) not null,
    primary key (invoice_id, line_no)
);

create table finance.bunker_purchases (
    purchase_id integer primary key,
    vessel_id integer not null references network.vessels,
    port_code text not null references network.ports,
    purchase_date date not null,
    fuel_grade text not null,
    quantity_mt numeric(10, 1) not null,
    price_usd_per_mt numeric(8, 2) not null,
    supplier text not null
);

create table finance.claims (
    claim_id integer primary key,
    claim_number text not null unique,
    booking_id integer not null references commercial.bookings,
    customer_id integer not null references commercial.customers,
    claim_type text not null,
    filed_date date not null,
    claimed_amount_usd numeric(12, 2) not null,
    settled_amount_usd numeric(12, 2),
    status text not null,                -- open | settled | rejected
    settled_date date,
    root_cause text
);

-- ── operations ──────────────────────────────────────────────────────────
create table operations.delay_incidents (
    incident_id integer primary key,
    incident_number text not null unique,
    voyage_id integer not null references network.voyages,
    port_code text references network.ports,
    started_at timestamptz not null,
    delay_hours numeric(6, 1) not null,
    cause text not null,
    severity text not null,              -- minor | moderate | major | critical
    description text not null
);

create table operations.voyage_emissions (
    voyage_id integer primary key references network.voyages,
    distance_nm integer not null,
    avg_speed_knots numeric(4, 1) not null,
    fuel_consumed_mt numeric(10, 1) not null,
    co2_tonnes numeric(10, 1) not null,
    teu_carried integer not null,
    co2_grams_per_teu_km numeric(8, 2) not null,
    eu_ets_allowances numeric(10, 1) not null
);

create table operations.subcontractors (
    subcontractor_id integer primary key,
    name text not null,
    service_type text not null,          -- trucking | rail | depot | terminal
    country text not null,
    performance_rating numeric(3, 1) not null
);

create table operations.trucking_jobs (
    job_id integer primary key,
    booking_id integer not null references commercial.bookings,
    subcontractor_id integer not null references operations.subcontractors,
    leg text not null,                   -- pre_carriage | on_carriage
    port_code text not null references network.ports,
    inland_city text not null,
    distance_km integer not null,
    cost_usd numeric(10, 2) not null,
    scheduled_pickup timestamptz not null,
    actual_pickup timestamptz,
    status text not null
);

create table operations.warehouses (
    warehouse_id integer primary key,
    name text not null,
    city text not null,
    country text not null,
    capacity_pallets integer not null
);

create table operations.inventory_snapshots (
    snapshot_date date not null,
    warehouse_id integer not null references operations.warehouses,
    customer_id integer not null references commercial.customers,
    product_category text not null,
    pallets integer not null,
    stock_value_usd numeric(14, 2) not null,
    primary key (snapshot_date, warehouse_id, customer_id, product_category)
);

-- ── hr (restricted) ─────────────────────────────────────────────────────
create table hr.employees (
    employee_id integer primary key,
    full_name text not null,
    email text not null,
    department text not null,
    job_title text not null,
    office text not null,
    hire_date date not null,
    salary_usd numeric(10, 2) not null,
    manager_id integer,
    status text not null
);
