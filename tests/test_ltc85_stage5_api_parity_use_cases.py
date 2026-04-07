from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.application.contracts import ErrorCode
from app.application.use_cases.qa_api import list_qa_journal_result
from app.application.use_cases.read_api import (
    list_master_roles_catalog_result,
    list_post_processing_tools_result,
    list_pre_processing_tools_result,
    list_skills_result,
    list_team_roles_result,
)
from app.application.use_cases.write_api import MasterRolePatchRequest, patch_master_role_result
from app.role_catalog import RoleCatalog
from app.storage import Storage
from prepost_processing_sdk.contract import PrePostProcessingSpec
from skills_sdk.contract import SkillSpec


class _FakeRegistry:
    def __init__(self, specs: list[object], manifest_by_id: dict[str, dict[str, object]]) -> None:
        self._specs = list(specs)
        self._manifest_by_id = dict(manifest_by_id)

    def list_specs(self) -> list[object]:
        return list(self._specs)

    def get(self, item_id: str):
        manifest = self._manifest_by_id.get(str(item_id))
        if manifest is None:
            return None
        return SimpleNamespace(manifest=manifest)


class LTC85Stage5ApiParityUseCasesTests(unittest.TestCase):
    def test_registry_lists_and_team_roles_enrichment(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "ltc85_roles.sqlite3")
            with storage.transaction(immediate=True):
                group = storage.upsert_group(-9850, "ltc85")
                role = storage.upsert_role(
                    role_name="dev",
                    description="d",
                    base_system_prompt="sp",
                    extra_instruction="ei",
                    llm_model=None,
                    is_active=True,
                )
                storage.ensure_group_role(group.group_id, role.role_id)
                team_id = int(group.team_id or 0)
                team_role_id = int(storage.resolve_team_role_id(team_id, role.role_id, ensure_exists=True) or 0)
                storage.upsert_role_skill_for_team_role(team_role_id, "s2", enabled=True, config=None)
                storage.upsert_role_skill_for_team_role(team_role_id, "s1", enabled=True, config=None)
                storage.upsert_role_skill_for_team_role(team_role_id, "s3", enabled=False, config=None)
                storage.upsert_role_prepost_processing_for_team_role(team_role_id, "p2", enabled=True, config=None)
                storage.upsert_role_prepost_processing_for_team_role(team_role_id, "p1", enabled=True, config=None)
                storage.upsert_role_prepost_processing_for_team_role(team_role_id, "p3", enabled=False, config=None)

            runtime = SimpleNamespace(
                skills_registry=_FakeRegistry(
                    [
                        SkillSpec(skill_id="s1", name="Skill 1", version="1"),
                        SkillSpec(skill_id="s2", name="Skill 2", version="1"),
                        SkillSpec(skill_id="s3", name="Skill 3", version="1"),
                    ],
                    {
                        "s1": {"entrypoint": "skills.a:make"},
                        "s2": {"entrypoint": "skills.b:make"},
                        "s3": {"entrypoint": "skills.c:make"},
                    },
                ),
                prepost_processing_registry=_FakeRegistry(
                    [
                        PrePostProcessingSpec(prepost_processing_id="p1", name="PrePost 1", version="1"),
                        PrePostProcessingSpec(prepost_processing_id="p2", name="PrePost 2", version="1"),
                        PrePostProcessingSpec(prepost_processing_id="p3", name="PrePost 3", version="1"),
                    ],
                    {
                        "p1": {"entrypoint": "prepost.a:make"},
                        "p2": {"entrypoint": "prepost.b:make"},
                        "p3": {"entrypoint": "prepost.c:make"},
                    },
                ),
            )

            skills = list_skills_result(runtime)
            pre = list_pre_processing_tools_result(runtime)
            post = list_post_processing_tools_result(runtime)
            self.assertTrue(skills.is_ok and skills.value is not None)
            self.assertTrue(pre.is_ok and pre.value is not None)
            self.assertTrue(post.is_ok and post.value is not None)
            self.assertEqual([item.id for item in skills.value], ["s1", "s2", "s3"])
            self.assertEqual(skills.value[0].source, "skills.a:make")
            self.assertEqual([item.id for item in pre.value], ["p1", "p2", "p3"])
            self.assertEqual([item.id for item in post.value], ["p1", "p2", "p3"])

            roles = list_team_roles_result(storage, team_id=team_id, runtime=runtime)
            self.assertTrue(roles.is_ok and roles.value is not None and roles.value)
            view = roles.value[0]
            self.assertEqual([item.id for item in view.skills], ["s1", "s2"])
            self.assertEqual([item.id for item in view.pre_processing_tools], ["p1", "p2"])
            self.assertEqual([item.id for item in view.post_processing_tools], ["p1", "p2"])

    def test_master_roles_catalog_shape_and_include_inactive_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            catalog_dir = root / "roles"
            catalog_dir.mkdir(parents=True, exist_ok=True)
            (catalog_dir / "dev.json").write_text(
                '{"schema_version":1,"role_name":"dev","description":"Developer","base_system_prompt":"sp","extra_instruction":"ei","llm_model":"gpt","is_active":true}\n',
                encoding="utf-8",
            )
            (catalog_dir / "ops.json").write_text(
                '{"schema_version":1,"role_name":"ops","description":"Ops","base_system_prompt":"sp2","extra_instruction":"ei2","llm_model":"gpt","is_active":false}\n',
                encoding="utf-8",
            )
            storage = Storage(root / "ltc85_catalog.sqlite3")
            with storage.transaction(immediate=True):
                storage.upsert_role("dev", "d", "sp", "ei", "gpt", True)
                storage.upsert_role("ops", "d2", "sp2", "ei2", "gpt", True)
            runtime = SimpleNamespace(role_catalog=RoleCatalog.load(catalog_dir))

            all_items = list_master_roles_catalog_result(runtime, storage, include_inactive=False, limit=50, offset=0)
            all_items_inc = list_master_roles_catalog_result(runtime, storage, include_inactive=True, limit=50, offset=0)
            self.assertTrue(all_items.is_ok and all_items.value is not None)
            self.assertTrue(all_items_inc.is_ok and all_items_inc.value is not None)
            self.assertEqual(all_items.value.total, all_items_inc.value.total)
            self.assertTrue(all(item.role_id > 0 for item in all_items.value.items))
            self.assertTrue(any(item.role_name == "ops" for item in all_items.value.items))

    def test_patch_master_role_conflict_and_update(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "ltc85_patch.sqlite3")
            with storage.transaction(immediate=True):
                dev = storage.upsert_role("dev", "d", "sp", "ei", "gpt", True)
                storage.upsert_role("ops", "d2", "sp2", "ei2", "gpt", True)

            conflict = patch_master_role_result(
                storage,
                role_id=dev.role_id,
                patch=MasterRolePatchRequest(role_name="ops"),
            )
            self.assertTrue(conflict.is_error)
            self.assertEqual(conflict.error.code if conflict.error else "", ErrorCode.CONFLICT_ALREADY_EXISTS.value)

            updated = patch_master_role_result(
                storage,
                role_id=dev.role_id,
                patch=MasterRolePatchRequest(system_prompt="new-sp", extra_instruction="new-ei", llm_model="new-model"),
            )
            self.assertTrue(updated.is_ok and updated.value is not None)
            self.assertEqual(updated.value.role_id, dev.role_id)
            self.assertEqual(updated.value.system_prompt, "new-sp")
            self.assertEqual(updated.value.extra_instruction, "new-ei")
            self.assertEqual(updated.value.llm_model, "new-model")

    def test_qa_journal_includes_answer_id_only_for_answered(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "ltc85_qa.sqlite3")
            with storage.transaction(immediate=True):
                group = storage.upsert_group(-9851, "qa")
                role = storage.upsert_role("dev", "d", "sp", "ei", None, True)
                storage.ensure_group_role(group.group_id, role.role_id)
                team_id = int(group.team_id or 0)
                team_role_id = int(storage.resolve_team_role_id(team_id, role.role_id, ensure_exists=True) or 0)

                q1 = storage.create_question(
                    question_id="q1",
                    thread_id="t1",
                    team_id=team_id,
                    created_by_user_id=700,
                    target_team_role_id=team_role_id,
                    text="first",
                )
                storage.transition_question_status(question_id=q1.question_id, status="queued")
                storage.transition_question_status(question_id=q1.question_id, status="in_progress")
                storage.create_answer(
                    answer_id="a1",
                    question_id=q1.question_id,
                    thread_id=q1.thread_id,
                    team_id=q1.team_id,
                    team_role_id=team_role_id,
                    role_name="dev",
                    text="ok",
                )
                storage.transition_question_status(question_id=q1.question_id, status="answered")

                storage.create_question(
                    question_id="q2",
                    thread_id="t2",
                    team_id=team_id,
                    created_by_user_id=700,
                    target_team_role_id=team_role_id,
                    text="second",
                )

            result = list_qa_journal_result(storage, team_id=team_id, limit=50)
            self.assertTrue(result.is_ok and result.value is not None)
            by_id = {item.question_id: item.answer_id for item in result.value.items}
            self.assertEqual(by_id.get("q1"), "a1")
            self.assertIsNone(by_id.get("q2"))


if __name__ == "__main__":
    unittest.main()
