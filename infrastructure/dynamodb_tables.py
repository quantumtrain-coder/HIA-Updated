"""Create DynamoDB tables for HIA."""

import boto3

REGION = "us-east-1"
dynamodb = boto3.client("dynamodb", region_name=REGION)


def create_tables():
    tables = [
        {
            "TableName": "hia_users",
            "KeySchema": [{"AttributeName": "user_id", "KeyType": "HASH"}],
            "AttributeDefinitions": [
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "email", "AttributeType": "S"},
            ],
            "GlobalSecondaryIndexes": [{
                "IndexName": "email-index",
                "KeySchema": [{"AttributeName": "email", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }],
            "BillingMode": "PAY_PER_REQUEST",
        },
        {
            "TableName": "hia_sessions",
            "KeySchema": [{"AttributeName": "session_id", "KeyType": "HASH"}],
            "AttributeDefinitions": [
                {"AttributeName": "session_id", "AttributeType": "S"},
                {"AttributeName": "user_id", "AttributeType": "S"},
            ],
            "GlobalSecondaryIndexes": [{
                "IndexName": "user_id-index",
                "KeySchema": [{"AttributeName": "user_id", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }],
            "BillingMode": "PAY_PER_REQUEST",
        },
        {
            "TableName": "hia_messages",
            "KeySchema": [
                {"AttributeName": "session_id", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            "AttributeDefinitions": [
                {"AttributeName": "session_id", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "S"},
            ],
            "BillingMode": "PAY_PER_REQUEST",
        },
    ]

    for table_def in tables:
        name = table_def["TableName"]
        try:
            dynamodb.create_table(**table_def)
            print(f"Created table: {name}")
            waiter = dynamodb.get_waiter("table_exists")
            waiter.wait(TableName=name)
            print(f"  Table {name} is active")
        except dynamodb.exceptions.ResourceInUseException:
            print(f"  Table {name} already exists, skipping")
        except Exception as e:
            print(f"  Error creating {name}: {e}")


if __name__ == "__main__":
    create_tables()
