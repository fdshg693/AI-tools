data "sakura_archive" "almalinux" {
  os_type = "almalinux9"
}

resource "sakura_disk" "ai_logs" {
  name              = "ai-logs-os-disk"
  size              = 20
  plan              = "ssd"
  connector         = "virtio"
  source_archive_id = data.sakura_archive.almalinux.id
}

resource "sakura_server" "ai_logs" {
  name        = "ai-logs"
  disks       = [sakura_disk.ai_logs.id]
  core        = 1
  memory      = 1
  description = "AI logs infra MVP (OTel Collector + Loki + Grafana)"
  tags        = ["ai-logs", "mvp"]

  network_interface = [{
    upstream = "shared"
  }]

  disk_edit_parameter = {
    hostname        = "ai-logs"
    ssh_keys        = [var.ssh_public_key]
    disable_pw_auth = true
  }
}
