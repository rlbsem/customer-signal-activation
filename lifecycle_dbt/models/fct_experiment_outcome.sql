{{ config(materialized='incremental',unique_key='assignment_id',incremental_strategy='delete+insert') }}
with event_versions as (
 select *,row_number() over(partition by brand,source,event_id order by revision desc) rank
 from raw.events where observed <= (select as_of from raw.experiment_clock)
), conversions as (
 select * from event_versions where rank=1 and kind='conversion' and json_extract_string(body,'$.converted')='true'
), coverage_versions as (
 select *,row_number() over(partition by id order by revision desc) rank from raw.experiment_observation
 where observed <= (select as_of from raw.experiment_clock)
), value_versions as (
 select *,row_number() over(partition by id order by revision desc) rank from raw.experiment_value
 where observed <= (select as_of from raw.experiment_clock)
)
select a.id assignment_id,
 case when (select as_of from raw.experiment_clock)>=a.assigned_at+a.window_seconds then 1 else 0 end mature,
 case when exists(select 1 from coverage_versions c where c.rank=1 and c.brand=a.brand and c.person=a.person and c.after_time<=a.assigned_at and c.through_time>=a.assigned_at+a.window_seconds) then 1 else 0 end coverage,
 case when exists(select 1 from conversions e where e.brand=a.brand and e.person=a.person and e.effective>=a.assigned_at and e.effective<a.assigned_at+a.window_seconds) then 1 else 0 end converted,
 coalesce((select sum(v.cents) from value_versions v where v.rank=1 and v.brand=a.brand and v.person=a.person
 and exists(select 1 from conversions e where e.brand=v.brand and e.person=v.person and e.event_id=v.conversion_ref and e.effective>=a.assigned_at and e.effective<a.assigned_at+a.window_seconds)),0) pipeline_cents
from {{ ref('fct_experiment_assignment') }} a
