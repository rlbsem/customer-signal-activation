select brand,account,event_id,occurred from {{ ref('stg_events') }} where kind='profile'
qualify row_number() over(partition by brand,account order by revision desc)=1

