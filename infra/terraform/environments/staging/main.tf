locals {
  static_secret_ids = toset([
    "conduut-anthropic-api-key",
    "conduut-connection-encryption-key",
    "conduut-deepseek-api-key",
    "conduut-google-api-key",
    "conduut-google-oauth-client-id",
    "conduut-google-oauth-client-secret",
    "conduut-openai-api-key",
    "conduut-openrouter-api-key",
  ])

  agent_secret_env = {
    CONDUUT_ANTHROPIC_API_KEY = {
      secret_id = "conduut-anthropic-api-key"
    }
    CONDUUT_CONNECTION_ENCRYPTION_KEY = {
      secret_id = "conduut-connection-encryption-key"
    }
    CONDUUT_DEEPSEEK_API_KEY = {
      secret_id = "conduut-deepseek-api-key"
    }
    CONDUUT_GOOGLE_API_KEY = {
      secret_id = "conduut-google-api-key"
    }
    CONDUUT_GOOGLE_OAUTH_CLIENT_ID = {
      secret_id = "conduut-google-oauth-client-id"
    }
    CONDUUT_GOOGLE_OAUTH_CLIENT_SECRET = {
      secret_id = "conduut-google-oauth-client-secret"
    }
    CONDUUT_OPENAI_API_KEY = {
      secret_id = "conduut-openai-api-key"
    }
    CONDUUT_OPENROUTER_API_KEY = {
      secret_id = "conduut-openrouter-api-key"
    }
  }
}

module "staging" {
  source = "../../modules/conduut-environment"

  agent_env                    = var.agent_env
  agent_image                  = var.agent_image
  agent_secret_env             = local.agent_secret_env
  artifact_repository_id       = var.artifact_repository_id
  deploy_runtime_services      = var.deploy_runtime_services
  deploy_service_account_email = var.deploy_service_account_email
  environment                  = "staging"
  firebase_project_id          = var.firebase_project_id
  project_id                   = var.project_id
  public_web_url               = var.public_web_url
  region                       = var.region
  static_secret_ids            = local.static_secret_ids
  tenant_secret_prefix         = var.tenant_secret_prefix
  tenant_secret_project_id     = var.tenant_secret_project_id
  web_env                      = var.web_env
  web_image                    = var.web_image
  web_secret_env               = var.web_secret_env
}

output "agent_service_url" {
  value = module.staging.agent_service_url
}

output "web_service_url" {
  value = module.staging.web_service_url
}

output "agent_service_name" {
  value = module.staging.agent_service_name
}

output "web_service_name" {
  value = module.staging.web_service_name
}
