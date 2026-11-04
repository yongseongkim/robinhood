"""Reject plaintext in the repository's flat SOPS credentials document.

This is a publication check; SOPS/KMS validates and decrypts the document at runtime.
"""
import argparse
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ENCRYPTED = re.compile(
    r"ENC\[AES256_GCM,data:[A-Za-z0-9+/=]+,iv:[A-Za-z0-9+/=]+,"
    r"tag:[A-Za-z0-9+/=]+,type:str\]"
)


def validate(text):
    payload, separator, metadata = text.partition("\nsops:\n")
    if not separator:
        raise ValueError("credentials.yaml must be a SOPS-encrypted YAML document.")
    fields = set()
    for line in payload.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, colon, value = line.partition(":")
        if (
            not colon
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
            or key in fields
            or not ENCRYPTED.fullmatch(value.strip())
        ):
            raise ValueError("Every credentials.yaml value must be SOPS ciphertext.")
        fields.add(key)
    if not fields:
        raise ValueError("credentials.yaml has no encrypted fields.")
    if not re.search(r"^    gcp_kms:\s*$", metadata, re.M):
        raise ValueError("The document must use the configured GCP KMS recipient.")
    if not re.search(r"^\s+(?:- )?resource_id: projects/\S+/cryptoKeys/\S+\s*$", metadata, re.M):
        raise ValueError("The document has no GCP KMS key resource.")
    mac = re.search(r"^    mac: (.+)$", metadata, re.M)
    if not mac or not ENCRYPTED.fullmatch(mac.group(1)):
        raise ValueError("The document must retain its encrypted SOPS MAC.")
    for recipient in ("kms", "azure_kv", "hc_vault", "age", "pgp", "huawei_kms", "key_groups"):
        match = re.search(rf"^    {recipient}:([^\n]*)$", metadata, re.M)
        if match and match.group(1).strip() != "[]":
            raise ValueError("Only GCP KMS recipients are configured for this repository.")
    return len(fields)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="Check the actual Git index")
    args = parser.parse_args()
    if args.staged:
        text = subprocess.check_output(
            ["git", "show", ":credentials.yaml"], cwd=ROOT, text=True
        )
    else:
        text = (ROOT / "credentials.yaml").read_text()
    try:
        count = validate(text)
    except ValueError as error:
        parser.exit(1, f"{error}\n")
    print(f"Validated {count} encrypted credential fields; no decryption performed.")


if __name__ == "__main__":
    main()
