with approval as (
  select subject, min(occurred) as approved_at,
         bool_or(cast(json_extract(body,'$.edited') as boolean)) as edited
  from {{ source('seller_raw','audit') }}
  where action='proposal_approved'
  group by subject
), delivery as (
  select subject,min(occurred) as delivered_at
  from {{ source('seller_raw','audit') }} where action='action_delivered' group by subject
)
select a.id as action_id,a.run_id,a.state,a.attempts,
       p.approved_at,p.edited,d.delivered_at,
       p.approved_at-r.created_at as approval_elapsed_seconds
from {{ source('seller_raw','actions') }} a
join {{ ref('fct_seller_runs') }} r on a.run_id=r.run_id
left join approval p on a.id=p.subject
left join delivery d on a.id=d.subject
