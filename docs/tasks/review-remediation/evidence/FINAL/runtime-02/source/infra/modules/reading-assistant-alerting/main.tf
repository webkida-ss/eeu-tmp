# Blast-radius capping for abuse (e.g. someone trying to burn OpenAI tokens
# through the API): a monthly AWS cost budget with 50/80/100% notifications
# and a CloudWatch alarm on abnormal Lambda invocation volume.
#
# Note: AWS Budgets only sees AWS spend. OpenAI spend is external; cap it on
# the OpenAI platform (usage limits) in addition to the in-app per-user
# token quotas. See infra/README.md, "Security and abuse resistance".
locals {
  name_prefix = "${var.project}-${var.environment}-reading-assistant"
}

resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-alerts"
}

# The email endpoint must confirm the subscription (AWS sends a
# confirmation mail after apply).
resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# Account-wide monthly cost budget. Notification-only budgets are free.
# It is deliberately not filtered by tag: cost allocation tags require
# manual activation in the billing console and silently match nothing until
# then, which would defeat the purpose of a safety net.
resource "aws_budgets_budget" "monthly_cost" {
  name         = "${local.name_prefix}-monthly-cost"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = [50, 80, 100]

    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.alert_email]
    }
  }
}

# Static-threshold anomaly signal: more invocations per hour than any
# legitimate PoC traffic would produce means someone is hammering the API.
resource "aws_cloudwatch_metric_alarm" "lambda_invocations" {
  alarm_name          = "${local.name_prefix}-lambda-invocations-hourly"
  alarm_description   = "Backend Lambda received more than ${var.lambda_invocations_hourly_threshold} invocations in one hour; possible abuse or a runaway client."
  namespace           = "AWS/Lambda"
  metric_name         = "Invocations"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = var.lambda_invocations_hourly_threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = var.lambda_function_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}
