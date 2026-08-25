check "runtime_services_require_networking" {
  assert {
    condition     = !var.deploy_runtime_services || var.provision_networking
    error_message = "deploy_runtime_services=true requires provision_networking=true."
  }
}

locals {
  app_project_apis = setunion(
    toset([
      "cloudresourcemanager.googleapis.com",
      "iam.googleapis.com",
      "iamcredentials.googleapis.com",
      "secretmanager.googleapis.com",
      "serviceusage.googleapis.com",
      "sts.googleapis.com",
    ]),
    var.provision_artifact_registry ? toset(["artifactregistry.googleapis.com"]) : toset([]),
    var.provision_networking ? toset(["compute.googleapis.com"]) : toset([]),
    var.deploy_runtime_services ? toset(["run.googleapis.com"]) : toset([]),
  )

  firebase_project_apis = toset([
    "firestore.googleapis.com",
    "firebase.googleapis.com",
    "identitytoolkit.googleapis.com",
    "serviceusage.googleapis.com",
  ])

  agent_secret_permissions = [
    "secretmanager.secrets.delete",
    "secretmanager.secrets.get",
    "secretmanager.secrets.update",
    "secretmanager.versions.access",
    "secretmanager.versions.add",
    "secretmanager.versions.destroy",
    "secretmanager.versions.disable",
    "secretmanager.versions.enable",
    "secretmanager.versions.get",
    "secretmanager.versions.list",
  ]

  tenant_secret_project_id = coalesce(var.tenant_secret_project_id, var.project_id)
  required_project_services = merge(
    {
      for service in local.app_project_apis :
      "${var.project_id}/${service}" => {
        project = var.project_id
        service = service
      }
    },
    {
      for service in local.firebase_project_apis :
      "${var.firebase_project_id}/${service}" => {
        project = var.firebase_project_id
        service = service
      }
    },
    {
      for service in toset([
        "iam.googleapis.com",
        "secretmanager.googleapis.com",
        "serviceusage.googleapis.com",
      ]) :
      "${local.tenant_secret_project_id}/${service}" => {
        project = local.tenant_secret_project_id
        service = service
      }
    },
  )
  all_secret_ids = toset(distinct(concat(
    tolist(var.static_secret_ids),
    [for ref in values(var.agent_secret_env) : ref.secret_id],
    [for ref in values(var.web_secret_env) : ref.secret_id]
  )))
  agent_secret_ids = toset([for ref in values(var.agent_secret_env) : ref.secret_id])
  web_secret_ids   = toset([for ref in values(var.web_secret_env) : ref.secret_id])

  base_agent_env = {
    CONDUUT_ENVIRONMENT                      = var.environment
    CONDUUT_FIREBASE_CREDENTIALS_MODE        = "adc"
    CONDUUT_FIREBASE_PROJECT_ID              = var.firebase_project_id
    CONDUUT_N8N_PROVIDER_MODE                = "customer_owned"
    CONDUUT_N8N_SECRET_MANAGER_BACKEND       = "google_secret_manager"
    CONDUUT_N8N_SECRET_MANAGER_LOCATION      = var.region
    CONDUUT_N8N_SECRET_MANAGER_PROJECT_ID    = local.tenant_secret_project_id
    CONDUUT_N8N_SECRET_MANAGER_SECRET_PREFIX = var.tenant_secret_prefix
    CONDUUT_PUBLIC_WEB_URL                   = var.public_web_url
  }

  base_web_env = {
    AGENT_API_AUTH_MODE         = "cloud_run"
    AGENT_API_AUDIENCE          = try(google_cloud_run_v2_service.agent[0].uri, "")
    AGENT_API_BASE_URL          = try(google_cloud_run_v2_service.agent[0].uri, "")
    AGENT_API_STREAM_TIMEOUT_MS = "905000"
    AGENT_API_TIMEOUT_MS        = "30000"
  }
}

data "google_project" "tenant_secret" {
  project_id = local.tenant_secret_project_id
}

