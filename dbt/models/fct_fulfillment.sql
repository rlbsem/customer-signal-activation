select brand,fulfillment,opportunity,completed,occurred from {{ ref('stg_events') }} where kind='fulfillment'
qualify row_number() over(partition by brand,fulfillment order by revision desc)=1

