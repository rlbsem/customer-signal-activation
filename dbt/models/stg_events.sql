select brand, event_id, kind, occurred,
 json_extract_string(body, '$.data.account') as account,
 json_extract_string(body, '$.data.session') as session,
 json_extract_string(body, '$.data.campaign') as campaign,
 json_extract_string(body, '$.data.opportunity') as opportunity,
 json_extract_string(body, '$.data.fulfillment') as fulfillment,
 json_extract_string(body, '$.data.invoice') as invoice,
 json_extract_string(body, '$.data.allocation') as allocation,
 json_extract_string(body, '$.data.stage') as stage,
 cast(json_extract(body, '$.data.completed') as boolean) as completed,
 cast(json_extract(body, '$.data.cents') as bigint) as cents,
 cast(json_extract(body, '$.data.revision') as bigint) as revision
from {{ source('raw', 'events') }}

