select * from {{ ref('fct_cash_lineage') }}
where known_account is null or stage<>'won' or completed is not true
 or invoice_cents is null or cents<=0
 or not(opportunity_at<=fulfillment_at and fulfillment_at<=invoice_at and invoice_at<=payment_at)
union all
select * from {{ ref('fct_cash_lineage') }} where (brand,invoice) in (
 select brand,invoice from {{ ref('fct_cash_lineage') }} group by brand,invoice
 having sum(cents)>max(invoice_cents)
)

