select brand,journey,count(*) as actions,sum(attempts) as attempts,
 sum(case when state='accepted' then 1 else 0 end) accepted,
 sum(case when state='uncertain' then 1 else 0 end) unresolved,
 sum(case when state='cancelled' then 1 else 0 end) cancelled
from {{ ref('fct_lifecycle_action') }} group by brand,journey
