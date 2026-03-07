"""DynamoDB service layer replacing Supabase."""

import boto3
import uuid
import hashlib
import hmac
import os
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key


class DynamoDBService:
    """Handles all DynamoDB operations for users, sessions, and messages."""

    def __init__(self, region="us-east-1"):
        self.dynamodb = boto3.resource("dynamodb", region_name=region)
        self.users_table = self.dynamodb.Table("hia_users")
        self.sessions_table = self.dynamodb.Table("hia_sessions")
        self.messages_table = self.dynamodb.Table("hia_messages")

    # --- User operations ---

    def _hash_password(self, password, salt=None):
        if salt is None:
            salt = os.urandom(32).hex()
        hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()
        return f"{salt}:{hashed}"

    def _verify_password(self, password, stored_hash):
        salt, expected_hash = stored_hash.split(":")
        actual_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()
        return hmac.compare_digest(expected_hash, actual_hash)

    def create_user(self, email, password, name):
        """Create a new user."""
        # Check if user exists
        existing = self.get_user_by_email(email)
        if existing:
            return False, "Email already registered"

        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        self.users_table.put_item(Item={
            "user_id": user_id,
            "email": email,
            "name": name,
            "password_hash": self._hash_password(password),
            "created_at": now,
        })
        return True, {"id": user_id, "email": email, "name": name, "created_at": now}

    def authenticate_user(self, email, password):
        """Authenticate user by email and password."""
        user = self.get_user_by_email(email)
        if not user:
            return False, "User not found"
        if not self._verify_password(password, user["password_hash"]):
            return False, "Invalid password"
        return True, {
            "id": user["user_id"],
            "email": user["email"],
            "name": user["name"],
        }

    def get_user_by_email(self, email):
        """Query user by email using GSI."""
        response = self.users_table.query(
            IndexName="email-index",
            KeyConditionExpression=Key("email").eq(email),
        )
        items = response.get("Items", [])
        return items[0] if items else None

    def get_user_by_id(self, user_id):
        response = self.users_table.get_item(Key={"user_id": user_id})
        return response.get("Item")

    # --- Session operations ---

    def create_session(self, user_id, title=None):
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        if not title:
            dt = datetime.now(timezone.utc)
            title = f"{dt.strftime('%d-%m-%Y')} | {dt.strftime('%H:%M:%S')}"

        item = {
            "session_id": session_id,
            "user_id": user_id,
            "title": title,
            "created_at": now,
        }
        self.sessions_table.put_item(Item=item)
        return True, {"id": session_id, **item}

    def get_user_sessions(self, user_id):
        response = self.sessions_table.query(
            IndexName="user_id-index",
            KeyConditionExpression=Key("user_id").eq(user_id),
            ScanIndexForward=False,
        )
        return True, response.get("Items", [])

    def delete_session(self, session_id):
        # Delete messages first
        msgs = self.messages_table.query(
            KeyConditionExpression=Key("session_id").eq(session_id)
        )
        with self.messages_table.batch_writer() as batch:
            for msg in msgs.get("Items", []):
                batch.delete_item(Key={
                    "session_id": msg["session_id"],
                    "created_at": msg["created_at"],
                })
        self.sessions_table.delete_item(Key={"session_id": session_id})
        return True, None

    # --- Message operations ---

    def save_message(self, session_id, content, role="user"):
        now = datetime.now(timezone.utc).isoformat()
        self.messages_table.put_item(Item={
            "session_id": session_id,
            "created_at": now,
            "message_id": str(uuid.uuid4()),
            "content": content,
            "role": role,
        })
        return True, None

    def get_session_messages(self, session_id):
        response = self.messages_table.query(
            KeyConditionExpression=Key("session_id").eq(session_id),
            ScanIndexForward=True,
        )
        return True, response.get("Items", [])
