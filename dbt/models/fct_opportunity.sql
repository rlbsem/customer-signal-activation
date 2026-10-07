select brand,opportunity,account,stage,occurred from {{ ref('stg_events') }} where kind='opportunity'
qualify row_number() over(partition by brand,opportunity order by revision desc)=1

