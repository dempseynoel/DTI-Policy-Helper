variable "environment" {
  description = "dev, test or prod: which entry of deploy/environments.yaml to build."
  type        = string

  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "environment must be dev, test or prod."
  }
}

variable "config" {
  description = "deploy/environments.yaml, decoded. Every setting comes from here."
  type        = any

  validation {
    condition     = contains(keys(var.config.environments), var.environment)
    error_message = "deploy/environments.yaml has no entry for this environment."
  }
}

variable "env_file" {
  description = "Where to write this environment's generated configuration (deploy/<env>.env)."
  type        = string
}
