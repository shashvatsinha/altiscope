"""Immutable, executable recipe versions for M3 comparisons."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from altiscope import __version__
from altiscope.llm.registry import (
    Capability,
    ModelSpec,
    ModelVersionKind,
    ProviderKind,
    ProviderSpec,
    Registry,
    StructuredOutputMode,
)
from altiscope.llm.types import Effort, Stage
from altiscope.prompts import Prompt
from altiscope.schemas.aggregate import AGGREGATE_SCHEMA_VERSION, AggregateOutput
from altiscope.schemas.pr_summary import PR_SUMMARY_SCHEMA_VERSION, PrReviewOutput
from altiscope.schemas.verify import ASSESSMENT_SCHEMA_VERSION, AssessmentOutput

CONFIGURATION_FORMAT_VERSION = 1
IDENTITY_POLICY_VERSION = "underlying-model-v1"
VALIDATOR_VERSION = "pydantic-v2-altiscope-v1"
TOKEN_ESTIMATOR_VERSION = "chars-div-4-v1"
PROMPT_PARSER_VERSION = "front-matter-v1"

_DEFAULT_ENDPOINTS: dict[ProviderKind, str] = {
    "anthropic": "https://api.anthropic.com",
    "openai_compatible": "https://api.openai.com/v1",
}
_EFFECTIVE_EFFORT: dict[Effort, Effort] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "high",
    "max": "high",
}


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


class RecipeOverrides(BaseModel):
    """Supported per-recipe settings; absent values use the registry stage settings."""

    model_config = ConfigDict(extra="forbid")

    effort: Effort | None = None
    reserved_output_tokens: int | None = Field(default=None, gt=0)
    input_budget_fraction: float | None = Field(default=None, gt=0, le=1)
    repair_limit: int = Field(default=1, ge=0, le=1)


class FrozenProvider(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    kind: ProviderKind
    adapter_version: str
    endpoint: str
    credential_reference: str | None
    timeout_seconds: float
    transport_retry_limit: int
    endpoint_options: dict[str, str]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    registry_key: str
    wire_name: str
    display_name: str
    underlying_model_id: str | None
    underlying_model_evidence: str
    identity_policy_version: str
    version_kind: ModelVersionKind
    capabilities: tuple[Capability, ...]
    output_mode: StructuredOutputMode
    context_window: int
    max_output_tokens: int


class FrozenGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_effort: Effort
    effective_effort: Effort | Literal["provider_default"]
    reserved_output_tokens: int
    wire_token_parameter: Literal["max_tokens", "max_completion_tokens"]
    sampling: Literal["provider_default"]
    seed: Literal["provider_default"]


class FrozenBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_budget_fraction: float
    input_limit: int
    token_estimator_version: str
    schema_envelope_allowance: int
    repair_limit: int
    repair_instruction_version: str


class FrozenOutputContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_id: str
    version: int
    schema_hash: str
    validator_version: str


class FrozenPricing(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    currency: Literal["USD"]
    input_usd_per_mtok: float = Field(ge=0)
    output_usd_per_mtok: float = Field(ge=0)
    cache_read_usd_per_mtok: float | None = Field(default=None, ge=0)
    cache_write_usd_per_mtok: float | None = Field(default=None, ge=0)
    units: Literal["per_million_tokens"]
    cache_token_treatment: Literal["separate_configured_rates", "ordinary_input_rate"]
    estimator_version: str
    status: Literal["configured_estimate", "unavailable"]
    provenance: Literal["model_registry"]


class FrozenInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    framework_version: str
    adapter_version: str
    prompt_parser_version: str
    source_format: str
    renderer_version: str
    input_policy_version: str
    facts_version: str


class FrozenExecutionConfig(BaseModel):
    """Complete configuration used to execute a recipe without a live registry lookup."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: int
    stage: Stage
    prompt_hash: str
    prompt_version: str
    prompt_source_path: str
    provider: FrozenProvider
    model: FrozenModel
    generation: FrozenGeneration
    budget: FrozenBudget
    output_contract: FrozenOutputContract
    pricing: FrozenPricing
    interpretation: FrozenInterpretation

    def to_registry(self) -> Registry:
        """Build a one-model registry exclusively from frozen recipe data."""
        provider = ProviderSpec(
            name=self.provider.name,
            kind=self.provider.kind,
            base_url=self.provider.endpoint,
            api_key_env=self.provider.credential_reference,
            timeout_seconds=self.provider.timeout_seconds,
        )
        model = ModelSpec(
            id=self.model.registry_key,
            provider=provider.name,
            model_name=self.model.wire_name,
            display_name=self.model.display_name,
            context_window=self.model.context_window,
            max_output_tokens=self.model.max_output_tokens,
            input_usd_per_mtok=self.pricing.input_usd_per_mtok,
            output_usd_per_mtok=self.pricing.output_usd_per_mtok,
            cache_read_usd_per_mtok=self.pricing.cache_read_usd_per_mtok,
            cache_write_usd_per_mtok=self.pricing.cache_write_usd_per_mtok,
            capabilities=set(self.model.capabilities),
            underlying_model_id=self.model.underlying_model_id,
            underlying_model_evidence=self.model.underlying_model_evidence,
            model_version_kind=self.model.version_kind,
        )
        stages = {
            stage: {
                "candidates": [model.id],
                "effort": self.generation.requested_effort,
                "reserved_output_tokens": self.generation.reserved_output_tokens,
            }
            for stage in ("pr_summary", "aggregate", "verify")
        }
        return Registry.model_validate(
            {
                "providers": {provider.name: provider.model_dump()},
                "models": {model.id: model.model_dump()},
                "input_budget_fraction": self.budget.input_budget_fraction,
                "stages": stages,
            }
        )


