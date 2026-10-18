WITH current_accounts AS (
    SELECT * FROM CSA_ACCOUNTS
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY source_ref ORDER BY source_modified_at DESC
    ) = 1
), current_reviews AS (
    SELECT * FROM CSA_REVIEWS
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY source_ref ORDER BY source_modified_at DESC
    ) = 1
), review_counts AS (
    SELECT account_source_ref,
        COUNT(*) AS review_count,
        SUM(CASE WHEN review_status = 'Pending' THEN 1 ELSE 0 END) AS pending_count,
        SUM(CASE WHEN review_status = 'Reviewed' THEN 1 ELSE 0 END) AS reviewed_count,
        SUM(CASE WHEN review_status = 'Rejected' THEN 1 ELSE 0 END) AS rejected_count
    FROM current_reviews GROUP BY account_source_ref
)
SELECT a.source_ref AS account_source_ref, a.source_modified_at,
    a.brand, a.account_key, a.owner_key, a.owner_ref, a.active, a.synthetic,
    COALESCE(r.review_count, 0) AS review_count,
    COALESCE(r.pending_count, 0) AS pending_count,
    COALESCE(r.reviewed_count, 0) AS reviewed_count,
    COALESCE(r.rejected_count, 0) AS rejected_count,
    CASE WHEN a.active AND a.synthetic
        AND COALESCE(r.pending_count, 0) = 0
        AND COALESCE(r.reviewed_count, 0) > 0
        THEN 'clarify_need' ELSE 'hold' END AS decision_action
FROM current_accounts a
LEFT JOIN review_counts r ON r.account_source_ref = a.source_ref
ORDER BY a.brand, a.account_key, a.source_ref
