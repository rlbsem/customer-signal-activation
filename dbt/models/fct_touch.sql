select e.brand,e.event_id,e.occurred,coalesce(nullif(e.campaign,''),'unattributed') as campaign,
 case when e.kind='call' then e.account else l.account end as account
from {{ ref('stg_events') }} e
left join {{ ref('stg_events') }} l on e.brand=l.brand and e.session=l.session and l.kind='link'
where e.kind in ('web','call')

