# ADR-0007: Make reports useful and possible to check

Status: proposed; citation, assessment, and coverage rules replaced by
[ADR-0010](0010-pr-review-provenance.md) and [ADR-0011](0011-aggregate-report-provenance.md).

## Why

A summary can misstate code, overstate its effects, or leave out important context.
Readers need access to the original material, and the project needs evaluation on
real reports. More elaborate citation machinery does not by itself solve these problems.

## Parts that remain relevant

- Compute counts and other structured facts in code.
- Record which patches were excluded from model input and why.
- Ask the model to respect differences between the PR description and the code.
- Preserve prompts and generation history so changes can be investigated.
- Describe work without judging people.
- Evaluate accuracy and usefulness with people who understand the changes.

## Earlier proposal and corrections

The initial proposal required evidence links and second-model assessment for every
claim, plus a coverage score based on cited inputs. ADR-0010 replaced individual
claims with an overall PR review. ADR-0011 records all supplied reports directly and
removes coverage scores. Readers can inspect the reports and original PRs themselves.

Optional second-model assessment of an overall report remains future work, as does
reader feedback and using reported errors as regression examples. Neither is required
for the current generation workflow.

## Tradeoffs

LLMs summarize probabilistically. Format checks and source history make the software
usable and inspectable, but do not prove the text correct. Another model also costs
time and money and can share the first model's errors. Its benefit should be measured
before making it a routine requirement.

The planned real-PR evaluation will compare accuracy, usefulness, and total human
effort. The current synthetic demo cannot answer those questions.
