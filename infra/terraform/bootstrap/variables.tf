variable "bootstrap_project_id" {
  description = "Project hosting bootstrap resources such as WIF and the state bucket."
  type        = string
}

variable "manage_project_services" {
  description = "Manage bootstrap APIs here; false when the environment root owns APIs in the same project."
  type        = bool
  default     = true
}

variable "region" {
  description = "Region for bootstrap-adjacent regional resources."
  type        = string
  default     = "europe-west3"
}

variable "github_repository" {
  description = "GitHub repository in owner/name form."
  type        = string
}

variable "allowed_refs" {
  description = "Git refs allowed to impersonate the deploy service account."
  type        = list(string)
  default = [
    "refs/heads/main",
    "refs/heads/staging",
  ]
}

variable "state_bucket_name" {
  description = "Globally unique remote-state bucket name."
  type        = string
}

variable "wif_pool_id" {
  description = "Workload Identity Pool ID."
  type        = string
  default     = "github-actions-pool"
}

variable "wif_provider_id" {
  description = "Workload Identity Provider ID."
  type        = string
  default     = "github-actions-provider"
}

variable "deploy_service_account_id" {
  description = "Deploy service account ID."
  type        = string
  default     = "github-actions-deployer"
}
