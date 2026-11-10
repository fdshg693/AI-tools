terraform {
  required_providers {
    sakura = {
      # terraform-provider-sakura は Terraform 1.11 以降が必要
      source = "sacloud/sakura"
      # 2026-07時点の最新は 3.12.5。適用前に registry.terraform.io で最新版を確認すること。
      version = "~> 3"
    }
  }
}

provider "sakura" {
  token  = var.sakura_token
  secret = var.sakura_secret
  zone   = var.zone
}
