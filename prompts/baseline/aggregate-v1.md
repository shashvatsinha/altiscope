---
stage: aggregate
version: baseline-v1
schema_version: 4
---
Summarize the supplied reports for the requested reader altitude. Return a concise
headline, narrative, and sections in the requested JSON schema. Use only the supplied
reports. Do not invent facts, counts, outcomes, or unavailable context. Describe work,
never people. The application records every input report and source link separately;
do not add citations, source lists, coverage scores, or numeric confidence.

If asked to repair malformed output, return a complete replacement summary.
