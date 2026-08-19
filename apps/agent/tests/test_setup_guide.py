from src.agent.setup_guide import (
    SETUP_GUIDE_VERSION,
    SUPPORTED_N8N_VERSION,
    get_public_setup_guide_payload,
    get_setup_stage_order,
    get_setup_step,
    get_setup_step_payload,
)


def _flatten_stage_text(stage_name: str) -> str:
    payload = get_setup_step_payload(stage_name)
    parts: list[str] = [
        str(payload["summary"]),
        *(str(item) for item in payload.get("instructions", [])),
        *(str(item) for item in payload.get("expected_signals", [])),
        *(str(item) for item in payload.get("troubleshooting", [])),
        *(str(item) for item in payload.get("safety_notes", [])),
    ]
    question = payload.get("ask_for")
    if isinstance(question, dict):
        parts.append(str(question.get("question", "")))
    for command in payload.get("commands", []):
        if isinstance(command, dict):
            parts.extend([str(command.get("description", "")), str(command.get("command", ""))])
    for file_payload in payload.get("files", []):
        if isinstance(file_payload, dict):
            parts.extend(
                [
                    str(file_payload.get("path", "")),
                    str(file_payload.get("description", "")),
                    str(file_payload.get("content", "")),
                ]
            )
    return "\n".join(parts).lower()


def test_setup_guide_stage_order_and_version_are_locked():
    assert get_setup_stage_order() == (
        "requirements",
        "inspect_server",
        "install_docker",
        "dns_readiness",
        "deploy_n8n",
        "verify_stack",
        "handoff_to_conduut",
    )

    for stage_name in get_setup_stage_order():
        stage = get_setup_step(stage_name)
        assert stage.schema_version == SETUP_GUIDE_VERSION
        assert stage.supported_target.n8n_version == SUPPORTED_N8N_VERSION
        assert stage.supported_target.preferred_os == "Ubuntu 24.04 LTS"
        assert stage.supported_target.supported_os_versions == [
            "Ubuntu 22.04 LTS",
            "Ubuntu 24.04 LTS",
        ]


def test_setup_guide_deploy_stage_pins_supported_n8n_version():
    deploy_stage = get_setup_step("deploy_n8n")
    compose_file = next(
        file for file in deploy_stage.files if file.path.endswith("docker-compose.yml")
    )

    assert f"n8nio/n8n:{SUPPORTED_N8N_VERSION}" in compose_file.content
    assert 'N8N_PROXY_HOPS: "1"' in compose_file.content
    assert 'N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS: "true"' in compose_file.content
    assert 'N8N_RUNNERS_ENABLED: "true"' in compose_file.content
    assert "N8N_WEBHOOK_URL: ${N8N_HOST}" not in compose_file.content
    assert "N8N_WEBHOOK_URL: https://${N8N_HOST}/" in compose_file.content
    assert "GENERIC_TIMEZONE: Europe/Istanbul" in compose_file.content
    assert "TZ: Europe/Istanbul" in compose_file.content
    assert "N8N_ENCRYPTION_KEY: ${N8N_ENCRYPTION_KEY}" in compose_file.content
    assert '"5678:5678"' not in compose_file.content
    assert "command:" not in compose_file.content
    assert "exec n8n start" not in compose_file.content
    assert "secrets:" not in compose_file.content
    assert all(not file.path.endswith(".env") for file in deploy_stage.files)


def test_setup_guide_deploy_stage_generates_root_only_env_silently():
    deploy_stage = get_setup_step("deploy_n8n")
    commands = {command.description: command.command for command in deploy_stage.commands}

    generation_command = commands[
        "Create the deployment .env file and silently generate the encryption key into it"
    ]

    assert "/opt/conduut-n8n/.env" in generation_command
    assert "openssl rand -hex 32" in generation_command
    assert "cat > /opt/conduut-n8n/.env <<EOF" in generation_command
    assert "N8N_ENCRYPTION_KEY=$(openssl rand -hex 32)" in generation_command
    assert "openssl rand -hex 32 >" not in generation_command


def test_setup_guide_deploy_stage_writes_config_files_before_starting_stack():
    deploy_stage = get_setup_step("deploy_n8n")
    commands = [command.command for command in deploy_stage.commands]

    compose_write_index = next(
        index for index, command in enumerate(commands) if "docker-compose.yml" in command
    )
    caddy_write_index = next(
        index
        for index, command in enumerate(commands)
        if command.startswith("sudo tee /opt/conduut-n8n/Caddyfile ")
    )
    validation_index = next(
        index for index, command in enumerate(commands) if "compose config --quiet" in command
    )
    start_index = next(
        index for index, command in enumerate(commands) if "compose up -d" in command
    )

    assert "<<'CONDUUT_FILE_EOF'" in commands[compose_write_index]
    assert f"n8nio/n8n:{SUPPORTED_N8N_VERSION}" in commands[compose_write_index]
    assert "reverse_proxy n8n:5678" in commands[caddy_write_index]
    assert compose_write_index < validation_index < start_index
    assert caddy_write_index < validation_index < start_index


