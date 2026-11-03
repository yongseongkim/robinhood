"""Publishing encrypted configuration must not also admit plaintext values."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_encrypted_credentials import validate


CIPHER = "ENC[AES256_GCM,data:YWJj,iv:YWJj,tag:YWJj,type:str]"
DOCUMENT = f"""assembly_api_key: {CIPHER}
openfiscal_api_key: {CIPHER}
sops:
    gcp_kms:
        - resource_id: projects/test/locations/test/keyRings/test/cryptoKeys/test
          enc: wrapped-key
    mac: {CIPHER}
    version: 3.9.0
"""


def test_encrypted_values_with_gcp_kms_are_publishable():
    assert validate(DOCUMENT) == 2


@pytest.mark.parametrize("document", [
    "assembly_api_key: plaintext\n",
    DOCUMENT.replace(f"assembly_api_key: {CIPHER}", "assembly_api_key: plaintext"),
    DOCUMENT.replace(f"assembly_api_key: {CIPHER}", "assembly_api_key: ENC[not-ciphertext]"),
    DOCUMENT.replace("    gcp_kms:", "    age:"),
    DOCUMENT.replace(f"    mac: {CIPHER}", "    mac: plaintext"),
    DOCUMENT + "    age:\n        - recipient: additional-recipient\n",
])
def test_plaintext_or_unexpected_recipient_is_rejected(document):
    with pytest.raises(ValueError):
        validate(document)
