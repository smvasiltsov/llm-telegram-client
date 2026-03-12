from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from skills_sdk.contract import SkillContext, SkillResult, SkillSpec
from skills.confluence_auto_sync.frontmatter_rewrite import (
    FrontmatterUpdate,
    rewrite_frontmatter_ids,
)
from skills.confluence_auto_sync.parser import ParsedDoc, parse_confluence_docs
from skills.confluence_auto_sync.publisher import ConfluencePublisher, PublishOptions
from skills.confluence_auto_sync.state import PublishState, load_publish_state
from skills.confluence_auto_sync.tree import ResolvedDoc, build_publish_tree


SUPPORTED_OPERATIONS: tuple[str, ...] = ("mcp_publish",)
DEFAULT_TIMEOUT_SEC = 30
DEFAULT_SKILL_TIMEOUT_SEC = 300
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_SLEEP_SEC = 3.0
DEFAULT_MAX_BATCH = 20
DEFAULT_CONFIG_FILENAME = "config.json"

CONFLUENCE_AUTO_SYNC_DESCRIPTION = (
    "Confluence auto sync skill for idempotent incremental publish from repository docs to Confluence. "
    "Only one operation is supported: mcp_publish. "
    "mcp_publish scans markdown docs under docs_root, validates front matter, resolves parents, "
    "computes local diff via state file, and performs create/update/archive decisions. "
    "Required inputs are repo_path, docs_root, mode, and space_id. "
    "mode is either dry-run (plan only) or apply (write changes). "
    "Optional overrides: space_id, root_page_id (MCP arguments have higher priority than front matter/_meta defaults). "
    "Optional behavior flags: changed_only, fail_on_drift, safe_mode, rewrite_frontmatter_ids. "
    "safe_mode checks drift against remote changes; with fail_on_drift=false drift is skipped with warning. "
    "rewrite_frontmatter_ids persists created page ids back into markdown front matter."
)

CONFLUENCE_AUTO_SYNC_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "operation": {"type": "string", "enum": list(SUPPORTED_OPERATIONS)},
        "repo_path": {"type": "string", "minLength": 1},
        "docs_root": {"type": "string", "minLength": 1},
        "space_id": {"oneOf": [{"type": "string", "minLength": 1}, {"type": "integer"}]},
        "root_page_id": {"oneOf": [{"type": "string", "minLength": 1}, {"type": "integer"}]},
        "mode": {"type": "string", "enum": ["dry-run", "apply"]},
        "changed_only": {"type": "boolean"},
        "fail_on_drift": {"type": "boolean"},
        "safe_mode": {"type": "boolean"},
        "rewrite_frontmatter_ids": {"type": "boolean"},
    },
    "required": ["operation", "repo_path", "docs_root", "mode", "space_id"],
    "oneOf": [
        {
            "properties": {"operation": {"const": "mcp_publish"}},
            "required": ["operation", "repo_path", "docs_root", "mode", "space_id"],
        }
    ],
    "additionalProperties": True,
}


