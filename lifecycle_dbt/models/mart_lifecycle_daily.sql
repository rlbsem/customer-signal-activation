with enrollment as (
 select brand,journey,cast(to_timestamp(due) as date) cohort_day,count(*) enrollments
 from raw.enrollment group by brand,journey,cohort_day
), transitions as (
 select e.brand,e.journey,cast(to_timestamp(e.due) as date) cohort_day,count(*) transitions
 from {{ ref('fct_lifecycle_transition') }} t
 join raw.actions a on t.action=a.id join raw.enrollment e on a.enrollment=e.id
 group by e.brand,e.journey,cohort_day
)
select e.*,coalesce(t.transitions,0) transitions from enrollment e
left join transitions t using(brand,journey,cohort_day)