@dataclass(frozen=True)
class SchemaRegistration:
    stage: Stage
    contract_id: str
    version: int
    output_type: type[BaseModel]


@dataclass(frozen=True)
class RecipeVersion:
    id: UUID
    name: str
    version: int
    stage: Stage
    prompt_id: int
    schema_id: UUID
    config: FrozenExecutionConfig
    configuration_hash: str
    prompt: Prompt
    output_type: type[BaseModel]


_SCHEMAS: dict[tuple[Stage, int], SchemaRegistration] = {
    ("pr_summary", PR_SUMMARY_SCHEMA_VERSION): SchemaRegistration(
        "pr_summary", "altiscope.pr_review", PR_SUMMARY_SCHEMA_VERSION, PrReviewOutput
    ),
    ("aggregate", AGGREGATE_SCHEMA_VERSION): SchemaRegistration(
        "aggregate", "altiscope.aggregate", AGGREGATE_SCHEMA_VERSION, AggregateOutput
    ),
    ("verify", ASSESSMENT_SCHEMA_VERSION): SchemaRegistration(
        "verify",
        "altiscope.whole_result_assessment",
        ASSESSMENT_SCHEMA_VERSION,
        AssessmentOutput,
    ),
}


def registered_schema(stage: Stage, version: int) -> SchemaRegistration:
    try:
        return _SCHEMAS[(stage, version)]
    except KeyError as exc:
        raise ValueError(f"unsupported output schema for {stage}: version {version}") from exc


def register_schema(
    *, stage: Stage, contract_id: str, version: int, output_type: type[BaseModel]
) -> SchemaRegistration:
    """Register a new immutable application contract (used by future #45 schemas)."""
    if not contract_id.strip() or version <= 0:
        raise ValueError("schema registration requires a nonblank id and positive version")
    key = (stage, version)
    existing = _SCHEMAS.get(key)
    if existing is not None and (
        existing.contract_id != contract_id or existing.output_type is not output_type
    ):
        raise ValueError(f"schema {stage} v{version} is already registered with another contract")
    registration = existing or SchemaRegistration(stage, contract_id, version, output_type)
    _SCHEMAS[key] = registration
    return registration