resource "google_project_service" "required" {
  for_each           = local.required_project_services
  project            = each.value.project
  service            = each.value.service
  disable_on_destroy = false
}

resource "google_firebase_project" "project" {
  count = var.manage_firebase_project ? 1 : 0

  provider   = google-beta
  project    = var.firebase_project_id
  depends_on = [google_project_service.required]
}

resource "google_firestore_database" "default" {
  count = var.manage_firestore_database ? 1 : 0

  provider    = google-beta
  project     = var.firebase_project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.required, google_firebase_project.project]
}

resource "google_artifact_registry_repository" "containers" {
  count = var.provision_artifact_registry ? 1 : 0

  project       = var.project_id
  location      = var.region
  repository_id = var.artifact_repository_id
  format        = "DOCKER"
  description   = "Conduut containers for ${var.environment}."

  depends_on = [google_project_service.required]
}

resource "google_artifact_registry_repository_iam_member" "deployer_writer" {
  count = var.provision_artifact_registry && var.deploy_service_account_email != null ? 1 : 0

  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.containers[0].name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${var.deploy_service_account_email}"
}

resource "google_service_account" "web" {
  project      = var.project_id
  account_id   = "${var.environment}-web"
  display_name = "Conduut ${var.environment} web runtime"
}

resource "google_service_account" "agent" {
  project      = var.project_id
  account_id   = "${var.environment}-agent"
  display_name = "Conduut ${var.environment} agent runtime"
}

resource "google_service_account_iam_member" "deployer_uses_web_identity" {
  count = var.deploy_service_account_email == null ? 0 : 1

  service_account_id = google_service_account.web.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.deploy_service_account_email}"
}

resource "google_service_account_iam_member" "deployer_uses_agent_identity" {
  count = var.deploy_service_account_email == null ? 0 : 1

  service_account_id = google_service_account.agent.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.deploy_service_account_email}"
}

resource "google_project_iam_member" "deployer_cloud_run" {
  count = var.deploy_service_account_email == null ? 0 : 1

  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${var.deploy_service_account_email}"
}

resource "google_project_iam_custom_role" "agent_secret_manager" {
  project     = local.tenant_secret_project_id
  role_id     = "${replace(var.environment, "-", "_")}_agent_secret_manager"
  title       = "Conduut ${var.environment} agent secret manager"
  description = "Least-privilege runtime access for tenant n8n secrets."
  permissions = local.agent_secret_permissions

  depends_on = [google_project_service.required]
}

resource "google_project_iam_custom_role" "agent_secret_creator" {
  project     = local.tenant_secret_project_id
  role_id     = "${replace(var.environment, "-", "_")}_agent_secret_creator"
  title       = "Conduut ${var.environment} agent secret creator"
  description = "Create-only access in the configured tenant-secret project boundary."
  permissions = ["secretmanager.secrets.create"]

  depends_on = [google_project_service.required]
}

resource "google_project_iam_member" "agent_firestore" {
  project = var.firebase_project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.agent.email}"
}

resource "google_project_iam_member" "agent_secret_role" {
  project = local.tenant_secret_project_id
  role    = google_project_iam_custom_role.agent_secret_manager.name
  member  = "serviceAccount:${google_service_account.agent.email}"

  dynamic "condition" {
    for_each = [1]

    content {
      title       = "tenant-secret-prefix"
      expression  = "resource.name.startsWith('projects/${data.google_project.tenant_secret.number}/secrets/${var.tenant_secret_prefix}-')"
      description = "Limit runtime secret access to tenant-scoped hashed GSM secrets."
    }
  }
}

resource "google_project_iam_member" "agent_secret_creator" {
  project = local.tenant_secret_project_id
  role    = google_project_iam_custom_role.agent_secret_creator.name
  member  = "serviceAccount:${google_service_account.agent.email}"
}

resource "google_secret_manager_secret" "static" {
  for_each            = local.all_secret_ids
  project             = var.project_id
  secret_id           = each.value
  version_destroy_ttl = "604800s"

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
}

