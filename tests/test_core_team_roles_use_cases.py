from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.llm_providers import ProviderConfig, ProviderUserField
from app.core.use_cases.team_roles import (
    bind_master_role_to_group,
    delete_team_role_binding,
    list_team_role_states,
    list_telegram_groups,
    reset_team_role_session,
    set_team_role_enabled,
    set_team_role_mode,
)
from app.storage import Storage


class CoreTeamRolesUseCasesTests(unittest.TestCase):
    def test_list_telegram_groups_is_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            storage.upsert_group(-1002, "B")
            storage.upsert_group(-1001, "A")

            groups = list_telegram_groups(storage)
            self.assertEqual([g.group_id for g in groups], [-1002, -1001])

    def test_role_state_mutations_and_delete_binding(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-1011, "g")
            team_id = int(group.team_id or 0)
            role = storage.upsert_role(
                role_name="core_uc_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            storage.bind_master_role_to_team(team_id, role.role_id)

            state = list_team_role_states(storage, group.group_id)[0]
            self.assertTrue(state.enabled)

            updated = set_team_role_enabled(storage, group_id=group.group_id, role_id=role.role_id, enabled=False)
            self.assertFalse(updated.enabled)

            updated, _ = set_team_role_mode(storage, group_id=group.group_id, role_id=role.role_id, mode="orchestrator")
            self.assertEqual(updated.mode, "orchestrator")

            runtime = SimpleNamespace(provider_registry={})
            deleted_name = delete_team_role_binding(runtime, storage, group_id=group.group_id, role_id=role.role_id, user_id=55)
            self.assertEqual(deleted_name, "core_uc_role")
            self.assertFalse(storage.get_team_role(team_id, role.role_id).is_active)

    def test_reset_team_role_session_clears_session(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-1021, "g")
            team_id = int(group.team_id or 0)
            role = storage.upsert_role(
                role_name="reset_uc_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            team_role, _ = storage.bind_master_role_to_team(team_id, role.role_id)
            team_role_id = int(team_role.team_role_id or 0)
            storage.save_user_role_session_by_team_role(telegram_user_id=77, team_role_id=team_role_id, session_id="s1")

            runtime = SimpleNamespace(default_provider_id="openai", provider_registry={})
            role_name = reset_team_role_session(runtime, storage, group_id=group.group_id, role_id=role.role_id, user_id=77)

            self.assertEqual(role_name, "reset_uc_role")
            self.assertIsNone(storage.get_user_role_session_by_team_role(77, team_role_id))

    def test_reset_team_role_session_clears_skills_root_dir_for_current_team_role(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-1023, "g")
            team_id = int(group.team_id or 0)
            role = storage.upsert_role(
                role_name="reset_uc_role_skills_root",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            team_role, _ = storage.bind_master_role_to_team(team_id, role.role_id)
            team_role_id = int(team_role.team_role_id or 0)
            storage.save_user_role_session_by_team_role(telegram_user_id=77, team_role_id=team_role_id, session_id="s1")
            storage.set_provider_user_value_by_team_role("skills", "root_dir", team_role_id, "/tmp/demo")

            runtime = SimpleNamespace(default_provider_id="openai", provider_registry={})
            role_name = reset_team_role_session(runtime, storage, group_id=group.group_id, role_id=role.role_id, user_id=77)

            self.assertEqual(role_name, "reset_uc_role_skills_root")
            self.assertIsNone(storage.get_provider_user_value_by_team_role("skills", "root_dir", team_role_id))

    def test_reset_team_role_session_blocks_legacy_fallback_for_current_team_role(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-1022, "g")
            team_id = int(group.team_id or 0)
            role = storage.upsert_role(
                role_name="reset_uc_role_fallback",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model="provider:model",
                is_active=True,
            )
            team_role, _ = storage.bind_master_role_to_team(team_id, role.role_id)
            team_role_id = int(team_role.team_role_id or 0)
            storage.save_user_role_session_by_team_role(telegram_user_id=77, team_role_id=team_role_id, session_id="s1")
            storage.set_provider_user_value("provider", "working_dir", role.role_id, "/legacy")
            storage.set_provider_user_value("provider", "root_dir", role.role_id, "/legacy-root")

            provider = ProviderConfig(
                provider_id="provider",
                label="Provider",
                base_url="http://example.invalid",
                tls_ca_cert_path=None,
                adapter="generic",
                capabilities={},
                auth_mode="none",
                endpoints={},
                models=[],
                history_enabled=False,
                history_limit=None,
                user_fields={
                    "working_dir": ProviderUserField(
                        key="working_dir",
                        prompt="wd",
                        scope="role",
                    ),
                    "root_dir": ProviderUserField(
                        key="root_dir",
                        prompt="rd",
                        scope="role",
                    ),
                },
            )
            runtime = SimpleNamespace(default_provider_id="provider", provider_registry={"provider": provider})
            role_name = reset_team_role_session(runtime, storage, group_id=group.group_id, role_id=role.role_id, user_id=77)

            self.assertEqual(role_name, "reset_uc_role_fallback")
            self.assertIsNone(storage.get_user_role_session_by_team_role(77, team_role_id))
            self.assertIsNone(
                storage.get_provider_user_value_by_team_role_or_role(
                    "provider",
                    "working_dir",
                    team_role_id=team_role_id,
                    role_id=role.role_id,
                )
            )
            self.assertIsNone(
                storage.get_provider_user_value_by_team_role_or_role(
                    "provider",
                    "root_dir",
                    team_role_id=team_role_id,
                    role_id=role.role_id,
                )
            )

    def test_bind_role_to_new_team_starts_without_team_scoped_role_field(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            g1 = storage.upsert_group(-1031, "g1")
            g2 = storage.upsert_group(-1032, "g2")
            team1 = int(g1.team_id or 0)
            team2 = int(g2.team_id or 0)
            role = storage.upsert_role(
                role_name="bind_scope_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model=None,
                is_active=True,
            )
            tr1, _ = storage.bind_master_role_to_team(team1, role.role_id)
            self.assertIsNotNone(tr1.team_role_id)
            storage.set_provider_user_value_by_team_role("provider", "working_dir", int(tr1.team_role_id or 0), "/team1")

            # Keep legacy value to validate temporary fallback behavior separately.
            storage.set_provider_user_value("provider", "working_dir", role.role_id, "/legacy")

            runtime = SimpleNamespace()
            bound_role_name, created = bind_master_role_to_group(
                runtime,
                storage,
                group_id=g2.group_id,
                role_name=role.role_name,
            )
            self.assertEqual(bound_role_name, role.role_name)
            self.assertTrue(created)

            tr2 = storage.get_team_role(team2, role.role_id)
            self.assertIsNotNone(tr2.team_role_id)
            team_scoped = storage.get_provider_user_value_by_team_role(
                "provider",
                "working_dir",
                int(tr2.team_role_id or 0),
            )
            self.assertIsNone(team_scoped)
            fallback_value = storage.get_provider_user_value_by_team_role_or_role(
                "provider",
                "working_dir",
                team_role_id=int(tr2.team_role_id or 0),
                role_id=role.role_id,
            )
            self.assertEqual(fallback_value, "/legacy")

    def test_remove_and_readd_role_in_same_group_clears_role_scoped_fields_and_blocks_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            storage = Storage(Path(td) / "test.sqlite3")
            group = storage.upsert_group(-1041, "g")
            team_id = int(group.team_id or 0)
            role = storage.upsert_role(
                role_name="remove_readd_scope_role",
                description="d",
                base_system_prompt="sp",
                extra_instruction="ei",
                llm_model="provider:model",
                is_active=True,
            )
            team_role, _ = storage.bind_master_role_to_team(team_id, role.role_id)
            old_team_role_id = int(team_role.team_role_id or 0)
            storage.set_provider_user_value_by_team_role("provider", "working_dir", old_team_role_id, "/team")
            storage.set_provider_user_value_by_team_role("skills", "root_dir", old_team_role_id, "/team-root")
            storage.set_provider_user_value("provider", "working_dir", role.role_id, "/legacy-working")
            storage.set_provider_user_value("provider", "root_dir", role.role_id, "/legacy-root")

            provider = ProviderConfig(
                provider_id="provider",
                label="Provider",
                base_url="http://example.invalid",
                tls_ca_cert_path=None,
                adapter="generic",
                capabilities={},
                auth_mode="none",
                endpoints={},
                models=[],
                history_enabled=False,
                history_limit=None,
                user_fields={
                    "working_dir": ProviderUserField(key="working_dir", prompt="wd", scope="role"),
                    "root_dir": ProviderUserField(key="root_dir", prompt="rd", scope="role"),
                },
            )
            runtime = SimpleNamespace(default_provider_id="provider", provider_registry={"provider": provider})

            deleted_name = delete_team_role_binding(
                runtime,
                storage,
                group_id=group.group_id,
                role_id=role.role_id,
                user_id=55,
            )
            self.assertEqual(deleted_name, "remove_readd_scope_role")

            rebound_name, created = bind_master_role_to_group(runtime, storage, group_id=group.group_id, role_name=role.role_name)
            self.assertEqual(rebound_name, role.role_name)
            self.assertTrue(created)

            rebound = storage.get_team_role(team_id, role.role_id)
            rebound_team_role_id = int(rebound.team_role_id or 0)
            self.assertIsNone(storage.get_provider_user_value_by_team_role("provider", "working_dir", rebound_team_role_id))
            self.assertIsNone(storage.get_provider_user_value_by_team_role("skills", "root_dir", rebound_team_role_id))
            self.assertIsNone(
                storage.get_provider_user_value_by_team_role_or_role(
                    "provider",
                    "working_dir",
                    team_role_id=rebound_team_role_id,
                    role_id=role.role_id,
                )
            )
            self.assertIsNone(
                storage.get_provider_user_value_by_team_role_or_role(
                    "provider",
                    "root_dir",
                    team_role_id=rebound_team_role_id,
                    role_id=role.role_id,
                )
            )


if __name__ == "__main__":
    unittest.main()
