# Demo presentation refresh

[Initial verification](verification.json) · [Current verification](../ui-refresh-delivery/verification.json) · [Regression cases](tests.xml) · [Capture provenance](../../images/ui-refresh.json)

The actual intake and seller HTML/CSS use coordinated navy, slate and muted teal surfaces. The intake keeps the original consent controls and inquiry actions; the seller retains its rail, evidence columns, review controls and boundaries. The seller image is a genuine 1440 × 1269 viewport showing the approval/delivery receipt and the complete reviewed draft, about 37% shorter than the original 1440 × 2025 image. The existing receipt is rendered above the brief in the actual UI; questions and cautions remain below the viewport. The initial verification predates this receipt-position adjustment; its original record is retained.

Chromium operated real local APIs in fresh isolated capture workspaces: three permission-gated intake events and one approved task persisted to the local synthetic HTTP destination. The seller response and reviewer edit come unchanged from the preserved public application record. The UI labels recorded inference and an offline live model. No new model request, Salesforce request or existing runtime/database access was used for these captures. Desktop and 390px mobile checks found no page errors or document overflow.

Original images are retained byte-for-byte in [the presentation archive](../../images/archive/). The verifier's explicit `--presentation-refresh docs/images/ui-refresh.json` checks the historical hashes against those archived bytes and separately checks the new captures. It permits replacement only of the two named image paths; all other prior evidence remains pinned. No native acceptance record, Salesforce metadata, permission contract, data model or business test was changed. Native execution remains the historical acceptance recorded at commit `1e12470acc33ee7e3aa0835d3fc151e82a2ef41d`; this visual follow-up does not claim native re-execution.

To reproduce the captures without a model or Salesforce credentials:

```text
python scripts/capture_ui.py --workspace work/your-fresh-capture
```

The directory must be new. The script preserves the original archive and refreshes the new image hashes in the capture record. Run the verifier with a fresh evidence directory afterward. Historical test and execution records remain unchanged.
