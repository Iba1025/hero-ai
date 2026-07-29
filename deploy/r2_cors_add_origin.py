"""Add an origin to the R2 bucket's CORS AllowedOrigins — ADD, never replace.

Phase 6 lean deploy (DEC-27/29): the pilot droplet serves at http://<ip>
until the domain lands; browser photo uploads (presigned PUT, BL-22) need
that origin in the bucket CORS. At the HTTPS flip the domain origin is added
the same way and the bare-IP origin removed deliberately (runbook step).

Reads R2_* from .env (same keys the app uses — INV-3 presign creds).

    uv run python deploy/r2_cors_add_origin.py http://134.122.44.90
"""

from __future__ import annotations

import sys

import boto3  # type: ignore[import-untyped]

from hero.config import get_settings


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].startswith("http"):
        print("usage: uv run python deploy/r2_cors_add_origin.py http://<ip-or-domain>")
        return 2
    origin = sys.argv[1].rstrip("/")

    settings = get_settings()
    if not (settings.r2_endpoint and settings.r2_access_key_id):
        print("R2_ENDPOINT / R2_ACCESS_KEY_ID missing from .env")
        return 2

    s3 = boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name=settings.r2_region,
    )

    try:
        rules = s3.get_bucket_cors(Bucket=settings.r2_bucket)["CORSRules"]
    except s3.exceptions.ClientError as exc:
        if "NoSuchCORSConfiguration" not in str(exc):
            raise
        rules = []

    print(f"current CORS rules on {settings.r2_bucket!r}:")
    for r in rules:
        print(f"  origins={r.get('AllowedOrigins')} methods={r.get('AllowedMethods')}")

    if any(origin in r.get("AllowedOrigins", []) for r in rules):
        print(f"{origin} already present — nothing to do")
        return 0

    if rules:
        # ADD to the first rule's origins (don't replace the rule set).
        rules[0]["AllowedOrigins"] = [*rules[0]["AllowedOrigins"], origin]
    else:
        rules = [
            {
                "AllowedOrigins": [origin],
                "AllowedMethods": ["PUT", "GET"],
                "AllowedHeaders": ["content-type"],
                "MaxAgeSeconds": 3600,
            }
        ]

    s3.put_bucket_cors(Bucket=settings.r2_bucket, CORSConfiguration={"CORSRules": rules})
    print(f"added {origin}; AllowedOrigins now: {rules[0]['AllowedOrigins']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
