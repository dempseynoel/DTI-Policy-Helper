# dev. Everything this environment is comes from deploy/environments.yaml: the shared section
# (must match everywhere) and environments.dev (may differ). This folder only chooses which
# entry to build, and holds its own state.

terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.81"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.12"
    }
  }

  # State is a local file in this folder (git-ignored). See infra/README.md.
}

locals {
  config = yamldecode(file("${path.root}/../../deploy/environments.yaml"))
}

provider "azurerm" {
  # From environments.yaml, never from your shell: `az account set` can't point this elsewhere.
  subscription_id = local.config.subscription_id

  features {
    # Key access is off on the storage account, so manage it through the management plane.
    storage {
      data_plane_available = false
    }
    # On destroy, purge soft-deleted Foundry and Key Vault resources so a rebuild can reuse
    # the names.
    cognitive_account {
      purge_soft_delete_on_destroy = true
    }
    key_vault {
      purge_soft_delete_on_destroy = true
    }
  }
}

module "env" {
  source = "../modules/environment"

  environment = "dev"
  config      = local.config
  env_file    = "${path.root}/../../deploy/dev.env"
}

output "app_url" {
  value = module.env.app_url
}

output "deploy_identity_client_id" {
  value = module.env.deploy_identity_client_id
}
