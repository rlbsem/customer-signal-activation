select 'allocation_grain' as reason from {{ ref('fct_cash_lineage') }} group by brand,allocation having count(*)<>1
union all
select 'cash_conservation' where
 (select coalesce(sum(cents),0) from {{ ref('stg_events') }} where kind='payment') <>
 (select coalesce(sum(cash_cents),0) from {{ ref('mart_campaign_cash') }})

