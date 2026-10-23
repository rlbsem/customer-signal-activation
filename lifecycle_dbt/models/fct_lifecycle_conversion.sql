{{ config(materialized='incremental',unique_key=['brand','event_id'],incremental_strategy='delete+insert') }}
with versions as (
select *, row_number() over(partition by brand,source,event_id order by revision desc) r
from raw.events where kind='conversion'
)
select brand,event_id,person,effective,revision,json_extract_string(body,'$.converted')='true' as converted
from versions where r=1