def test_setup_guide_install_docker_stage_uses_dynamic_codename_and_sources_file():
    install_stage = get_setup_step("install_docker")
    commands = {command.description: command.command for command in install_stage.commands}
    source_command = commands["Add Docker's official apt repository key and source file"]

    assert "/etc/apt/keyrings/docker.asc" in source_command
    assert "/etc/apt/sources.list.d/docker.sources" in source_command
    assert "OS_CODENAME" in source_command
    assert "jammy" not in source_command
    assert "noble stable" not in source_command
    assert "docker.gpg" not in source_command


def test_setup_guide_docker_installs_wait_for_ubuntu_dpkg_lock():
    install_stage = get_setup_step("install_docker")
    install_commands = [
        command.command
        for command in install_stage.commands
        if "apt-get" in command.command and " install " in command.command
    ]

    assert len(install_commands) == 2
    assert all("DPkg::Lock::Timeout=600" in command for command in install_commands)
    assert any(
        "do not delete the lock file" in item.lower() for item in install_stage.troubleshooting
    )


def test_dns_stage_has_no_premature_https_check():
    dns_stage = get_setup_step("dns_readiness")
    commands = [command.command for command in dns_stage.commands]

    assert all("curl -I https://" not in command for command in commands)
    assert any("getent ahosts" in command for command in commands)
    assert any("resolvectl query" in command for command in commands)


def test_setup_guide_keeps_secrets_out_of_chat_requests():
    banned_phrases = (
        "paste your password",
        "send your password",
        "paste your ssh private key",
        "send your ssh private key",
        "paste your api key here",
        "send your api key here",
        "paste your token",
        "send your token",
        "paste your encryption key",
        "send your encryption key",
    )

    for stage_name in get_setup_stage_order():
        text = _flatten_stage_text(stage_name)
        for phrase in banned_phrases:
            assert phrase not in text, f"{stage_name} leaked unsafe request language: {phrase}"


def test_setup_guide_final_handoff_requires_settings_not_chat():
    handoff = get_setup_step_payload("handoff_to_conduut")
    text = _flatten_stage_text("handoff_to_conduut")

    assert handoff["next_stage"] is None
    assert "do not paste the n8n api key into chat" in text
    assert "conduut settings -> automation server" in text


def test_public_setup_guide_payload_is_camel_case_and_stage_complete():
    payload = get_public_setup_guide_payload()

    assert payload["schemaVersion"] == SETUP_GUIDE_VERSION
    assert payload["totalStages"] == len(get_setup_stage_order())
    assert payload["supportedTarget"]["preferredOs"] == "Ubuntu 24.04 LTS"
    assert payload["supportedTarget"]["supportedOsVersions"] == [
        "Ubuntu 22.04 LTS",
        "Ubuntu 24.04 LTS",
    ]
    assert payload["supportedTarget"]["baselineResources"] == (
        "Required: public HTTPS-reachable VPS. Recommended: 2 vCPU, 4 GB RAM, 40 GB SSD, 2 GB swap."
    )
    assert payload["supportedTarget"]["n8nVersion"] == SUPPORTED_N8N_VERSION

    stage = payload["stages"][0]
    assert "stageIndex" in stage
    assert "expectedSignals" in stage
    assert "safetyNotes" in stage
    assert "nextStage" in stage
    assert "stage_index" not in stage
    assert "expected_signals" not in stage


def test_setup_guide_inspection_stage_is_read_only_and_waits_for_output():
    inspect_stage = get_setup_step("inspect_server")
    commands = [command.command for command in inspect_stage.commands]

    assert inspect_stage.wait_for_pasted_output is True
    assert all("apt-get install" not in command for command in commands)
    assert any(command.startswith("uname -m") for command in commands)
    assert any("ss -ltn" in command for command in commands)


def test_deploy_stage_file_write_instructions_are_executable_shell_commands():
    deploy_stage = get_setup_step("deploy_n8n")
    commands = [command.command for command in deploy_stage.commands]

    assert any("Run the commands below in order" in item for item in deploy_stage.instructions)
    assert any("sudo tee /opt/conduut-n8n/docker-compose.yml" in command for command in commands)
    assert any("sudo tee /opt/conduut-n8n/Caddyfile" in command for command in commands)


def test_verify_stage_uses_get_health_check_instead_of_head_request():
    verify_stage = get_setup_step("verify_stack")
    commands = [command.command for command in verify_stage.commands]

    assert any("/healthz" in command for command in commands)
    assert all("curl -I" not in command for command in commands)
