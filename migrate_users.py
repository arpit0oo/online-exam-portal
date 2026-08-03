"""
One-time migration: convert student users from
  class_id / class_name  →  class_ids: []
Run once, then delete this file.
"""
import firebase_admin
from firebase_admin import credentials, firestore
import os, json

if os.path.exists('firebase-adminsdk.json'):
    cred = credentials.Certificate('firebase-adminsdk.json')
else:
    cred = credentials.Certificate(json.loads(os.environ['FIREBASE_ADMINSDK_JSON']))

firebase_admin.initialize_app(cred)
db = firestore.client()

users = db.collection('users').stream()
migrated = 0
skipped = 0

for doc in users:
    data = doc.to_dict()

    # Only process students
    if data.get('role') != 'student':
        skipped += 1
        continue

    # Already migrated
    if 'class_ids' in data:
        skipped += 1
        continue

    old_class_id = data.get('class_id')
    new_class_ids = [old_class_id] if old_class_id else []

    update = {'class_ids': new_class_ids}

    # Remove old fields
    update['class_id'] = firestore.DELETE_FIELD
    update['class_name'] = firestore.DELETE_FIELD

    doc.reference.update(update)
    migrated += 1
    print(f"  Migrated: {data.get('email')} → class_ids={new_class_ids}")

print(f"\n✅ Done. Migrated: {migrated}, Skipped: {skipped}")
