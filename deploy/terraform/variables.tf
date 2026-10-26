variable "region" {
  description = "Frankfurt keeps client data in Germany (StBerG § 62a and the firms' data processing agreements)."
  type        = string
  default     = "eu-central-1"
}

variable "environment" {
  type    = string
  default = "prod"
}

variable "name" {
  type    = string
  default = "kanzlei"
}

variable "domain_name" {
  description = "Public host name, e.g. abschluss.example.de. Its ACM certificate must already exist in the region."
  type        = string
}

variable "certificate_arn" {
  description = "ACM certificate for domain_name."
  type        = string
}

variable "image_tag" {
  description = "Tag of the api and web images in ECR (the git SHA CI pushed)."
  type        = string
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "db_multi_az" {
  type    = bool
  default = true
}

variable "api_desired_count" {
  type    = number
  default = 2
}

variable "document_retention_years" {
  description = "GoBD/AO § 147: invoices and other Buchungsbelege are kept 8 years (BEG IV). Object Lock in compliance mode: nobody can shorten it, not even the account root."
  type        = number
  default     = 8
}

variable "smtp_host" {
  description = "Mail relay for client questions (the outbox worker). Empty: the worker only logs."
  type        = string
  default     = ""
}

variable "llm_enabled" {
  description = "Let the model read PDFs the rules cannot. Only after the firm has signed its § 62a StBerG agreement; see config/llm.yaml."
  type        = bool
  default     = false
}

variable "oidc" {
  description = "The group's identity provider (e.g. Microsoft Entra ID). Null: no sign-in in front of the app; only for a demo with KANZLEI_DEMO_MODE."
  type = object({
    issuer                 = string
    authorization_endpoint = string
    token_endpoint         = string
    user_info_endpoint     = string
    client_id              = string
    client_secret          = string
  })
  default   = null
  sensitive = true
}

variable "demo_mode" {
  description = "Seeded demo with a person picker. Never together with real client data."
  type        = bool
  default     = false
}