resource "google_secret_manager_secret_iam_member" "agent_static_accessor" {
  for_each = local.agent_secret_ids

  project   = var.project_id
  secret_id = google_secret_manager_secret.static[each.value].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.agent.email}"
}

resource "google_secret_manager_secret_iam_member" "web_static_accessor" {
  for_each = local.web_secret_ids

  project   = var.project_id
  secret_id = google_secret_manager_secret.static[each.value].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.web.email}"
}

resource "google_compute_network" "serverless" {
  count = var.provision_networking ? 1 : 0

  project                 = var.project_id
  name                    = "${var.environment}-serverless-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "serverless" {
  count = var.provision_networking ? 1 : 0

  project                  = var.project_id
  name                     = "${var.environment}-serverless-subnet"
  region                   = var.region
  network                  = google_compute_network.serverless[0].id
  ip_cidr_range            = "10.42.0.0/24"
  private_ip_google_access = true
}

resource "google_compute_router" "serverless" {
  count = var.provision_networking ? 1 : 0

  project = var.project_id
  name    = "${var.environment}-serverless-router"
  region  = var.region
  network = google_compute_network.serverless[0].id
}

resource "google_compute_router_nat" "serverless" {
  count = var.provision_networking ? 1 : 0

  project                            = var.project_id
  name                               = "${var.environment}-serverless-nat"
  router                             = google_compute_router.serverless[0].name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"

  subnetwork {
    name                    = google_compute_subnetwork.serverless[0].id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }
}

resource "google_cloud_run_v2_service" "agent" {
  count = var.deploy_runtime_services ? 1 : 0

  project  = var.project_id
  name     = "${var.environment}-${var.agent_service_name}"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account                  = google_service_account.agent.email
    timeout                          = "900s"
    max_instance_request_concurrency = 10

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    vpc_access {
      egress = "ALL_TRAFFIC"

      network_interfaces {
        network    = google_compute_network.serverless[0].id
        subnetwork = google_compute_subnetwork.serverless[0].id
      }
    }

    containers {
      image = var.agent_image

      ports {
        container_port = 8000
      }

      dynamic "env" {
        for_each = merge(local.base_agent_env, var.agent_env)
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.agent_secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value.secret_id
              version = env.value.version
            }
          }
        }
      }

      startup_probe {
        http_get {
          path = "/health"
          port = 8000
        }
        failure_threshold     = 12
        period_seconds        = 5
        timeout_seconds       = 5
        initial_delay_seconds = 5
      }

      liveness_probe {
        http_get {
          path = "/health"
          port = 8000
        }
        failure_threshold = 3
        period_seconds    = 10
        timeout_seconds   = 5
      }
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.agent_static_accessor,
  ]
}

resource "google_cloud_run_v2_service" "web" {
  count = var.deploy_runtime_services ? 1 : 0

  project  = var.project_id
  name     = "${var.environment}-${var.web_service_name}"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account                  = google_service_account.web.email
    max_instance_request_concurrency = 80

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    vpc_access {
      egress = "ALL_TRAFFIC"

      network_interfaces {
        network    = google_compute_network.serverless[0].id
        subnetwork = google_compute_subnetwork.serverless[0].id
      }
    }

    containers {
      image = var.web_image

      ports {
        container_port = 3000
      }

      dynamic "env" {
        for_each = merge(local.base_web_env, var.web_env)
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.web_secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value.secret_id
              version = env.value.version
            }
          }
        }
      }

      startup_probe {
        http_get {
          path = "/"
          port = 3000
        }
        failure_threshold     = 12
        period_seconds        = 5
        timeout_seconds       = 5
        initial_delay_seconds = 5
      }
    }
  }

  depends_on = [
    google_cloud_run_v2_service.agent,
    google_secret_manager_secret_iam_member.web_static_accessor,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "web_public" {
  count = var.deploy_runtime_services ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.web[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "agent_invoker" {
  count = var.deploy_runtime_services ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.agent[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.web.email}"
}
