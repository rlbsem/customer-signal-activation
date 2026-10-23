select a.*,cast(json_extract_string(e.body,'$.window') as bigint) as window_seconds
from raw.experiment_assignment a join raw.experiment e on e.id=a.experiment
where a.assigned_at <= (select as_of from raw.experiment_clock)
