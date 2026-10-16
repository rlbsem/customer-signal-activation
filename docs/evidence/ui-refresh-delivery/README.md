# Presentation verification with visible approval and delivery

[Executed local verification](verification.json) · [Regression cases](tests.xml) · [Capture provenance](../../images/ui-refresh.json) · [Seller capture](../../images/seller-brief.jpg)

The current real-UI screenshot includes “Approved actions: 1,” “Delivered tasks: 1,” the successful delivery banner, and the entire persisted-task receipt. The receipt states that approval and delivery reference the same content hash. The capture runner checks both counts, the receipt's actual action key and its complete bounds inside the viewport before exporting the image.

The existing receipt is rendered above the brief rather than below the questions. This changes presentation only. The 1440 × 1269 viewport still includes the complete reviewed draft and visible synthetic/local and recorded-inference disclosures. Questions and cautions remain in the running page below the crop. The recorded proposal/reviewer edit is preserved, and delivery is a real fresh local HTTP effect against a synthetic receiver. No fresh inference, Salesforce operation or existing runtime/database access is claimed.

The branch preserves current main's business logic, native acceptance records and documentation. Historical screenshots remain archived with their original hashes; the verifier checks both archived originals and current display images. The earlier [initial visual verification](../ui-refresh/verification.json) is retained as a historical record. This record supplies verification after moving the receipt and synchronizing current main.

GitHub CI runs the same complete regression suite through the archive-preserving verifier, placing generated CI evidence in `work/`. This keeps the published screenshot bytes and their capture hashes intact during verification and packaging. It uses no native credentials.
