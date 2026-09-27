# Key access is off, so Terraform manages everything here through the management plane (the
# provider sets storage.data_plane_available = false) and every reader needs a data role.
resource "azurerm_storage_account" "this" {
  name                     = local.e.storage
  location                 = azurerm_resource_group.this.location
  resource_group_name      = azurerm_resource_group.this.name
  account_kind             = "StorageV2"
  account_tier             = "Standard"
  account_replication_type = local.e.storage_replication
  min_tls_version          = "TLS1_2"

  shared_access_key_enabled       = local.shared.storage_shared_key_access
  allow_nested_items_to_be_public = local.shared.storage_public_blob_access
  default_to_oauth_authentication = true

  blob_properties {
    versioning_enabled = true

    delete_retention_policy {
      days = 7
    }

    container_delete_retention_policy {
      days = 7
    }
  }

  tags = local.tags
}

# Lesson 04's integrated-vectorization experiment reads from here. dev only.
resource "azurerm_storage_container" "corpus" {
  count = local.env == "dev" ? 1 : 0

  name                  = "corpus"
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "private"
}

# Lesson 13: one redacted JSON record per answer.
resource "azurerm_storage_container" "audit" {
  name                  = "audit"
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "private"
}

locals {
  # The scope for roles on the audit container alone, in the form check_env compares.
  audit_scope = "${azurerm_storage_account.this.id}/blobServices/default/containers/${azurerm_storage_container.audit.name}"
}

# Versioning is on, so a deleted blob leaves a previous version behind. Delete those too, or
# the retention period isn't real.
resource "azurerm_storage_management_policy" "this" {
  storage_account_id = azurerm_storage_account.this.id

  rule {
    name    = "audit-retention"
    enabled = true

    filters {
      blob_types   = ["blockBlob"]
      prefix_match = ["audit/"]
    }

    actions {
      base_blob {
        delete_after_days_since_creation_greater_than = local.e.audit_retention_days
      }
      version {
        delete_after_days_since_creation = local.e.audit_retention_days
      }
    }
  }
}
