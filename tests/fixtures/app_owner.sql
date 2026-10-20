-- A small schema holding every dependency shape the read tier reports.
-- DISPOSABLE DATABASES ONLY: tests/live_check.py drops and recreates the
-- app_owner and reporting schemas.
drop schema if exists reporting cascade;
drop schema if exists app_owner cascade;
create schema app_owner;
create schema reporting;
set search_path = app_owner;

create sequence seq_order;

create table t_order (
  id      bigint primary key default nextval('seq_order'),
  status  text not null default 'DRAFT' check (status in ('DRAFT', 'PAID')),
  total   numeric(12, 2) not null default 0,
  created timestamptz not null default now()
);
comment on table t_order is 'Customer orders';
comment on column t_order.status is 'DRAFT until paid';
create index ix_order_status on t_order (status);

create table t_order_line (
  order_id bigint not null references t_order (id),
  line_no  int not null,
  amount   numeric(12, 2) not null,
  primary key (order_id, line_no)
);

create table t_order_audit (
  order_id bigint,
  changed  timestamptz default now()
);

-- tracked by the catalog: a view reads through its rewrite rule
create view v_order_total as
  select o.id, o.status, sum(l.amount) as lines_total
    from t_order o
    left join t_order_line l on l.order_id = o.id
   group by o.id, o.status;

-- tracked, and in another schema
create view reporting.v_sales as
  select status, count(*) as n from app_owner.t_order group by status;

-- NOT tracked: a PL/pgSQL body is only text to pg_depend
create function f_order_total(p_id bigint) returns numeric
language plpgsql as $$
declare
  v_total numeric;
begin
  select total into v_total from t_order where id = p_id;
  return coalesce(v_total, 0);
end;
$$;

create function f_order_paid(p_id bigint) returns boolean
language plpgsql as $$
begin
  return f_order_total(p_id) > 0;
end;
$$;

-- tracked: a SQL-standard body (PostgreSQL 14+) is parsed at CREATE
create function f_line_count(p_id bigint) returns bigint
language sql stable
begin atomic
  select count(*) from t_order_line where order_id = p_id;
end;

create function f_order_audit() returns trigger
language plpgsql as $$
begin
  insert into t_order_audit (order_id) values (new.id);
  return new;
end;
$$;

create trigger trg_order_audit after update on t_order
  for each row execute function f_order_audit();

-- compiles (PL/pgSQL is late-bound), fails at run time; plpgsql_check sees it
create function f_broken() returns bigint
language plpgsql as $$
begin
  return (select count(*) from t_gone);
end;
$$;
