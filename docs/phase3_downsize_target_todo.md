# Phase 3 Downsize Target Follow-Up

## Issue

When Phase 2 downgraded a risky `STOP` decision into `DOWNSIZE`, some rows had a current EC2 instance type but no `recommended_type`.

That made the row look like a downsize in the dashboard, but Phase 3 could not send it through the normal Groq validation path because the LLM validator requires a concrete target type.

## Current Patch

Phase 3 now fills the missing `recommended_type` with one size smaller than the current instance type before LLM validation.

Example:

```text
m5.large -> m5.medium
c5.xlarge -> c5.large
```

This allows downgraded `DOWNSIZE` rows to be checked by Groq instead of becoming deterministic "not evaluated" rows.

## TODO

Investigate whether the Groq response gives a sufficiently comprehensive explanation that ties the final recommendation back to the Phase 1 detection result and the Phase 2 guardrail result.

The review should check whether the response explains:

- why Phase 1 originally flagged the instance;
- why Phase 2 changed or retained the action;
- why the proposed smaller instance type is acceptable;
- whether dependency risk, blast radius, and write/log relationships were considered;
- whether the recommendation should remain automatic or require user review.
