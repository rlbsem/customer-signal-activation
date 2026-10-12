select id as run_id,
       json_extract_string(body,'$.snapshot.brand') as brand,
       json_extract_string(body,'$.snapshot.account') as account,
       json_extract_string(body,'$.configuration.mode') as mode,
       json_extract_string(body,'$.configuration.model') as model,
       json_extract_string(body,'$.status') as status,
       cast(json_extract(body,'$.created_at') as bigint) as created_at,
       cast(json_extract(body,'$.inference.latency_seconds') as double) as latency_seconds,
       coalesce(cast(json_extract(body,'$.inference.usage.total_tokens') as bigint),0) as total_tokens
from {{ source('seller_raw','runs') }}
