select a.experiment,a.arm,count(*) assigned,
 sum(case when a.eligibility='eligible' then 1 else 0 end) eligible,
 sum(e.approved) approved,sum(e.accepted) accepted,sum(o.converted) conversions,
 sum(case when o.mature=1 and o.coverage=1 then 1 else 0 end) mature_covered,
 sum(o.pipeline_cents) pipeline_cents
from {{ ref('fct_experiment_assignment') }} a
join {{ ref('fct_experiment_exposure') }} e on e.assignment_id=a.id
join {{ ref('fct_experiment_outcome') }} o on o.assignment_id=a.id
group by a.experiment,a.arm
