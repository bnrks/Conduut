import firebase_admin
from firebase_admin import credentials, firestore

_cred = credentials.Certificate("/app/serviceAccount.json")
firebase_admin.initialize_app(_cred)

db = firestore.client()
