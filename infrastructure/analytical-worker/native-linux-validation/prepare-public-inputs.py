"""Prepare partition-preserving public files from existing local candidate graphs.

Run on the trusted contributor host. No source, S3, publication or credentials.
This is preparation evidence; candidate graphs are not publication receipts.
"""

import argparse
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from outage_explorer.domain.datasets import PUBLIC_DATASETS
from outage_explorer.infrastructure.parquet.schemas import (
    modeled_from_record,
    schema_for,
)

MANIFEST_BYTES = 1_048_576
FILE_BYTES = 16_777_216
SNAPSHOT_BYTES = 2_147_483_647
SNAPSHOT_FILES = 10_000
PARTITION_ROWS = 100_000


def prepare(manifest_path, target):
    if manifest_path.is_symlink() or any(p.is_symlink() for p in manifest_path.parents):
        raise ValueError("Unsafe manifest path")
    with manifest_path.open("rb") as source:
        raw = source.read(MANIFEST_BYTES + 1)
    if len(raw) > MANIFEST_BYTES:
        raise ValueError("Manifest preparation bound exceeded")
    if hashlib.sha256(raw).hexdigest() != manifest_path.name:
        raise ValueError("Manifest digest mismatch")
    manifest = json.loads(raw)
    if manifest["outcome"] != "candidate":
        raise ValueError("Candidate graph required")
    refs_all = manifest["modeled"]
    if not isinstance(refs_all, list) or not 1 <= len(refs_all) <= SNAPSHOT_FILES:
        raise ValueError("Modeled file preparation bound exceeded")
    total = 0
    snapshot, coverage = {}, {}
    for dataset in PUBLIC_DATASETS:
        refs = [r for r in manifest["modeled"] if r["grain"] == dataset.grain]
        if not refs:
            raise ValueError("Missing grain")
        descriptors, dates, identities = [], set(), set()
        schema = schema_for("modeled", dataset.grain)
        public_schema = pa.schema([schema.field(c.name) for c in dataset.columns])
        keys = set()
        for index, ref in enumerate(refs):
            source = manifest_path.parent / ref["object"]["sha256"]
            if len(source.name) != 64 or any(
                c not in "0123456789abcdef" for c in source.name
            ):
                raise ValueError("Invalid modeled digest")
            if (
                source.is_symlink()
                or ref["kind"] != "modeled"
                or ref["schema_version"] != "1"
            ):
                raise ValueError("Unsafe modeled object")
            with source.open("rb") as stream:
                payload = stream.read(FILE_BYTES + 1)
            total += len(payload)
            if len(payload) > FILE_BYTES or total > SNAPSHOT_BYTES:
                raise ValueError("Modeled byte preparation bound exceeded")
            if (
                len(payload) != ref["object"]["byte_count"]
                or hashlib.sha256(payload).hexdigest() != source.name
            ):
                raise ValueError("Modeled digest/size mismatch")
            parquet = pq.ParquetFile(source)
            if not 0 < parquet.metadata.num_rows <= PARTITION_ROWS:
                raise ValueError("Modeled partition row bound exceeded")
            table = parquet.read()
            if (
                not table.schema.equals(schema, check_metadata=False)
                or table.num_rows != ref["row_count"]
            ):
                raise ValueError("Modeled schema/row mismatch")
            records = []
            for record in table.to_pylist():
                row = modeled_from_record(record, dataset.grain)
                day, identity = (
                    row.observation.day.isoformat(),
                    row.observation.identity,
                )
                if day != ref["partition"] or (day, identity) in keys:
                    raise ValueError("Duplicate/misplaced modeled key")
                keys.add((day, identity))
                dates.add(day)
                identities.add(identity)
                records.append({c.name: record[c.name] for c in dataset.columns})
            path = target / f"{dataset.id}-{index:04d}.parquet"
            pq.write_table(pa.Table.from_pylist(records, schema=public_schema), path)
            path.chmod(0o400)
            projected = path.read_bytes()
            descriptors.append(
                {
                    "path": str(path),
                    "sha256": hashlib.sha256(projected).hexdigest(),
                    "byte_count": len(projected),
                    "rows": len(records),
                }
            )
        snapshot[dataset.id] = descriptors
        coverage[dataset.id] = {
            "files": len(descriptors),
            "rows": len(keys),
            "entities": len(identities),
            "days": len(dates),
            "first": min(dates),
            "last": max(dates),
            "public_bytes": sum(d["byte_count"] for d in descriptors),
        }
    return snapshot, {
        "generation_id": manifest["generation_id"],
        "manifest_sha256": manifest_path.name,
        "interval": manifest["interval"],
        "coverage": coverage,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = args.output.absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("Unsafe output root")
    root.mkdir(mode=0o700)  # Exclusive: preserve incomplete preparation on failure.
    snapshots, evidence = (
        {},
        {
            "review_status": "unreviewed",
            "measurement_status": "not_run",
            "snapshots": {},
        },
    )
    for label in ("old", "current"):
        target = root / label
        target.mkdir(mode=0o700)
        snapshots[label], evidence["snapshots"][label] = prepare(
            getattr(args, label).absolute(), target
        )
    # Deliberately incomplete until independently authorized Linux PIDs/port exist.
    for name, document in (
        ("snapshots.json", snapshots),
        ("preparation.json", evidence),
    ):
        path = root / name
        path.write_text(json.dumps(document, indent=2) + "\n")
        path.chmod(0o600)
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    main()
