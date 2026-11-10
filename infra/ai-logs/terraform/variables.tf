variable "sakura_token" {
  type      = string
  sensitive = true
}

variable "sakura_secret" {
  type      = string
  sensitive = true
}

variable "zone" {
  type        = string
  default     = "is1a" # 石狩第1ゾーン
  description = "さくらのクラウドのゾーン"
}

variable "ssh_public_key" {
  type        = string
  description = "VMへのSSHログインに使う公開鍵の中身(例: ~/.ssh/ai_logs_ed25519.pub の内容)。disk_edit_parameter.ssh_keys に直接注入する"
}
