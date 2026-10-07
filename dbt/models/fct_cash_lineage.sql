with joined as (
 select p.brand,p.allocation,p.cents,p.occurred as payment_at,p.invoice,
 i.cents as invoice_cents,i.occurred as invoice_at,i.fulfillment,
 j.opportunity,j.completed,j.occurred as fulfillment_at,o.account,o.stage,o.occurred as opportunity_at,
 a.account as known_account,t.event_id as touch_id,coalesce(t.campaign,'unattributed') as campaign,
 row_number() over(partition by p.brand,p.allocation order by t.occurred,t.event_id) as touch_rank
 from {{ ref('stg_events') }} p
 left join {{ ref('stg_events') }} i on p.brand=i.brand and p.invoice=i.invoice and i.kind='invoice'
 left join {{ ref('fct_fulfillment') }} j on i.brand=j.brand and i.fulfillment=j.fulfillment
 left join {{ ref('fct_opportunity') }} o on j.brand=o.brand and j.opportunity=o.opportunity
 left join {{ ref('dim_account') }} a on o.brand=a.brand and o.account=a.account
 left join {{ ref('fct_touch') }} t on o.brand=t.brand and o.account=t.account
   and t.campaign<>'unattributed' and t.occurred<=o.occurred
 where p.kind='payment'
)
select * exclude(touch_rank) from joined where touch_rank=1

