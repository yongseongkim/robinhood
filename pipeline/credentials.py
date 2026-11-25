"""수집에 필요한 API 인증키를 읽는다.

환경변수(예: ASSEMBLY_API_KEY)에 값이 있으면 그 값을 쓴다.
없으면 SOPS로 프로젝트 루트의 credentials.yaml에서 해당 키만 복호화한다.
이때 .sops.yaml에 지정된 GCP KMS 키의 복호화 권한이 있는 ADC가 필요하다.
복호화한 값은 메모리에서만 사용한다.

키를 추가하거나 바꿀 때는 터미널에서 sops credentials.yaml을 실행한다.
편집기에서 저장하면 SOPS가 다시 암호화한다.
"""
import json
import os
import subprocess

from common import ROOT

CRED_FILE = ROOT / "credentials.yaml"
PLACEHOLDER = "REPLACE_ME"


class MissingCredential(RuntimeError):
    pass


def get(name, env_var=None):
    env_var = env_var or name.upper()
    if os.environ.get(env_var):
        return os.environ[env_var]
    if not CRED_FILE.exists():
        raise MissingCredential(f"{CRED_FILE.relative_to(ROOT)} 이 없습니다. docs/INSTALL.md의 'API 인증키' 절을 보세요.")
    try:
        r = subprocess.run(["sops", "decrypt", "--extract", json.dumps([name]), str(CRED_FILE)],
                           capture_output=True, text=True, timeout=30)
    except FileNotFoundError as e:
        raise MissingCredential("sops가 설치되어 있지 않습니다 (brew install sops).") from e
    if r.returncode != 0:
        last = (r.stderr.strip().splitlines() or ["알 수 없는 오류"])[-1]
        raise MissingCredential(f"sops 복호화 실패({name}): {last} — GCP KMS 권한과 `gcloud auth application-default login`을 확인하세요.")
    value = r.stdout.strip()
    if not value or value == PLACEHOLDER:
        raise MissingCredential(f"{name} 값이 아직 없습니다. 본인 터미널에서 `sops credentials.yaml`로 값을 넣으세요.")
    return value


if __name__ == "__main__":
    # 값 자체는 출력하지 않고, 읽히는지만 확인한다
    import sys
    key = sys.argv[1] if len(sys.argv) > 1 else "assembly_api_key"
    try:
        v = get(key)
        print(f"{key}: 읽기 성공 (길이 {len(v)})")
    except MissingCredential as e:
        print(f"{key}: {e}")
        sys.exit(1)
