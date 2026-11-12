"""Pulumi Python program deploying the Serverless Withings to Garmin Sync infrastructure."""

import json

import pulumi
import pulumi_aws as aws

try:
    from infra.build import build_lambda_package
except ModuleNotFoundError:
    from build import build_lambda_package

config = pulumi.Config()
schedule_cron = config.get("scheduleCron") or "rate(1 hour)"
alert_email = config.get("alertEmail")
ssm_prefix = config.get("ssmPrefix") or "/withings-sync"
sync_window_days = config.get("syncWindowDays") or "30"

# 1. Ensure deployment package zip is built
zip_path = build_lambda_package()

# 2. SNS Alert Topic (for token expiration alerts)
alert_topic = aws.sns.Topic(
    "withings-sync-alerts",
    name="withings-sync-alerts",
)

if alert_email:
    aws.sns.TopicSubscription(
        "withings-sync-alert-email-sub",
        topic=alert_topic.arn,
        protocol="email",
        endpoint=alert_email,
    )

# 3. SSM Parameter Placeholders (with ignore_changes so Pulumi never overwrites active tokens)
for param_key, default_val in [
    ("credentials", "{}"),
    ("tokens", "{}"),
    ("ledger", "[]"),
    ("state", "{}"),
]:
    aws.ssm.Parameter(
        f"ssm-param-{param_key}",
        name=f"{ssm_prefix}/{param_key}",
        type="SecureString",
        value=default_val,
        opts=pulumi.ResourceOptions(ignore_changes=["value"]),
    )

# 4. IAM Role for Lambda
assume_role_policy = json.dumps(
    {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Action": "sts:AssumeRole",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Effect": "Allow",
            }
        ],
    }
)

lambda_role = aws.iam.Role(
    "withings-sync-lambda-role",
    assume_role_policy=assume_role_policy,
)

current_region = aws.get_region().name
current_caller = aws.get_caller_identity().account_id

ssm_arn_pattern = f"arn:aws:ssm:{current_region}:{current_caller}:parameter{ssm_prefix}/*"

role_policy = aws.iam.RolePolicy(
    "withings-sync-policy",
    role=lambda_role.id,
    policy=pulumi.Output.all(alert_topic.arn).apply(
        lambda args: json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "logs:CreateLogGroup",
                            "logs:CreateLogStream",
                            "logs:PutLogEvents",
                        ],
                        "Resource": "arn:aws:logs:*:*:*",
                    },
                    {
                        "Effect": "Allow",
                        "Action": [
                            "ssm:GetParameter",
                            "ssm:GetParameters",
                            "ssm:PutParameter",
                        ],
                        "Resource": ssm_arn_pattern,
                    },
                    {
                        "Effect": "Allow",
                        "Action": ["sns:Publish"],
                        "Resource": args[0],
                    },
                ],
            }
        )
    ),
)

# 5. CloudWatch Log Group with 14-day retention (to avoid storage costs)
log_group = aws.cloudwatch.LogGroup(
    "withings-sync-log-group",
    name="/aws/lambda/withings-garmin-sync",
    retention_in_days=14,
)

# 6. Lambda Function (ARM64 Graviton)
lambda_func = aws.lambda_.Function(
    "withings-garmin-sync-lambda",
    name="withings-garmin-sync",
    role=lambda_role.arn,
    runtime="python3.12",
    architectures=["arm64"],
    handler="withings_garmin_sync.handler.lambda_handler",
    code=pulumi.FileArchive(str(zip_path)),
    memory_size=256,
    timeout=60,
    environment=aws.lambda_.FunctionEnvironmentArgs(
        variables={
            "SSM_PREFIX": ssm_prefix,
            "ALERT_SNS_TOPIC_ARN": alert_topic.arn,
            "SYNC_WINDOW_DAYS": str(sync_window_days),
        }
    ),
    opts=pulumi.ResourceOptions(depends_on=[log_group, role_policy]),
)

# 7. EventBridge Scheduled Rule (e.g. rate(1 hour))
event_rule = aws.cloudwatch.EventRule(
    "withings-sync-schedule",
    name="withings-sync-schedule",
    description="Trigger Withings to Garmin sync periodically",
    schedule_expression=schedule_cron,
)

event_target = aws.cloudwatch.EventTarget(
    "withings-sync-target",
    rule=event_rule.name,
    arn=lambda_func.arn,
)

lambda_permission = aws.lambda_.Permission(
    "withings-sync-eventbridge-permission",
    action="lambda:InvokeFunction",
    function=lambda_func.name,
    principal="events.amazonaws.com",
    source_arn=event_rule.arn,
)

# 8. Exports
pulumi.export("lambda_arn", lambda_func.arn)
pulumi.export("sns_topic_arn", alert_topic.arn)
pulumi.export("ssm_prefix", ssm_prefix)
pulumi.export("schedule_cron", schedule_cron)
