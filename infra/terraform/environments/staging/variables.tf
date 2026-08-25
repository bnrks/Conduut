variable "project_id" {
  type = string
}

variable "firebase_project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "europe-west3"
}

variable "artifact_repository_id" {
  type    = string
  default = "conduut-staging"
}

variable "tenant_secret_prefix" {
  type    = string
  default = "conduut-staging-tenant"
}

variable "tenant_secret_project_id" {
  type = string
}

variable "deploy_runtime_services" {
  type    = bool
  default = false
}

variable "deploy_service_account_email" {
  type    = string
  default = null
}

variable "public_web_url" {
  type = string
}

variable "web_image" {
  type = string
}

variable "agent_image" {
  type = string
}

variable "web_env" {
  type    = map(string)
  default = {}
}

variable "web_secret_env" {
  type = map(object({
    secret_id = string
    version   = optional(string, "latest")
  }))
  default = {}
}

variable "agent_env" {
  type    = map(string)
  default = {}
}
