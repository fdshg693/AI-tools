output "server_ip_address" {
  value       = sakura_server.ai_logs.ip_address
  description = "作成したVMのグローバルIPアドレス"
}
