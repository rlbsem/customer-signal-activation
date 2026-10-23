with action_receipts as (
 select a.id,a.enrollment,a.epoch,a.state,
 max(case when h.event='approved' then 1 else 0 end) approved,
 max(case when h.event='attempt' then 1 else 0 end) attempted,
 max(case when h.event='accepted' and json_extract_string(h.body,'$.accepted')='true' and json_extract_string(h.body,'$.id')=a.id
 and json_extract_string(h.body,'$.payload_hash')=sha256(a.payload) then 1 else 0 end) accepted
 from raw.actions a left join raw.history h on h.action=a.id and h."at" <= (select as_of from raw.experiment_clock)
 group by a.id,a.enrollment,a.epoch,a.state
)
select x.id as assignment_id,coalesce(max(a.approved),0) approved,coalesce(max(a.accepted),0) accepted,
 coalesce(max(case when a.attempted=1 and a.accepted=0 then 1 else 0 end),0) unresolved
from {{ ref('fct_experiment_assignment') }} x left join action_receipts a on a.enrollment=x.enrollment and a.epoch=x.epoch
group by x.id
