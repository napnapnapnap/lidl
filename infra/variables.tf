variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "zone" {
  description = "GCE zone"
  type        = string
  default     = "us-west1-a"
}

variable "existing_data_disk_name" {
  description = "Name of an existing persistent disk to attach. Empty string creates a new 10 GB pd-standard disk."
  type        = string
  default     = ""
}

variable "ssh_public_key" {
  description = "SSH public key content added to the VM's authorized_keys (debian user)"
  type        = string
}
