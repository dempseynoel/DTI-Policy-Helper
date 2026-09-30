output "app_url" {
  description = "The Container App's URL, once environments.yaml names an image."
  value       = local.app_enabled ? "https://${azurerm_container_app.this[0].ingress[0].fqdn}" : null
}

output "deploy_identity_client_id" {
  description = "GitHub environment variable AZURE_CLIENT_ID for this environment (Lesson 13)."
  value       = azurerm_user_assigned_identity.deploy.client_id
}

output "env_file" {
  description = "The configuration file this apply wrote."
  value       = local_file.env.filename
}