class ConfluenceAutoSyncSkill:
    def describe(self) -> SkillSpec:
        timeout_sec = self._load_skill_timeout_from_default_profile()
        return SkillSpec(
            skill_id="confluence_auto_sync",
            name="Confluence Auto Sync",
            version="0.1.0",
            description=CONFLUENCE_AUTO_SYNC_DESCRIPTION,
            input_schema=CONFLUENCE_AUTO_SYNC_INPUT_SCHEMA,
            mode="read_write",
            timeout_sec=timeout_sec,
        )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        if not isinstance(config, dict):
            return ["config must be an object"]

        config_path = config.get("config_path")
        if config_path is not None and (not isinstance(config_path, str) or not config_path.strip()):
            return ["config.config_path must be a non-empty string when provided"]

        try:
            profile = self._load_profile(config)
        except ValueError as exc:
            return [str(exc)]

        errors: list[str] = []
        confluence = profile.get("confluence")
        publish = profile.get("publish")
        state = profile.get("state")
        skill = profile.get("skill")

        if not isinstance(confluence, dict):
            errors.append("profile.confluence must be an object")
        if not isinstance(publish, dict):
            errors.append("profile.publish must be an object")
        if not isinstance(state, dict):
            errors.append("profile.state must be an object")
        if skill is not None and not isinstance(skill, dict):
            errors.append("profile.skill must be an object when provided")
        if errors:
            return errors

        url = confluence.get("url")
        if not isinstance(url, str) or not url.strip():
            errors.append("profile.confluence.url is required")
        elif not self._is_valid_confluence_url(url.strip()):
            errors.append("profile.confluence.url must be in format https://<site>.atlassian.net/wiki")

        username = confluence.get("username")
        if not isinstance(username, str) or not username.strip():
            errors.append("profile.confluence.username is required")

        token = confluence.get("token")
        if not isinstance(token, str) or not token.strip():
            errors.append("profile.confluence.token is required")

        timeout_sec = self._parse_int(confluence.get("timeout_sec"), default=DEFAULT_TIMEOUT_SEC)
        if timeout_sec < 5 or timeout_sec > 120:
            errors.append("profile.confluence.timeout_sec must be between 5 and 120")

        retry_attempts = self._parse_int(confluence.get("retry_attempts"), default=DEFAULT_RETRY_ATTEMPTS)
        if retry_attempts < 1 or retry_attempts > 10:
            errors.append("profile.confluence.retry_attempts must be between 1 and 10")

        retry_sleep_sec = self._parse_float(confluence.get("retry_sleep_sec"), default=DEFAULT_RETRY_SLEEP_SEC)
        if retry_sleep_sec < 0 or retry_sleep_sec > 30:
            errors.append("profile.confluence.retry_sleep_sec must be between 0 and 30")

        repo_path = publish.get("repo_path")
        if not isinstance(repo_path, str) or not repo_path.strip():
            errors.append("profile.publish.repo_path is required")

        docs_root = publish.get("docs_root")
        if not isinstance(docs_root, str) or not docs_root.strip():
            errors.append("profile.publish.docs_root is required")

        dry_run_default = publish.get("dry_run_default")
        if not isinstance(dry_run_default, bool):
            errors.append("profile.publish.dry_run_default must be boolean")

        max_batch = self._parse_int(publish.get("max_batch"), default=DEFAULT_MAX_BATCH)
        if max_batch < 1 or max_batch > 500:
            errors.append("profile.publish.max_batch must be between 1 and 500")

        changed_only = publish.get("update_if_changed_only")
        if not isinstance(changed_only, bool):
            errors.append("profile.publish.update_if_changed_only must be boolean")

        markdown_mode = publish.get("markdown_mode")
        if markdown_mode not in {"storage"}:
            errors.append("profile.publish.markdown_mode must be 'storage'")

        state_file = state.get("file")
        if not isinstance(state_file, str) or not state_file.strip():
            errors.append("profile.state.file is required")

        if isinstance(skill, dict):
            skill_timeout_sec = self._parse_int(skill.get("timeout_sec"), default=DEFAULT_SKILL_TIMEOUT_SEC)
            if skill_timeout_sec < 30 or skill_timeout_sec > 3600:
                errors.append("profile.skill.timeout_sec must be between 30 and 3600")

        return errors

    def run(self, ctx: SkillContext, arguments: dict[str, Any], config: dict[str, Any]) -> SkillResult:
        _ = ctx
        if not isinstance(arguments, dict):
            return SkillResult(ok=False, error="arguments must be an object")

        config_errors = self.validate_config(config)
        if config_errors:
            return SkillResult(ok=False, error="; ".join(config_errors))

        operation_raw = arguments.get("operation")
        if not isinstance(operation_raw, str) or not operation_raw.strip():
            return SkillResult(ok=False, error="arguments.operation is required")
        operation = operation_raw.strip()

        handlers: dict[str, Callable[[dict[str, Any], dict[str, Any]], SkillResult]] = {
            "mcp_publish": self._mcp_publish,
        }
        handler = handlers.get(operation)
        if handler is None:
            return SkillResult(
                ok=False,
                error=f"arguments.operation is unsupported: {operation}",
                metadata={"supported_operations": list(SUPPORTED_OPERATIONS)},
            )
        return handler(arguments, config)

    def _resolve_config_path(self, config: dict[str, Any]) -> Path:
        raw_path = config.get("config_path")
        if isinstance(raw_path, str) and raw_path.strip():
            return Path(raw_path.strip()).expanduser()
        return Path(__file__).resolve().parent / DEFAULT_CONFIG_FILENAME

    def _load_profile(self, config: dict[str, Any]) -> dict[str, Any]:
        path = self._resolve_config_path(config)
        if not path.exists() or not path.is_file():
            raise ValueError(f"profile config file not found: {path}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid profile config JSON at {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"profile config must be a JSON object: {path}")
        return raw

    def _parse_int(self, value: Any, *, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

    def _parse_float(self, value: Any, *, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default

    def _load_skill_timeout_from_default_profile(self) -> int:
        default_path = Path(__file__).resolve().parent / DEFAULT_CONFIG_FILENAME
        try:
            raw = json.loads(default_path.read_text(encoding="utf-8"))
        except Exception:
            return DEFAULT_SKILL_TIMEOUT_SEC
        if not isinstance(raw, dict):
            return DEFAULT_SKILL_TIMEOUT_SEC
        skill = raw.get("skill")
        if not isinstance(skill, dict):
            return DEFAULT_SKILL_TIMEOUT_SEC
        timeout_sec = self._parse_int(skill.get("timeout_sec"), default=DEFAULT_SKILL_TIMEOUT_SEC)
        if timeout_sec < 30 or timeout_sec > 3600:
            return DEFAULT_SKILL_TIMEOUT_SEC
        return timeout_sec

    def _is_valid_confluence_url(self, value: str) -> bool:
        parsed = urlparse(value)
        if parsed.scheme != "https":
            return False
        if not parsed.netloc.endswith(".atlassian.net"):
            return False
        return parsed.path.rstrip("/") == "/wiki"

    def _mcp_publish(self, arguments: dict[str, Any], config: dict[str, Any]) -> SkillResult:
        profile = self._load_profile(config)
        publish_profile = profile.get("publish", {}) if isinstance(profile, dict) else {}
        state_profile = profile.get("state", {}) if isinstance(profile, dict) else {}

        repo_path_raw = arguments.get("repo_path")
        docs_root_raw = arguments.get("docs_root")
        mode_raw = arguments.get("mode")
        space_id_raw = arguments.get("space_id")

        if not isinstance(repo_path_raw, str) or not repo_path_raw.strip():
            return SkillResult(ok=False, error="mcp_publish: arguments.repo_path is required")
        if not isinstance(docs_root_raw, str) or not docs_root_raw.strip():
            return SkillResult(ok=False, error="mcp_publish: arguments.docs_root is required")
        if mode_raw not in {"dry-run", "apply"}:
            return SkillResult(ok=False, error="mcp_publish: arguments.mode must be 'dry-run' or 'apply'")
        if self._normalize_id(space_id_raw) is None:
            return SkillResult(ok=False, error="mcp_publish: arguments.space_id is required")

        repo_path = str(Path(repo_path_raw).expanduser().resolve())
        docs_root = docs_root_raw.strip()
        mode = mode_raw
        changed_only = self._parse_bool(arguments.get("changed_only"), default=False)
        safe_mode = self._parse_bool(arguments.get("safe_mode"), default=False)
        fail_on_drift = self._parse_bool(arguments.get("fail_on_drift"), default=False)
        rewrite_ids = self._parse_bool(arguments.get("rewrite_frontmatter_ids"), default=False)
        update_if_changed_only = self._parse_bool(
            publish_profile.get("update_if_changed_only"),
            default=True,
        )
        max_batch = self._parse_int(publish_profile.get("max_batch"), default=DEFAULT_MAX_BATCH)

        output = {
            "created": [],
            "updated": [],
            "skipped": [],
            "errors": [],
            "warnings": [],
            "summary": {"created": 0, "updated": 0, "skipped": 0, "errors": 0, "warnings": 0},
        }

        parse_result = parse_confluence_docs(repo_path=repo_path, docs_root=docs_root)
        if parse_result.meta is None:
            output["errors"].append({"path": docs_root, "error": "missing or invalid _meta.yaml"})
        for item in parse_result.errors:
            output["errors"].append({"path": docs_root, "error": item})

        meta_data = dict(parse_result.meta.data) if parse_result.meta is not None else {}
        confluence_meta = meta_data.get("confluence")
        if not isinstance(confluence_meta, dict):
            confluence_meta = {}
            meta_data["confluence"] = confluence_meta

        space_id_override = self._normalize_id(arguments.get("space_id"))
        root_page_override = self._normalize_id(arguments.get("root_page_id"))
        if root_page_override:
            confluence_meta["root_page_id"] = root_page_override

        docs_for_tree = self._apply_mcp_overrides(
            docs=parse_result.docs,
            space_id_override=space_id_override,
            root_page_override=root_page_override,
        )

        tree_result = build_publish_tree(
            docs=docs_for_tree,
            meta_data=meta_data,
            prefer_root_for_top_level=bool(root_page_override),
        )
        for item in tree_result.errors:
            output["errors"].append({"path": docs_root, "error": item})

        state_file = state_profile.get("file")
        if not isinstance(state_file, str) or not state_file.strip():
            output["errors"].append({"path": docs_root, "error": "profile.state.file is required"})
            self._finalize_summary(output)
            return SkillResult(ok=False, output=output, error="mcp_publish: invalid state profile")

        state_path = Path(state_file.strip())
        if not state_path.is_absolute():
            state_path = Path(repo_path) / state_path

        try:
            publish_state = load_publish_state(state_path)
        except ValueError as exc:
            output["errors"].append({"path": str(state_path), "error": str(exc)})
            self._finalize_summary(output)
            return SkillResult(ok=False, output=output, error="mcp_publish: failed to load state")

        docs_with_fingerprint = self._attach_publish_fingerprint(tree_result.ordered_docs)
        docs_for_publish = self._hydrate_page_ids_from_state(docs_with_fingerprint, publish_state)

        if max_batch > 0 and len(docs_for_publish) > max_batch:
            batches = (len(docs_for_publish) + max_batch - 1) // max_batch
            output["warnings"].append(
                {
                    "path": docs_root,
                    "warning": f"processing in {batches} batches (max_batch={max_batch})",
                }
            )

        options = PublishOptions(
            mode=mode,
            changed_only=changed_only,
            update_if_changed_only=update_if_changed_only,
            safe_mode=safe_mode,
            fail_on_drift=fail_on_drift,
            rewrite_frontmatter_ids=rewrite_ids,
            strict_parent_update=bool(root_page_override),
            target_space_id=space_id_override,
        )
        publisher = ConfluencePublisher(profile=profile)
        all_active_paths = {item.doc_path for item in docs_for_publish}
        if max_batch > 0:
            chunks = [
                docs_for_publish[i : i + max_batch]
                for i in range(0, len(docs_for_publish), max_batch)
            ]
        else:
            chunks = [docs_for_publish]

        for idx, chunk in enumerate(chunks):
            publish_result = publisher.publish(
                docs=chunk,
                state=publish_state,
                options=options,
                process_orphans=(idx == len(chunks) - 1),
                all_active_doc_paths=all_active_paths,
            )
            publish_output = publish_result.to_output()
            output["created"].extend(publish_output.get("created", []))
            output["updated"].extend(publish_output.get("updated", []))
            output["skipped"].extend(publish_output.get("skipped", []))
            output["errors"].extend(publish_output.get("errors", []))
            output["warnings"].extend(publish_output.get("warnings", []))

        if rewrite_ids and mode == "apply":
            rewrite_updates: list[FrontmatterUpdate] = []
            docs_by_path = {doc.doc_path: doc for doc in docs_for_publish}
            for item in (output["created"] + output["updated"]):
                page_id = self._normalize_id(item.get("page_id"))
                space_id = self._normalize_id(item.get("space_id"))
                path = item.get("path")
                if not page_id or not isinstance(path, str):
                    continue
                doc = docs_by_path.get(path)
                if doc is None:
                    continue
                # Keep parent topology source-of-truth in local references
                # (parent_local_id/parent_doc_path). Persist parent_page_id only
                # when it was explicitly authored in front matter.
                parent_page_id = None
                if doc.parent_source == "explicit":
                    parent_page_id = self._normalize_id(item.get("parent_page_id"))
                rewrite_updates.append(
                    FrontmatterUpdate(
                        file_path=doc.abs_path,
                        page_id=page_id,
                        space_id=space_id,
                        parent_page_id=parent_page_id,
                        doc_path=doc.doc_path,
                    )
                )
            if rewrite_updates:
                rewrite_result = rewrite_frontmatter_ids(rewrite_updates)
                for skipped in rewrite_result.skipped:
                    output["skipped"].append(
                        {"path": skipped.path, "page_id": skipped.page_id, "reason": f"frontmatter: {skipped.reason}"}
                    )
                for error_item in rewrite_result.errors:
                    output["errors"].append(
                        {"path": error_item.path, "page_id": error_item.page_id, "error": f"frontmatter: {error_item.error}"}
                    )

        if mode == "apply":
            try:
                publish_state.save()
            except OSError as exc:
                output["errors"].append({"path": str(state_path), "error": f"state save failed: {exc}"})

        self._finalize_summary(output)
        return SkillResult(ok=output["summary"]["errors"] == 0, output=output)

    def _finalize_summary(self, output: dict[str, Any]) -> None:
        output["summary"] = {
            "created": len(output["created"]),
            "updated": len(output["updated"]),
            "skipped": len(output["skipped"]),
            "errors": len(output["errors"]),
            "warnings": len(output["warnings"]),
        }

    def _parse_bool(self, value: Any, *, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        return default

    def _normalize_id(self, value: Any) -> str | None:
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _hydrate_page_ids_from_state(self, docs: list[ResolvedDoc], state: PublishState) -> list[ResolvedDoc]:
        hydrated: list[ResolvedDoc] = []
        for doc in docs:
            page_id = self._normalize_id(doc.confluence.get("page_id"))
            if page_id:
                hydrated.append(doc)
                continue
            existing = state.get(doc.doc_path)
            if existing is None or not existing.page_id:
                hydrated.append(doc)
                continue
            confluence = dict(doc.confluence)
            confluence["page_id"] = existing.page_id
            hydrated.append(
                ResolvedDoc(
                    doc_path=doc.doc_path,
                    abs_path=doc.abs_path,
                    folder_path=doc.folder_path,
                    is_index=doc.is_index,
                    title=doc.title,
                    body_markdown=doc.body_markdown,
                    content_hash=doc.content_hash,
                    confluence=confluence,
                    sync=dict(doc.sync),
                    effective_space_id=doc.effective_space_id,
                    resolved_parent_page_id=doc.resolved_parent_page_id,
                    resolved_parent_doc_path=doc.resolved_parent_doc_path,
                    parent_source=doc.parent_source,
                )
            )
        return hydrated

    def _attach_publish_fingerprint(self, docs: list[ResolvedDoc]) -> list[ResolvedDoc]:
        fingerprinted: list[ResolvedDoc] = []
        for doc in docs:
            base = doc.content_hash
            parent = doc.resolved_parent_page_id or ""
            raw = f"{base}|space={doc.effective_space_id}|parent={parent}|source={doc.parent_source}"
            parent_doc_path = doc.resolved_parent_doc_path or ""
            raw = f"{raw}|parent_doc={parent_doc_path}"
            combined = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            fingerprinted.append(
                ResolvedDoc(
                    doc_path=doc.doc_path,
                    abs_path=doc.abs_path,
                    folder_path=doc.folder_path,
                    is_index=doc.is_index,
                    title=doc.title,
                    body_markdown=doc.body_markdown,
                    content_hash=combined,
                    confluence=dict(doc.confluence),
                    sync=dict(doc.sync),
                    effective_space_id=doc.effective_space_id,
                    resolved_parent_page_id=doc.resolved_parent_page_id,
                    resolved_parent_doc_path=doc.resolved_parent_doc_path,
                    parent_source=doc.parent_source,
                )
            )
        return fingerprinted

    def _apply_mcp_overrides(
        self,
        *,
        docs: list[ParsedDoc],
        space_id_override: str | None,
        root_page_override: str | None,
    ) -> list[ParsedDoc]:
        if not space_id_override and not root_page_override:
            return docs

        overridden: list[ParsedDoc] = []
        for doc in docs:
            confluence = dict(doc.confluence)
            effective_space_id = doc.effective_space_id

            if space_id_override:
                confluence["space_id"] = space_id_override
                effective_space_id = space_id_override

            overridden.append(
                ParsedDoc(
                    doc_path=doc.doc_path,
                    abs_path=doc.abs_path,
                    folder_path=doc.folder_path,
                    is_index=doc.is_index,
                    title=doc.title,
                    body_markdown=doc.body_markdown,
                    content_hash=doc.content_hash,
                    confluence=confluence,
                    sync=dict(doc.sync),
                    effective_space_id=effective_space_id,
                )
            )
        return overridden


def create_skill() -> ConfluenceAutoSyncSkill:
    return ConfluenceAutoSyncSkill()
