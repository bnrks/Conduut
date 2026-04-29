from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore


def _service_account_path() -> str:
    docker_path = Path("/app/serviceAccount.json")
    if docker_path.exists():
        return str(docker_path)

    local_path = Path(__file__).resolve().parent.parent / "serviceAccount.json"
    return str(local_path)


_cred = credentials.Certificate(_service_account_path())
if not firebase_admin._apps:
    firebase_admin.initialize_app(_cred)

db = firestore.client()