def _endpoint(spec: ProviderSpec) -> str:
    endpoint = spec.base_url or _DEFAULT_ENDPOINTS[spec.kind]
    parsed = urlsplit(endpoint)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("provider endpoint must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("provider endpoint must not contain credentials, query, or fragment")
    return endpoint.rstrip("/")


def _resolved_config(
    *,
    registry: Registry,
    registry_key: str,
    prompt: Prompt,
    schema: SchemaRegistration,
    overrides: RecipeOverrides,
) -> FrozenExecutionConfig:
    if registry_key not in registry.models:
        raise ValueError(f"unknown model registry key: {registry_key}")
    model = registry.models[registry_key]
    provider = registry.provider_for(registry_key)
    stage_config = registry.stages[prompt.stage]
    output_mode = model.structured_output_mode
    if provider.kind == "anthropic" and output_mode != "native":
        raise ValueError("the Anthropic adapter supports only native structured output")
    requested_effort = overrides.effort or stage_config.effort
    reserved = overrides.reserved_output_tokens or stage_config.reserved_output_tokens
    if reserved > model.max_output_tokens:
        raise ValueError(
            f"recipe reserves {reserved} output tokens but {registry_key} allows "
            f"at most {model.max_output_tokens}"
        )
    fraction = overrides.input_budget_fraction or registry.input_budget_fraction
    input_limit = max(0, math.floor(model.context_window * fraction) - reserved)
    if input_limit <= 0:
        raise ValueError("recipe has no positive input budget after output reservation")
    effective_effort: Effort | Literal["provider_default"]
    if provider.kind == "anthropic":
        effective_effort = requested_effort
    elif "reasoning_effort" in model.capabilities:
        effective_effort = _EFFECTIVE_EFFORT[requested_effort]
    else:
        effective_effort = "provider_default"
    wire_parameter = (
        "max_completion_tokens"
        if provider.kind == "openai_compatible" and "reasoning_effort" in model.capabilities
        else "max_tokens"
    )
    schema_document = schema.output_type.model_json_schema()
    pricing_status: Literal["configured_estimate", "unavailable"] = (
        "configured_estimate"
        if model.input_usd_per_mtok > 0 or model.output_usd_per_mtok > 0
        else "unavailable"
    )
    return FrozenExecutionConfig(
        format_version=CONFIGURATION_FORMAT_VERSION,
        stage=prompt.stage,
        prompt_hash=prompt.content_hash,
        prompt_version=prompt.version,
        prompt_source_path=str(prompt.path),
        provider=FrozenProvider(
            name=provider.name,
            kind=provider.kind,
            adapter_version="1",
            endpoint=_endpoint(provider),
            credential_reference=provider.api_key_env,
            timeout_seconds=provider.timeout_seconds,
            transport_retry_limit=0,
            endpoint_options={},
        ),
        model=FrozenModel(
            registry_key=registry_key,
            wire_name=model.wire_name,
            display_name=model.display_name,
            underlying_model_id=model.underlying_model_id,
            underlying_model_evidence=model.underlying_model_evidence or "unknown",
            identity_policy_version=IDENTITY_POLICY_VERSION,
            version_kind=model.model_version_kind,
            capabilities=tuple(sorted(model.capabilities)),
            output_mode=output_mode,
            context_window=model.context_window,
            max_output_tokens=model.max_output_tokens,
        ),
        generation=FrozenGeneration(
            requested_effort=requested_effort,
            effective_effort=effective_effort,
            reserved_output_tokens=reserved,
            wire_token_parameter=wire_parameter,
            sampling="provider_default",
            seed="provider_default",
        ),
        budget=FrozenBudget(
            input_budget_fraction=fraction,
            input_limit=input_limit,
            token_estimator_version=TOKEN_ESTIMATOR_VERSION,
            schema_envelope_allowance=256,
            repair_limit=overrides.repair_limit,
            repair_instruction_version="validation-diagnostic-v1",
        ),
        output_contract=FrozenOutputContract(
            contract_id=schema.contract_id,
            version=schema.version,
            schema_hash=_hash_json(schema_document),
            validator_version=VALIDATOR_VERSION,
        ),
        pricing=FrozenPricing(
            currency="USD",
            input_usd_per_mtok=model.input_usd_per_mtok,
            output_usd_per_mtok=model.output_usd_per_mtok,
            cache_read_usd_per_mtok=model.cache_read_usd_per_mtok,
            cache_write_usd_per_mtok=model.cache_write_usd_per_mtok,
            units="per_million_tokens",
            cache_token_treatment="separate_configured_rates",
            estimator_version="configured-token-rates-v2",
            status=pricing_status,
            provenance="model_registry",
        ),
        interpretation=FrozenInterpretation(
            framework_version=__version__,
            adapter_version="1",
            prompt_parser_version=PROMPT_PARSER_VERSION,
            source_format="prepared-source-v1",
            renderer_version="current-v1",
            input_policy_version="current-v1",
            facts_version="current-v1",
        ),
    )


def _save_prompt(conn: psycopg.Connection, prompt: Prompt) -> int:
    row = conn.execute(
        "INSERT INTO prompt_versions(stage,name,content_hash,content,source_text) "
        "VALUES (%s,%s,%s,%s,%s) ON CONFLICT(stage,content_hash) DO NOTHING RETURNING id",
        (prompt.stage, prompt.version, prompt.content_hash, prompt.body, prompt.source_text),
    ).fetchone()
    if row is not None:
        return int(row[0])
    existing = conn.execute(
        "SELECT id,name,content,source_text FROM prompt_versions "
        "WHERE stage=%s AND content_hash=%s",
        (prompt.stage, prompt.content_hash),
    ).fetchone()
    if existing is None or existing[1:] != (prompt.version, prompt.body, prompt.source_text):
        raise ValueError("stored prompt content does not match its content hash")
    return int(existing[0])


def _save_schema(conn: psycopg.Connection, schema: SchemaRegistration) -> UUID:
    document = schema.output_type.model_json_schema()
    digest = _hash_json(document)
    schema_id = uuid4()
    row = conn.execute(
        "INSERT INTO output_schema_versions"
        "(id,stage,contract_id,version,schema_document,schema_hash,validator_version) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT(stage,contract_id,version) DO NOTHING RETURNING id",
        (
            schema_id,
            schema.stage,
            schema.contract_id,
            schema.version,
            Jsonb(document),
            digest,
            VALIDATOR_VERSION,
        ),
    ).fetchone()
    if row is not None:
        return UUID(str(row[0]))
    existing = conn.execute(
        "SELECT id,schema_hash,validator_version FROM output_schema_versions "
        "WHERE stage=%s AND contract_id=%s AND version=%s",
        (schema.stage, schema.contract_id, schema.version),
    ).fetchone()
    if existing is None or existing[1:] != (digest, VALIDATOR_VERSION):
        raise ValueError("registered output schema content or validator has changed")
    return UUID(str(existing[0]))


def create_recipe(
    conn: psycopg.Connection,
    *,
    name: str,
    registry_key: str,
    prompt: Prompt,
    registry: Registry,
    overrides: RecipeOverrides | None = None,
) -> RecipeVersion:
    """Append the next version of a named recipe in one transaction."""
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("recipe name must not be blank")
    if not prompt.body.strip() or not prompt.source_text.strip():
        raise ValueError("recipe prompt content must not be blank")
    schema = registered_schema(prompt.stage, prompt.schema_version)
    config = _resolved_config(
        registry=registry,
        registry_key=registry_key,
        prompt=prompt,
        schema=schema,
        overrides=overrides or RecipeOverrides(),
    )
    return _insert_recipe(conn, name=clean_name, prompt=prompt, schema=schema, config=config)


def _insert_recipe(
    conn: psycopg.Connection,
    *,
    name: str,
    prompt: Prompt,
    schema: SchemaRegistration,
    config: FrozenExecutionConfig,
) -> RecipeVersion:
    """Insert one already-resolved immutable recipe configuration."""
    configuration = config.model_dump(mode="json")
    digest = _hash_json(configuration)
    recipe_id = uuid4()
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (name,))
        prompt_id = _save_prompt(conn, prompt)
        schema_id = _save_schema(conn, schema)
        row = conn.execute(
            "SELECT COALESCE(max(version),0)+1 FROM recipe_versions WHERE name=%s",
            (name,),
        ).fetchone()
        assert row is not None
        version = int(row[0])
        conn.execute(
            "INSERT INTO recipe_versions"
            "(id,name,version,stage,prompt_version_id,output_schema_version_id,"
            "configuration_format_version,configuration,configuration_hash) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                recipe_id,
                name,
                version,
                prompt.stage,
                prompt_id,
                schema_id,
                CONFIGURATION_FORMAT_VERSION,
                Jsonb(configuration),
                digest,
            ),
        )
    return RecipeVersion(
        recipe_id,
        name,
        version,
        prompt.stage,
        prompt_id,
        schema_id,
        config,
        digest,
        prompt,
        schema.output_type,
    )


