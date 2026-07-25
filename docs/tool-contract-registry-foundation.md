# Tool Contract and Registry Foundation

Stage 8.1 extends the existing provider-neutral tool contracts with explicit
enablement and discovery. It does not add a tool-execution loop.

## Architecture

`BaseTool` declares a business capability through frozen `ToolMetadata` and
Pydantic input/output schemas. `ToolRegistry` stores tool classes, never tool
instances, and exposes deterministic discovery operations. Model providers,
FastAPI, SQLAlchemy, prompts, and transport formats are outside this boundary.

The registry answers **which tools exist?** It does not answer **run this
tool**. Execution remains a separate concern owned by the existing executor.

## Metadata and schemas

Metadata includes the tool's name, semantic version, description, category,
supported use cases, safety declarations, read-only declaration, and enabled
state. The metadata model is frozen. Input and output contracts are declared as
Pydantic model classes on each tool and are exposed as fresh JSON Schema
snapshots by `BaseTool.definition()`.

## Discovery

- `register()` rejects duplicate name/version pairs.
- `get()` supports exact name/version lookup and safe name-only lookup.
- Name-only lookup fails when several versions make the request ambiguous.
- `list_all()` and `list_enabled()` return deterministic immutable tuples.
- `metadata()` returns frozen metadata declarations.
- `definitions()` delegates schema generation to `BaseTool`; the registry does
  not duplicate that logic.

`PingTool` is a deterministic demonstration declaration. It proves that a
complete capability can be registered and described without connecting the
registry to a model, database, HTTP service, or provider.
