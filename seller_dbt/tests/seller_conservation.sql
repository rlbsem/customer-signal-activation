select 'run_count' as defect
where (select coalesce(sum(generated_runs),0) from {{ ref('mart_seller_workflow') }})
  <> (select count(*) from {{ source('seller_raw','runs') }})
union all
select 'action_count' where
  (select coalesce(sum(approved_actions),0) from {{ ref('mart_seller_workflow') }})
  <> (select count(*) from {{ source('seller_raw','actions') }})
union all
select 'token_count' where
  (select coalesce(sum(total_tokens),0) from {{ ref('mart_seller_workflow') }})
  <> (select coalesce(sum(total_tokens),0) from {{ ref('fct_seller_runs') }})
union all
select 'delivered_without_receipt' where exists(
  select 1 from {{ source('seller_raw','actions') }} where state='delivered' and receipt is null)
