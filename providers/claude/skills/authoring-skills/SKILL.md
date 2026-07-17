---
name: authoring-skills
description: "Route a request to create, write, build, author, or improve an Agent Skill to the right workflow. Use when the user wants to make a new skill, turn a repeated task or prompt into a skill, write a SKILL.md, or sharpen an existing skill that mis-triggers or underperforms—even if they do not name a command. Points skill authoring and improvement requests to build-skill. Not for merely using, listing, or invoking a skill that already does the job."
---


# Authoring skills — router

The user wants to author or improve a skill. Route every such request to `/build-skill [name]`.

Name the principle before handing off: a skill exists to make the agent take the same process every run, and it must be built from real work rather than imagination.

Do not fire for merely using, listing, or invoking an existing skill ("run the
code-audit skill", "what skills do I have?"); route those to the requested skill or
ordinary help.
