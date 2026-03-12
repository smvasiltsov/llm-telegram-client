---
title: 30.2 Provider Config Template
confluence:
  parent_page_id: 98699
  space_id: 5144580
  page_id: 5406759
  parent_doc_path: 30-llm-integration/_index.md
  local_id: 30-2-provider-config-template
  parent_local_id: 30-llm-integration
sync:
  mode: publish
  delete_policy: keep
doc:
  status: draft
---
# 30.2 Provider Config Template

## Configuration Location
Provider definitions are JSON files under `llm_providers/`.
Each file must describe one provider instance.

## Required Core Fields
A functional provider config includes:
- `id`
- `label`
- `base_url`
- `adapter` (currently `generic`)
- `capabilities`
- `auth`
- `endpoints.send_message`
- `models`

## Canonical Structure
```json
{
  "id": "provider-id",
  "label": "Provider Label",
  "base_url": "https://api.example.com",
  "tls": { "ca_cert_path": null },
  "adapter": "generic",
  "capabilities": {
    "list_sessions": false,
    "create_session": false,
    "rename_session": false,
    "model_select": true
  },
  "auth": { "mode": "none" },
  "user_fields": {},
  "endpoints": {
    "send_message": {
      "path": "/send",
      "method": "POST",
      "request": {
        "body_template": { "prompt": "{{content}}" }
      },
      "response": { "content_path": "answer" }
    }
  },
  "history": { "enabled": false, "max_messages": 20 },
  "models": [{ "id": "default", "label": "Default" }]
}
```

## Template Placeholders
LTC payload rendering supports:
- `{{session_id}}`
- `{{content}}`
- `{{model}}`
- `{{messages}}`
- `{{name}}`
- `[[[field_key]]]` for provider user fields.

## Endpoint Mapping Notes
- `request.body_template` controls outbound payload shape.
- `request.headers` can be templated the same way.
- `response.content_path` points to assistant text in JSON responses.
- streaming responses use stream-specific response config fields.

## Validation Guidance
Before activating a provider:
- verify model ids are declared,
- verify all required endpoint paths exist,
- verify placeholders map to actual runtime values,
- verify capability flags match real API behavior.
