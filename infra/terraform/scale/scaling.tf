# Autoscaling. Every service starts at one task, so the video can show response time rising
# when users arrive and falling as tasks are added.
#   API: CPU (target 50%) - it streams answers and does little work per request
#   agent workers: step scaling on answers in progress per worker (the queue metric the API
#     publishes every 30 s, EagleEye/LoadTest ActiveAnswers, over running workers), judged
#     every minute, so the cluster reacts within about two minutes (target tracking waits 3+)
#   ingest worker, gateway: CPU
# Scale-out reacts within about a minute; scale-in waits longer so the cluster doesn't flap.

resource "aws_appautoscaling_target" "svc" {
  for_each = {
    api           = var.api_max
    agent-worker  = var.agent_max
    ingest-worker = 2
    gateway       = 3
  }
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.svc[each.key].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = 1
  max_capacity       = each.value
}

resource "aws_appautoscaling_policy" "cpu" {
  for_each           = toset(["api", "ingest-worker", "gateway"])
  name               = "${local.name}-${each.key}-cpu"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = "ecs"
  resource_id        = aws_appautoscaling_target.svc[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.svc[each.key].scalable_dimension
  target_tracking_scaling_policy_configuration {
    target_value       = 50 # scale a little early: the API holds every answer stream
    scale_out_cooldown = 60
    scale_in_cooldown  = 180
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "agent_busy" {
  alarm_name          = "${local.name}-agent-busy"
  alarm_description   = "Answers in progress per agent worker above target: add workers"
  comparison_operator = "GreaterThanThreshold"
  threshold           = var.answers_per_worker
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_appautoscaling_policy.agent_out.arn]

  metric_query {
    id          = "answers"
    return_data = false
    metric {
      namespace   = "EagleEye/LoadTest"
      metric_name = "ActiveAnswers"
      period      = 60
      stat        = "Average"
    }
  }
  metric_query {
    id          = "workers"
    return_data = false
    metric {
      namespace   = "ECS/ContainerInsights"
      metric_name = "RunningTaskCount"
      period      = 60
      stat        = "Average"
      dimensions  = { ClusterName = local.name, ServiceName = "agent-worker" }
    }
  }
  metric_query {
    id          = "per_worker"
    expression  = "answers / IF(workers < 1, 1, workers)"
    label       = "Answers in progress per agent worker"
    return_data = true
  }
}

resource "aws_cloudwatch_metric_alarm" "agent_quiet" {
  alarm_name          = "${local.name}-agent-quiet"
  alarm_description   = "Few answers per agent worker for 5 minutes: remove a worker"
  comparison_operator = "LessThanThreshold"
  threshold           = var.answers_per_worker * 0.4
  evaluation_periods  = 5
  datapoints_to_alarm = 5
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_appautoscaling_policy.agent_in.arn]

  metric_query {
    id          = "answers"
    return_data = false
    metric {
      namespace   = "EagleEye/LoadTest"
      metric_name = "ActiveAnswers"
      period      = 60
      stat        = "Average"
    }
  }
  metric_query {
    id          = "workers"
    return_data = false
    metric {
      namespace   = "ECS/ContainerInsights"
      metric_name = "RunningTaskCount"
      period      = 60
      stat        = "Average"
      dimensions  = { ClusterName = local.name, ServiceName = "agent-worker" }
    }
  }
  metric_query {
    id          = "per_worker"
    expression  = "answers / IF(workers < 1, 1, workers)"
    label       = "Answers in progress per agent worker"
    return_data = true
  }
}

# the further above target, the more workers at once (bounds are relative to the threshold)
resource "aws_appautoscaling_policy" "agent_out" {
  name               = "${local.name}-agent-out"
  policy_type        = "StepScaling"
  service_namespace  = "ecs"
  resource_id        = aws_appautoscaling_target.svc["agent-worker"].resource_id
  scalable_dimension = aws_appautoscaling_target.svc["agent-worker"].scalable_dimension
  step_scaling_policy_configuration {
    adjustment_type         = "ChangeInCapacity"
    cooldown                = 60
    metric_aggregation_type = "Average"
    step_adjustment {
      metric_interval_lower_bound = 0
      metric_interval_upper_bound = var.answers_per_worker
      scaling_adjustment          = 2
    }
    step_adjustment {
      metric_interval_lower_bound = var.answers_per_worker
      metric_interval_upper_bound = var.answers_per_worker * 3
      scaling_adjustment          = 4
    }
    step_adjustment {
      metric_interval_lower_bound = var.answers_per_worker * 3
      scaling_adjustment          = 6
    }
  }
}

resource "aws_appautoscaling_policy" "agent_in" {
  name               = "${local.name}-agent-in"
  policy_type        = "StepScaling"
  service_namespace  = "ecs"
  resource_id        = aws_appautoscaling_target.svc["agent-worker"].resource_id
  scalable_dimension = aws_appautoscaling_target.svc["agent-worker"].scalable_dimension
  step_scaling_policy_configuration {
    adjustment_type         = "ChangeInCapacity"
    cooldown                = 60
    metric_aggregation_type = "Average"
    step_adjustment {
      metric_interval_upper_bound = 0
      scaling_adjustment          = -1
    }
  }
}
