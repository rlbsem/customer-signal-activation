-- One row per assigned person; distinct assignment keys prevent source-join fanout.
select x.experiment from {{ ref('fct_experiment_assignment') }} x
left join {{ ref('fct_experiment_outcome') }} o on o.assignment_id=x.id
left join {{ ref('fct_experiment_exposure') }} e on e.assignment_id=x.id
group by x.experiment
having count(*) <> count(distinct x.id) or count(o.assignment_id) <> count(*) or count(e.assignment_id) <> count(*)