def create_recipe_variant(
    conn: psycopg.Connection,
    *,
    name: str,
    base: RecipeVersion,
    prompt: Prompt,
) -> RecipeVersion:
    """Create a prompt-only variant while preserving every other frozen setting."""
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("recipe name must not be blank")
    if not prompt.body.strip() or not prompt.source_text.strip():
        raise ValueError("recipe prompt content must not be blank")
    if prompt.stage != base.stage:
        raise ValueError("recipe variant prompt must match the base recipe stage")
    schema = registered_schema(prompt.stage, prompt.schema_version)
    if (
        schema.contract_id != base.config.output_contract.contract_id
        or schema.version != base.config.output_contract.version
    ):
        raise ValueError("recipe variant must preserve the base output contract")
    config = base.config.model_copy(
        update={
            "prompt_hash": prompt.content_hash,
            "prompt_version": prompt.version,
            "prompt_source_path": str(prompt.path),
        }
    )
    return _insert_recipe(conn, name=clean_name, prompt=prompt, schema=schema, config=config)


def load_recipe(
    conn: psycopg.Connection,
    recipe_id: UUID | str,
    *,
    require_executable: bool = True,
) -> RecipeVersion:
    row = conn.execute(
        "SELECT r.id,r.name,r.version,r.stage,r.prompt_version_id,r.output_schema_version_id,"
        "r.configuration,r.configuration_hash,p.name,p.content_hash,p.content,p.source_text,"
        "s.contract_id,s.version,s.schema_hash,s.validator_version,s.schema_document "
        "FROM recipe_versions r JOIN prompt_versions p ON p.id=r.prompt_version_id "
        "JOIN output_schema_versions s ON s.id=r.output_schema_version_id WHERE r.id=%s",
        (UUID(str(recipe_id)),),
    ).fetchone()
    if row is None:
        raise ValueError("recipe version not found")
    if _hash_json(row[6]) != row[7]:
        raise ValueError("stored recipe configuration hash mismatch")
    config = FrozenExecutionConfig.model_validate(row[6])
    if hashlib.sha256(str(row[11]).encode()).hexdigest() != row[9]:
        raise ValueError("stored recipe prompt hash mismatch")
    if config.prompt_hash != row[9] or config.prompt_version != row[8]:
        raise ValueError("stored recipe prompt identity differs from its frozen configuration")
    if _hash_json(row[16]) != row[14]:
        raise ValueError("stored output schema hash mismatch")
    if config.output_contract.schema_hash != row[14]:
        raise ValueError("stored recipe schema differs from its frozen configuration")
    stage: Stage = row[3]
    schema = registered_schema(stage, int(row[13]))
    if require_executable:
        if config.format_version != CONFIGURATION_FORMAT_VERSION:
            raise ValueError("recipe configuration format is not executable by this build")
        if row[15] != VALIDATOR_VERSION or schema.contract_id != row[12]:
            raise ValueError("recipe output validator is not supported by this build")
        if config.provider.adapter_version != "1":
            raise ValueError("recipe provider adapter is not supported by this build")
    prompt = Prompt(
        stage=stage,
        version=str(row[8]),
        schema_version=int(row[13]),
        content_hash=str(row[9]),
        body=str(row[10]),
        source_text=str(row[11]),
        path=Path(config.prompt_source_path),
    )
    return RecipeVersion(
        UUID(str(row[0])),
        str(row[1]),
        int(row[2]),
        stage,
        int(row[4]),
        UUID(str(row[5])),
        config,
        str(row[7]),
        prompt,
        schema.output_type,
    )


def load_recipe_version(
    conn: psycopg.Connection, name: str, version: int | None = None
) -> RecipeVersion:
    if version is None:
        row = conn.execute(
            "SELECT id FROM recipe_versions WHERE name=%s ORDER BY version DESC LIMIT 1",
            (name,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM recipe_versions WHERE name=%s AND version=%s", (name, version)
        ).fetchone()
    if row is None:
        raise ValueError("recipe version not found")
    return load_recipe(conn, UUID(str(row[0])))


def list_recipes(conn: psycopg.Connection) -> list[tuple[UUID, str, int, Stage, str]]:
    rows = conn.execute(
        "SELECT id,name,version,stage,configuration_hash FROM recipe_versions ORDER BY name,version"
    ).fetchall()
    return [(UUID(str(row[0])), str(row[1]), int(row[2]), row[3], str(row[4])) for row in rows]
