# Autoscaling. Every service starts at one task, so the video can show response time rising
# when users arrive and falling as tasks are added.
#   API: CPU (target 60%) - it streams answers and does little work per request
#   agent workers: answers in progress per worker, from the queue metric the API publishes
#     (EagleEye/LoadTest ActiveAnswers) divided by the running workers (Container Insights)
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
    target_value       = 60
    scale_out_cooldown = 60
    scale_in_cooldown  = 180
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

resource "aws_appautoscaling_policy" "agent_answers" {
  name               = "${local.name}-agent-answers"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = "ecs"
  resource_id        = aws_appautoscaling_target.svc["agent-worker"].resource_id
  scalable_dimension = aws_appautoscaling_target.svc["agent-worker"].scalable_dimension
  target_tracking_scaling_policy_configuration {
    target_value       = var.answers_per_worker
    scale_out_cooldown = 45
    scale_in_cooldown  = 180
    customized_metric_specification {
      metrics {
        id          = "answers"
        return_data = false
        metric_stat {
          stat = "Average"
          metric {
            namespace   = "EagleEye/LoadTest"
            metric_name = "ActiveAnswers"
          }
        }
      }
      metrics {
        id          = "workers"
        return_data = false
        metric_stat {
          stat = "Average"
          metric {
            namespace   = "ECS/ContainerInsights"
            metric_name = "RunningTaskCount"
            dimensions {
              name  = "ClusterName"
              value = aws_ecs_cluster.this.name
            }
            dimensions {
              name  = "ServiceName"
              value = "agent-worker"
            }
          }
        }
      }
      metrics {
        id          = "per_worker"
        expression  = "answers / IF(workers < 1, 1, workers)"
        label       = "Answers in progress per agent worker"
        return_data = true
      }
    }
  }
}
