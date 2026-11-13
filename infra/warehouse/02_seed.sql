-- Deterministic seed: the same data on every machine (setseed + generate_series).
-- Orders span 2024-11-01 .. 2026-10-31 so "last quarter" / "this year" questions have answers.

select setseed(0.42);

insert into sales.regions (region_id, name, country) values
    (1, 'North America', 'United States'),
    (2, 'EMEA', 'Germany'),
    (3, 'UK & Ireland', 'United Kingdom'),
    (4, 'Nordics', 'Norway'),
    (5, 'APAC', 'Singapore');

insert into sales.customers (customer_id, name, email, phone, region_id, segment, signup_date)
select
    g,
    'Customer ' || g,
    'customer' || g || '@example.com',
    '+1-555-' || lpad((1000 + g)::text, 4, '0'),
    -- skewed: North America and EMEA are the biggest regions
    (array[1, 1, 1, 2, 2, 2, 3, 3, 4, 5])[1 + floor(random() * 10)::int],
    (array['consumer', 'consumer', 'consumer', 'smb', 'smb', 'enterprise'])[1 + floor(random() * 6)::int],
    date '2023-01-01' + floor(random() * 1000)::int
from generate_series(1, 2000) g;

insert into sales.products (product_id, name, category, unit_price)
select
    g,
    c.category || ' item ' || g,
    c.category,
    round((c.base * (0.5 + random()))::numeric, 2)
from generate_series(1, 200) g
cross join lateral (
    select (array['Laptops', 'Tablets', 'Headphones', 'Monitors', 'Accessories',
                  'Smart Home', 'Cameras', 'Printers'])[1 + (g % 8)] as category,
           (array[1200, 600, 180, 350, 40, 120, 700, 250])[1 + (g % 8)] as base
) c;

insert into sales.orders (order_id, customer_id, order_date, status, channel)
select
    g,
    1 + floor(random() * 2000)::int,
    -- more orders in recent months (growth) and in Nov/Dec (seasonality)
    (date '2024-11-01' + floor(power(random(), 0.8) * 730)::int),
    (array['completed', 'completed', 'completed', 'completed', 'completed', 'completed',
           'completed', 'cancelled', 'refunded', 'processing'])[1 + floor(random() * 10)::int],
    (array['web', 'web', 'web', 'store', 'store', 'partner'])[1 + floor(random() * 6)::int]
from generate_series(1, 40000) g;

-- Nov/Dec bump: duplicate a slice of orders into the holiday weeks
update sales.orders
set order_date = make_date(extract(year from order_date)::int, 12, 1 + (order_id % 24))
where order_id % 9 = 0 and extract(month from order_date) in (10, 11)
  and order_date < date '2026-01-01';  -- never move orders past the data's end date

insert into sales.order_items (order_id, product_id, quantity, unit_price)
select o.order_id, p.product_id, 1 + floor(random() * 3)::int, p.unit_price
from sales.orders o
cross join lateral (
    select distinct 1 + floor(random() * 200)::int as product_id
    from generate_series(1, 1 + (o.order_id % 3))
) pick
join sales.products p on p.product_id = pick.product_id;

insert into sales.shipments (shipment_id, order_id, method, promised_days, shipped_at, delivered_at)
select
    row_number() over (order by o.order_id),
    o.order_id,
    s.method,
    case s.method when 'express' then 1 else 5 end,
    o.order_date + interval '1 day' * (random() * 2) + interval '10 hours',
    o.order_date + interval '1 day' * (case s.method when 'express' then 1 + random() * 1.6
                                                 else 2 + random() * 5 end) + interval '14 hours'
from sales.orders o
cross join lateral (
    select case when random() < 0.25 then 'express' else 'standard' end as method
    where o.order_id > 0
) s
where o.status in ('completed', 'refunded');

insert into sales.returns (return_id, order_id, product_id, reason, refund_amount, returned_at)
select
    row_number() over (order by oi.order_id, oi.product_id),
    oi.order_id,
    oi.product_id,
    (array['Defective', 'Changed mind', 'Wrong item', 'Arrived late', 'Not as described'])
        [1 + floor(random() * 5)::int],
    round(oi.unit_price * oi.quantity, 2),
    o.order_date + 3 + floor(random() * 20)::int
from sales.order_items oi
join sales.orders o on o.order_id = oi.order_id
where o.status = 'refunded' or (o.status = 'completed' and random() < 0.04);

insert into hr.salaries (employee_id, department, title, salary)
select
    g,
    (array['Engineering', 'Sales', 'Support', 'Finance', 'Operations'])[1 + (g % 5)],
    (array['Associate', 'Senior', 'Lead', 'Manager'])[1 + (g % 4)],
    round((50000 + random() * 120000)::numeric, 2)
from generate_series(1, 300) g;

analyze;
