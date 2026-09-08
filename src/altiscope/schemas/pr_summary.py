"""Overall PR review output; the application supplies PR provenance."""

from pydantic import BaseModel, ConfigDict, Field

PR_SUMMARY_SCHEMA_VERSION = 3


class PrReviewOutput(BaseModel):
    """M1 v3: an overall code review; the application attaches PR provenance."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    review: str = Field(min_length=1, description="Overall review of the supplied PR code changes.")
