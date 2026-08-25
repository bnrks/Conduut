variable "project_id" {
  description = "Application project ID hosting Cloud Run, GSM and networking."
  type        = string
}

variable "firebase_project_id" {
  description = "Separate Firebase/Auth/Firestore project ID."
  type        = string
}

variable "region" {
  description = "Primary region."
  type        = string
}

variable "environment" {
  description = "Environment name."
  type        = string
}

variable "artifact_repository_id" {
  description = "Artifact Registry repository ID."
  type        = string
}

variable "tenant_secret_prefix" {
  description = "Reserved prefix for tenant runtime secrets."
  type        = string
}

variable "tenant_secret_project_id" {
  description = "Dedicated project containing tenant runtime secrets only."
  type        = string

  validation {
    condition     = length(trimspace(var.tenant_secret_project_id)) > 0
    error_message = "tenant_secret_project_id is required."
  }
}

variable "deploy_runtime_services" {
  description = "Create Cloud Run services only after static secret versions have been seeded."
  type        = bool
  default     = false
}

variable "deploy_service_account_email" {
  description = "Optional WIF deploy identity; receives image-writer and Cloud Run developer only."
  type        = string
  default     = null
}

variable "public_web_url" {
  description = "Public web base URL."
  type        = string
}

variable "web_image" {
  type = string
}

variable "agent_image" {
  type = string
}

variable "web_service_name" {
  type    = string
  default = "conduut-web"
}

variable "agent_service_name" {
  type    = string
  default = "conduut-agent"
}

variable "static_secret_ids" {
  description = "Static secret containers created without values."
  type        = set(string)
}

variable "web_env" {
  type    = map(string)
  default = {}
}

variable "agent_env" {
  type    = map(string)
  default = {}
}

variable "agent_secret_env" {
  description = "Agent env vars backed by Secret Manager."
  type = map(object({
    secret_id = string
    version   = optional(string, "latest")
  }))
}

variable "web_secret_env" {
  description = "Web env vars backed by Secret Manager."
  type = map(object({
    secret_id = string
    version   = optional(string, "latest")
  }))
  default = {}
}
