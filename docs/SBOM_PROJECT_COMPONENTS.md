# Mixed-project SBOM topology anchors

Unified Project Manager can discover several project components inside one repository: for example a Node frontend, Python service, Rust engine, and Go utility. Aggregate dependency inventory alone does not make that project topology explicit.

UPM therefore emits deterministic **application anchors** in both CycloneDX 1.7 and SPDX 2.3.

## Goals

The anchor layer answers only project-topology questions:

- what aggregate project does this SBOM describe?;
- which discovered UPM components are inside it?;
- what ecosystem, manager, and relative path identifies each component?;
- can those identities remain stable when the same repository is cloned elsewhere?

It deliberately does **not** infer component-to-package dependency edges from generic normalized inventory. Native provider relationship evidence remains authoritative for dependency relationships.

## CycloneDX representation

The aggregate project is represented as `metadata.component` with `type = application`.

Each discovered UPM component is represented as a separate `type = application` entry in `components`.

Component anchors include UPM properties for:

- `upm:role = project-component`;
- `upm:component-key`;
- `upm:ecosystem`;
- `upm:manager` when known;
- `upm:path`.

The aggregate root has:

- `upm:role = aggregate-project-root`;
- `upm:component-count`.

The CycloneDX dependency table contains one topology edge from the aggregate root to each project-component anchor. That relation means the aggregate project contains/describes those components. It does **not** mean every dependency library belongs directly to the aggregate root.

UPM does not synthesize project-component → package edges merely from a lock observation. Those edges should be added only when a provider can support their meaning from authoritative native relationship evidence.

## SPDX representation

SPDX mirrors the same topology using packages with:

```text
primaryPackagePurpose = APPLICATION
```

UPM emits:

- one aggregate APPLICATION package;
- one APPLICATION package per discovered UPM component;
- aggregate `CONTAINS` component relationships;
- normal document `DESCRIBES` relationships.

Dependency libraries remain `LIBRARY` packages.

The SPDX document namespace is recomputed after application anchors and provider relationships are present.

## Stable identity

Application anchor refs are derived only from normalized relative project identity:

- component key;
- ecosystem;
- manager;
- sorted component membership for the aggregate root.

Absolute checkout paths are not part of the anchor digest.

The aggregate display name is also clone-independent:

- if exactly one root (`.`) component has a declared native project name, that name is used;
- otherwise the stable generic name `UPM aggregate project` is used.

This prevents two clones of the same mixed repository from receiving different anchor refs or SPDX namespaces merely because their parent directory names differ.

## Provider merge behavior

Provider-specific SBOM mergers must preserve existing application anchors and aggregate topology while adding package identity/relationships.

The local regression covers preservation through:

- Go native CycloneDX enrichment;
- aggregate provider CycloneDX construction;
- npm CycloneDX/SPDX merges;
- pnpm CycloneDX/SPDX merges;
- Yarn CycloneDX/SPDX merges;
- Poetry/PDM structured-lock CycloneDX/SPDX merges;
- a full static Poetry `build_native_cyclonedx` pipeline.

Application anchors do not carry registry PURLs, so PURL consistency checks continue to compare dependency package identity rather than project topology records.

## Advisory scanning boundary

Application anchors are not dependency packages.

Security planning and post-enrichment validation count only CycloneDX `type = library` components when deciding whether concrete dependency inventory exists. Therefore:

- an anchor-only project is still rejected as having no scan-ready dependency inventory;
- adding project topology does not inflate advisory package counts;
- a project with one dependency library still reports one dependency package even though application anchors are also present in the SBOM.

The exact SBOM—including application topology—is still retained and fingerprinted as advisory evidence when a scan runs.

## Local validation

Focused driver:

```sh
sh ./scripts/test-sbom-project-components.sh
```

The same regression is included in:

```sh
sh ./scripts/test-integration.sh
sh ./scripts/check-all-local-latest.sh
```

In the constrained implementation runtime, a reconstructed anchor slice passed **5/5** checks covering:

- clone-stable component/aggregate refs;
- clone-stable aggregate display naming;
- CycloneDX aggregate → project-component topology;
- SPDX `CONTAINS` hierarchy with clone-stable namespace;
- advisory counting that includes dependency libraries but excludes application anchors.

The committed full regression adds merge-preservation and native static-Poetry assertions for execution from a normal local checkout. The complete private branch is still not materialized in this runtime, so that full shell driver is not claimed as having run here.
