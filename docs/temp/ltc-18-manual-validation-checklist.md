# LTC-18 Manual Validation Checklist

## 1) Runtime Status in UI
- Open `/groups`.
- Confirm each role row displays `FREE` or `BUSY` runtime state.
- Open role card and verify busy preview is shown when role is busy.

## 2) Busy/Free Semantics
- Trigger role request.
- While request is in-flight, role should be `BUSY`.
- After response is delivered to chat, role should return to `FREE`.

## 3) Lock Groups
- Open role card -> `Lock Groups`.
- Create new lock group.
- Add another role (same team or another team) to same lock group.
- While first role is busy, second role invocation should be blocked with busy message.

## 4) Preview Rules
- Preview length should be <= 100 chars.
- Preview should reflect user or skill-engine text only.
- No raw JSON/system/instruction fragments in UI preview.

## 5) Regression Smoke
- `/roles` and `/groups` callbacks still work.
- Regular role response flow unchanged for non-blocked roles.
- Session reset and role toggles remain functional.
