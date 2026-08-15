# SPDX export model

UPM's first SPDX exporter targets **SPDX 2.3 JSON** deliberately. SPDX 3.x has a different object model; it is not treated as a version-string change over a 2.3 document.

The 2.3 exporter is implemented as a real SPDX document rather than a CycloneDX payload with renamed fields.

## Document identity

The document includes:

- `spdxVersion = SPDX-2.3`;
- `dataLicense = CC0-1.0`;
- `SPDXID = SPDXRef-DOCUMENT`;
- document name;
- a content-derived absolute document namespace;
- creation information with a UTC timestamp and UPM as the creating tool.

The namespace digest is derived from package/relationship content rather than the creation timestamp. With a fixed creation timestamp, repeated export of unchanged state is deterministic.

## Package records

Every concrete package observation is represented with the required 2.3 package assertions:

- SPDX package ID;
- name;
- version when known;
- `downloadLocation = NOASSERTION` unless UPM has a real download-location assertion;
- `filesAnalyzed = false`;
- `licenseConcluded = NOASSERTION`;
- `licenseDeclared = NOASSERTION`;
- `copyrightText = NOASSERTION`.

UPM does not invent licenses, copyrights, or download URLs merely to make those fields look populated.

Registry package identities with trustworthy Package URLs receive an SPDX package-manager external reference with `referenceType = purl`.

Git/path/workspace/local packages do not receive fabricated registry PURLs.

## Relationships

The document emits explicit SPDX relationships:

- `SPDXRef-DOCUMENT DESCRIBES <package>` for represented packages;
- package `DEPENDS_ON` package when an authoritative provider establishes the relationship and both endpoint identities can be represented safely.

Provider semantics remain the same as the native graph layer:

- Go selected-module relationships may add selected module package identities;
- npm relationships are admitted only when package-lock state already established trustworthy package identity;
- Cargo relationships are admitted for registry packages backed by Cargo.lock identity;
- uv universal-lock relationships are admitted only for unambiguous registry package edges.

An ambiguous universal-lock fork is not converted into a guessed SPDX relationship.

## Why 2.3 first

SPDX 3.x introduces a substantially different model and vocabulary. A correct 3.x exporter should be designed against that object graph directly.

UPM therefore prefers one real 2.3 implementation over claiming 2.3/3.x support through a shallow translation layer.

## Scope

The SPDX document describes dependency/package inventory. It does not currently claim:

- file-level SPDX analysis;
- discovered source-file licenses;
- build artifact provenance;
- vulnerability exploitability;
- runtime reachability;
- source symbol relationships.

Those require stronger evidence sources and should be added as explicit model layers rather than inferred from dependency metadata.
