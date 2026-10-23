select id as action_key, state, attempts, reserved, json_extract_string(payload,'$.person') as person,
json_extract_string(payload,'$.brand') as brand, json_extract_string(payload,'$.journey') as journey
from raw.actions
