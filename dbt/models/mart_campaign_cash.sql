with cash as (
 select brand,campaign,count(*) as allocations,count(distinct account) as accounts,
 count(distinct fulfillment) as fulfillments,sum(cents) as cash_cents from {{ ref('fct_cash_lineage') }} group by 1,2
), invoices as (
 select brand,campaign,sum(invoice_cents) as linked_invoice_cents from (
 select distinct brand,campaign,invoice,invoice_cents from {{ ref('fct_cash_lineage') }}
 ) group by 1,2
)
select c.*,i.linked_invoice_cents from cash c join invoices i using(brand,campaign)

