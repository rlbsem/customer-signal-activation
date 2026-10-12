with runs as (
  select mode,model,count(*) as generated_runs,
         count(*) filter(where status='review_required') as reviewable_runs,
         count(*) filter(where status='failed') as failed_runs,
         sum(total_tokens) as total_tokens,median(latency_seconds) as median_inference_seconds
  from {{ ref('fct_seller_runs') }} group by mode,model
), actions as (
  select r.mode,r.model,count(*) as approved_actions,
         count(*) filter(where a.edited) as edited_actions,
         count(*) filter(where a.state='delivered') as delivered_actions,
         sum(a.attempts) as delivery_attempts,
         median(a.approval_elapsed_seconds) as median_approval_elapsed_seconds
  from {{ ref('fct_seller_actions') }} a join {{ ref('fct_seller_runs') }} r using(run_id)
  group by r.mode,r.model
)
select r.*,coalesce(a.approved_actions,0) as approved_actions,
       coalesce(a.edited_actions,0) as edited_actions,
       coalesce(a.delivered_actions,0) as delivered_actions,
       coalesce(a.delivery_attempts,0) as delivery_attempts,
       a.median_approval_elapsed_seconds
from runs r left join actions a using(mode,model)
