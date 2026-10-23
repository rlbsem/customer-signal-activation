-- Neither holdouts nor competing treatment journeys may contain a verified effect.
select distinct x.id from {{ ref('fct_experiment_assignment') }} x
join raw.enrollment n on n.brand=x.brand and n.person=x.person
join raw.actions a on a.enrollment=n.id
join raw.history h on h.action=a.id
where (x.arm='holdout' or a.enrollment<>x.enrollment or a.epoch<>x.epoch)
and h.event='accepted' and h."at">=x.assigned_at and h."at"<=(select as_of from raw.experiment_clock)
and json_extract_string(h.body,'$.accepted')='true'
and json_extract_string(h.body,'$.id')=a.id
and json_extract_string(h.body,'$.payload_hash')=sha256(a.payload)
