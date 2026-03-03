# Publish Workflow

This repository is for development only.

The main project integration step is simple:

1. finish the skill in this repository
2. run local runner checks
3. run smoke tests
4. copy the finished `skills/<skill_folder>/` into the main project `skills/` directory
5. enable the skill for a role in the bot UI

## Helper script

```bash
scripts/publish_to_bot_skills.sh --main-repo /path/to/main/repo --skill-folder fs_read_file
```

Only publish the skill folder itself.
