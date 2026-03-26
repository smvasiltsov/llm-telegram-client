# Interface SDK

`interfaces_sdk` defines the public contract for external interface modules.

## What To Implement

Each interface module must expose `create_adapter(core_port, runtime, config)`.

The returned adapter must provide:
- `interface_id: str`
- `async start() -> None`
- `async stop() -> None`

## Minimal Adapter Skeleton

Use `interfaces_sdk/template_adapter.py` as the starting point.

## Validation

Run contract validation for a module:

```bash
python3 -m scripts.interface_sdk_smoke interfaces_sdk.template_adapter replace_me
```

If output is `OK`, the module satisfies the adapter contract used by runtime loader.
