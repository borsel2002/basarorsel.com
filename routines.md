# Routine source of truth

The single JSON block below is the strict, versioned machine-readable log.
Each routine maps to a category and unique muscle-group identifiers.
Historical strength uses the union of Full Body, Leg, Core and Neck; historical
mobility uses Daily Mobility. This is a programmatic attribution, not evidence
that every listed muscle was exercised in every historical session.

`historical_before` is exclusive in Europe/Istanbul local date. From that date,
only logged routines count. Add sessions to `sessions` as objects with `when`
(YYYY-MM-DD or an ISO-8601 timestamp including UTC offset) and `routines` (names).
An exact timestamp match takes precedence over a date match. Multiple rows at
the same resolution union their routines. Unknown names fail the build. Future
unmatched sessions stay explicitly unmatched, never backfilled with history.
No future sessions have been invented. Example format (not an actual log):
`{"when":"YYYY-MM-DD","routines":["Leg","Core"]}`.

```json
{
  "version": 1,
  "timezone": "Europe/Istanbul",
  "historical_before": "2026-09-08",
  "routines": {
    "Full Body": {"category":"strength","muscles":["chest","back","shoulders","quads","hamstrings","glutes","core"]},
    "Leg": {"category":"strength","muscles":["quads","hamstrings","glutes","calves"]},
    "Core": {"category":"strength","muscles":["abdominals","obliques","lower-back"]},
    "Neck": {"category":"strength","muscles":["neck-flexors","neck-extensors","upper-traps"]},
    "Daily Mobility": {"category":"mobility","muscles":["hips","spine","shoulders","ankles","wrists","neck"]}
  },
  "historical": {"strength":["Full Body","Leg","Core","Neck"],"mobility":["Daily Mobility"]},
  "sessions": []
}
```

Counts mean sessions attributed to a muscle group, not sets, repetitions,
intensity, fatigue, or biometric load. Recent counts cover 28 calendar days
ending at the latest workout date in the snapshot, not the viewing date.
The FIT mind-and-body category is used as the mobility proxy (including yoga,
pilates, flexibility and generic fitness equipment); it is an inference and
not exercise-level detail. Sub-sport strength labels take precedence.
