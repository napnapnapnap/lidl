terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
  backend "gcs" {
    # Bucket is passed via -backend-config in CI and local init.
    # See deploy-infra.yml and the local init instructions below.
    prefix = "terraform/lidl"
  }
}

provider "google" {
  project = var.project_id
  zone    = var.zone
}

locals {
  region = join("-", slice(split("-", var.zone), 0, 2))
}

resource "google_compute_address" "vm_ip" {
  name   = "lidl-bot-ip"
  region = local.region
}

resource "google_compute_firewall" "ssh" {
  name    = "lidl-bot-allow-ssh"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["lidl-bot"]
}

resource "google_compute_disk" "data" {
  count = var.existing_data_disk_name == "" ? 1 : 0
  name  = "lidl-bot-data"
  size  = 10
  type  = "pd-standard"
  zone  = var.zone
}

data "google_compute_disk" "existing" {
  count = var.existing_data_disk_name != "" ? 1 : 0
  name  = var.existing_data_disk_name
  zone  = var.zone
}

locals {
  data_disk_self_link = (
    var.existing_data_disk_name != ""
    ? data.google_compute_disk.existing[0].self_link
    : google_compute_disk.data[0].self_link
  )
}

resource "google_compute_instance" "vm" {
  name         = "lidl-bot"
  machine_type = "e2-micro"
  zone         = var.zone
  tags         = ["lidl-bot"]

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 10
    }
  }

  attached_disk {
    source      = local.data_disk_self_link
    device_name = "data"
    mode        = "READ_WRITE"
  }

  network_interface {
    network = "default"
    access_config {
      nat_ip = google_compute_address.vm_ip.address
    }
  }

  metadata = {
    ssh-keys       = "debian:${var.ssh_public_key}"
    startup-script = file("${path.module}/startup.sh")
  }

  # startup-script changes are ignored to avoid VM replacement on every plan.
  # To apply an updated startup.sh: SSH in and run it manually, or
  # reset the VM via: gcloud compute instances reset lidl-bot --zone=us-west1-a
  lifecycle {
    ignore_changes = [metadata["startup-script"]]
  }
}
