-- Acme retail "enterprise warehouse" (demo data for Phase 4 text-to-SQL).
-- Schema `sales` is queryable; schema `hr` exists to prove access is denied.

create schema sales;
create schema hr;

create table sales.regions (
    region_id   integer primary key,
    name        text not null,
    country     text not null
);

create table sales.customers (
    customer_id integer primary key,
    name        text not null,
    email       text not null,
    phone       text not null,
    region_id   integer not null references sales.regions (region_id),
    segment     text not null check (segment in ('consumer', 'smb', 'enterprise')),
    signup_date date not null
);

create table sales.products (
    product_id  integer primary key,
    name        text not null,
    category    text not null,
    unit_price  numeric(10, 2) not null
);

create table sales.orders (
    order_id    integer primary key,
    customer_id integer not null references sales.customers (customer_id),
    order_date  date not null,
    status      text not null check (status in ('completed', 'cancelled', 'refunded', 'processing')),
    channel     text not null check (channel in ('web', 'store', 'partner'))
);

create table sales.order_items (
    order_id    integer not null references sales.orders (order_id),
    product_id  integer not null references sales.products (product_id),
    quantity    integer not null check (quantity > 0),
    unit_price  numeric(10, 2) not null,
    primary key (order_id, product_id)
);

create table sales.shipments (
    shipment_id   integer primary key,
    order_id      integer not null unique references sales.orders (order_id),
    method        text not null check (method in ('standard', 'express')),
    promised_days integer not null,
    shipped_at    timestamptz not null,
    delivered_at  timestamptz
);

create table sales.returns (
    return_id     integer primary key,
    order_id      integer not null references sales.orders (order_id),
    product_id    integer not null references sales.products (product_id),
    reason        text not null,
    refund_amount numeric(10, 2) not null,
    returned_at   date not null
);

create table hr.salaries (
    employee_id integer primary key,
    department  text not null,
    title       text not null,
    salary      numeric(12, 2) not null
);

create index orders_date_idx on sales.orders (order_date);
create index orders_customer_idx on sales.orders (customer_id);
create index items_product_idx on sales.order_items (product_id);
