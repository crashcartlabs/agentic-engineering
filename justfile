python := if os() == "windows" { "py -3" } else { "python3" }

default:
    @just --list

# Validate canonical skills, provider adapters, records, docs, and all embedded selftests.
check:
    {{python}} "{{justfile_directory()}}/scripts/ci/check_all.py"

# Report installed agent CLIs, platform capabilities, credentials, and source health.
doctor:
    {{python}} "{{justfile_directory()}}/scripts/toolbelt.py" doctor

# Preview a personal Claude/Codex/Pi installation without changing home directories.
install-dry-run:
    {{python}} "{{justfile_directory()}}/scripts/toolbelt.py" install --dry-run

# Install or update the personal Claude/Codex/Pi adapters.
install:
    {{python}} "{{justfile_directory()}}/scripts/toolbelt.py" install

# Publish a clean, single-commit snapshot to the public repo (force-pushes its main).
publish remote ref="main":
    {{python}} "{{justfile_directory()}}/scripts/release/publish_public.py" --remote "{{remote}}" --ref "{{ref}}"

# Build the public snapshot locally without pushing (inspect .public-snapshot-dryrun/).
publish-dry-run ref="main":
    {{python}} "{{justfile_directory()}}/scripts/release/publish_public.py" --dry-run --ref "{{ref}}"

# Bootstrap a new application repository into the required workflow.
new-app path:
    {{python}} "{{justfile_directory()}}/scripts/toolbelt.py" init-app {{quote(path)}} --create

# Start Claude Code in the target application repository with normal safeguards.
devcl repo=invocation_directory():
    cd {{quote(repo)}} && claude

# Start Codex with the target application repository as its working root.
devco repo=invocation_directory():
    codex -C {{quote(repo)}}

# Start Pi in the target application repository.
devpi repo=invocation_directory():
    cd {{quote(repo)}} && pi

# Bake off four agent/model combinations with normal provider safeguards.
# Run from inside cmux or explicitly configure a safe socket policy first.
build feature repo=invocation_directory():
    {{python}} "{{justfile_directory()}}/scripts/cmux/spawn_fleet.py" \
        --repo {{quote(repo)}} --arrange grid --orchestrator claude \
        --entry claude-opus:claude:opus:{{quote(feature)}} \
        --entry codex:codex:gpt-5.5:{{quote(feature)}} \
        --entry pi-glm:pi:zai/glm-5.2:{{quote(feature)}} \
        --entry pi-minimax:pi:minimax/MiniMax-M3:{{quote(feature)}}

# Conspicuous unsafe bake-off: disables Claude/Codex safeguards and relaxes cmux globally.
build-unsafe feature repo=invocation_directory():
    {{python}} "{{justfile_directory()}}/scripts/cmux/spawn_fleet.py" \
        --repo {{quote(repo)}} --arrange grid --orchestrator claude \
        --unsafe-yolo --allow-all-socket \
        --entry claude-opus:claude:opus:{{quote(feature)}} \
        --entry codex:codex:gpt-5.5:{{quote(feature)}} \
        --entry pi-glm:pi:zai/glm-5.2:{{quote(feature)}} \
        --entry pi-minimax:pi:minimax/MiniMax-M3:{{quote(feature)}}

# Run eight safeguarded agents for parallel bug investigation.
debug bug repo=invocation_directory():
    {{python}} "{{justfile_directory()}}/scripts/cmux/spawn_fleet.py" \
        --repo {{quote(repo)}} --arrange grid --orchestrator claude \
        --entry claude-opus-1:claude:opus:{{quote(bug)}} \
        --entry claude-opus-2:claude:opus:{{quote(bug)}} \
        --entry codex-1:codex:gpt-5.5:{{quote(bug)}} \
        --entry codex-2:codex:gpt-5.5:{{quote(bug)}} \
        --entry pi-glm-1:pi:zai/glm-5.2:{{quote(bug)}} \
        --entry pi-glm-2:pi:zai/glm-5.2:{{quote(bug)}} \
        --entry pi-minimax-1:pi:minimax/MiniMax-M3:{{quote(bug)}} \
        --entry pi-minimax-2:pi:minimax/MiniMax-M3:{{quote(bug)}}

# Render the worktree/PR dashboard once for the target repository.
dashboard repo=invocation_directory():
    {{python}} "{{justfile_directory()}}/scripts/dashboard/dashboard.py" --repo {{quote(repo)}}

# Run the report-only weekly janitor locally.
janitor:
    {{python}} "{{justfile_directory()}}/scripts/maintenance/weekly_janitor_report.py"

# Run the committed state of a repo in the offline-by-default Docker sandbox.
sandbox repo=invocation_directory():
    {{python}} "{{justfile_directory()}}/scripts/sandbox/prepare_archive.py" \
        --repo {{quote(repo)}} --output "{{justfile_directory()}}/.sandbox/source.tar"
    docker compose -f "{{justfile_directory()}}/sandbox/compose.yaml" run --rm sandbox

# Run the sandbox with network access explicitly enabled for downloads.
sandbox-online repo=invocation_directory():
    {{python}} "{{justfile_directory()}}/scripts/sandbox/prepare_archive.py" \
        --repo {{quote(repo)}} --output "{{justfile_directory()}}/.sandbox/source.tar"
    docker compose -f "{{justfile_directory()}}/sandbox/compose.yaml" run --rm sandbox-online

# Open the canonical app lifecycle guide.
help:
    #!/usr/bin/env sh
    guide="{{justfile_directory()}}/docs/app-build-workflow.html"
    case "{{os()}}" in
        macos)   open "$guide" ;;
        linux)   xdg-open "$guide" ;;
        windows) powershell -NoProfile -Command "Start-Process '$guide'" ;;
        *)       echo "Unsupported OS: {{os()}}" >&2; exit 1 ;;
    esac

# Open the cmux-specific guide.
cmux-help:
    #!/usr/bin/env sh
    guide="{{justfile_directory()}}/docs/cmux-guide.html"
    case "{{os()}}" in
        macos)   open "$guide" ;;
        linux)   xdg-open "$guide" ;;
        windows) powershell -NoProfile -Command "Start-Process '$guide'" ;;
        *)       echo "Unsupported OS: {{os()}}" >&2; exit 1 ;;
    esac
