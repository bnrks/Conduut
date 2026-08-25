output "deploy_service_account_email" {
  value = google_service_account.deploy.email
}

output "state_bucket_name" {
  value = google_storage_bucket.terraform_state.name
}

output "workload_identity_provider" {
  value = google_iam_workload_identity_pool_provider.github.name
}
