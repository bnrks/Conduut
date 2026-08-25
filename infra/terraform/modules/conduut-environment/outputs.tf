output "agent_service_url" {
  value = try(google_cloud_run_v2_service.agent[0].uri, null)
}

output "web_service_url" {
  value = try(google_cloud_run_v2_service.web[0].uri, null)
}

output "artifact_repository_id" {
  value = try(google_artifact_registry_repository.containers[0].id, null)
}

output "agent_service_name" {
  value = try(google_cloud_run_v2_service.agent[0].name, null)
}

output "web_service_name" {
  value = try(google_cloud_run_v2_service.web[0].name, null)
}

output "runtime_service_accounts" {
  value = {
    agent = google_service_account.agent.email
    web   = google_service_account.web.email
  }
}
