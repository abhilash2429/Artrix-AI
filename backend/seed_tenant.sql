INSERT INTO tenants (name, api_key_hash, vertical, config, domain_whitelist, is_active)
VALUES (
  'StyleCart Demo',
  '8780101ef427963d18101be650eaf77db6a07fb8d1393ce0c3313146cef61560',
  'ecommerce',
  '{"persona_name": "Aria", "persona_description": "Friendly support agent for StyleCart e-commerce", "escalation_threshold": 0.55, "auto_resolve_threshold": 0.80, "max_turns_before_escalation": 10, "allowed_topics": ["orders", "returns", "refunds", "delivery", "products"]}',
  ARRAY['http://localhost:3000'],
  true
);
