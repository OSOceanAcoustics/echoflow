import toml
import asyncio
import os
from typing import Any, Dict, List, Optional, Union
from echoflow.config.echoflow_config import BaseConfig, EchoflowConfig, EchoflowPrefectConfig

from echoflow.stages_v2.subflows.pipeline_trigger import pipeline_trigger

from prefect.blocks.core import Block
from prefect_aws import AwsCredentials
from prefect_azure import AzureCosmosDbCredentials
import socket

from echoflow.stages_v2.utils.config_utils import get_storage_options


def check_internet_connection(host="8.8.8.8", port=53, timeout=5):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except Exception as e:
        return False


def echoflow_create_prefect_profile(
    name: str,
    api_key: str = None,
    workspace_id: str = None,
    account_id: str = None,
    set_active: bool = True,
):
    config_path = os.path.expanduser("~/.prefect/profiles.toml")
    with open(config_path, "r") as f:
        config = toml.load(f)

    if set_active:
        config["active"] = name

    profiles = config["profiles"]
    if api_key is not None and workspace_id is not None and account_id is not None:
        profiles[name] = {
            "PREFECT_API_KEY": api_key,
            "PREFECT_API_URL": f"https://api.prefect.cloud/api/accounts/{ account_id }/workspaces/{ workspace_id }",
        }
    else:
        profiles[name] = {}

    # Save the updated configuration file
    with open(config_path, "w") as f:
        toml.dump(config, f)

    # Does not update if switching from cloud to local or vice-versa, but updates the old profile which is active. This is the default behaviour of Prefect.
    update_prefect_config(
        prefect_api_key=api_key,
        prefect_workspace_id=workspace_id,
        prefect_account_id=account_id,
        profile_name=name,
    )


def load_profile(name: str):
    # Load the existing Prefect configuration file
    config_path = os.path.expanduser("~/.prefect/profiles.toml")
    with open(config_path, "r") as f:
        config = toml.load(f)

    if config.get("profiles").get(name) is None:
        raise ValueError("No such profile exists. Please try creating profile with this name")
    config["active"] = name

    # Save the updated configuration file
    with open(config_path, "w") as f:
        toml.dump(config, f)


def get_active_profile():
    # Load the existing Prefect configuration file
    config_path = os.path.expanduser("~/.prefect/profiles.toml")
    with open(config_path, "r") as f:
        config = toml.load(f)

    profiles = config["profiles"]

    for p in profiles.keys():
        if p == config["active"]:
            return profiles[p]

    raise ValueError("No profile found.")


def echoflow_start(
    dataset_config: Union[Dict[str, Any], str],
    pipeline_config: Union[Dict[str, Any], str],
    logging_config: Union[Dict[str, Any], str] = {},
    storage_options: Union[Dict[str, Any], Block] = None,
    options: Optional[Dict[str, Any]] = {}
):
    if storage_options is not None:
        if isinstance(storage_options, Block):
            storage_options = get_storage_options(storage_options=storage_options)
    else:
        storage_options = {}

    # Try loading the Prefect config block
    try:
        echoflow_config = EchoflowConfig.load("echoflow-config", validate=False)
    except ValueError as e:
        print("No Prefect Cloud Configuration found. Creating Prefect Local named 'echoflow-local'. Please add your prefect cloud ")
        # Add local profile to echoflow config but keep default as active since user might configure using Prefect setup
        echoflow_create_prefect_profile(name="echoflow-local", set_active=False)

    # Check if program can connect to the Internet.
    if check_internet_connection() == False:
        active_profile = get_active_profile()
        if active_profile["PREFECT_API_KEY"] is not None:
            raise ValueError(
                "Please connect to internet or consider switching to a local prefect environment. This can be done by calling load_profile('echoflow-local') method."
            )
        else:
            print("Using a local prefect environment. To go back to your cloud workspace call load_profile(<name>) with <name> of your cloud profile.")
    
    if options['storage_options_override'] is not None and options['storage_options_override'] == False:
        storage_options = {}

    # Call the actual pipeline
    pipeline_trigger(
        dataset_config=dataset_config,
        pipeline_config=pipeline_config,
        logging_config=logging_config,
        storage_options=storage_options
    )


def update_prefect_config(
    prefect_api_key: Optional[str] = None,
    prefect_account_id: Optional[str] = None,
    prefect_workspace_id: Optional[str] = None,
    profile_name: str = None,
    active: bool = True,
):
    profiles: List[str] = []
    prefect_config = EchoflowPrefectConfig(
        prefect_account_id=prefect_account_id,
        prefect_workspace_id=prefect_workspace_id,
        prefect_api_key=prefect_api_key,
        profile_name=profile_name,
    )

    uuid = asyncio.run(prefect_config.save(name=profile_name, overwrite=True))

    active_profile: str = None
    if active:
        active_profile = profile_name
    profiles.append(profile_name)

    try:
        current_config: EchoflowConfig = asyncio.run(EchoflowConfig.load("echoflow-config", validate=False))
        if current_config.prefect_configs is not None:

            if active_profile is None:            
                active_profile = current_config.active

            profiles = current_config.prefect_configs

            for p in profiles:
                if p == profile_name:
                    profiles.remove(p)
            profiles.append(profile_name)
        ecfg = asyncio.run(EchoflowConfig(active=active_profile, prefect_configs=profiles, blocks=current_config.blocks).save(
            "echoflow-config", overwrite=True
        ))
    except ValueError as e:
        ecfg = asyncio.run(EchoflowConfig(active=active_profile, prefect_configs=profiles, blocks=[]).save(
            "echoflow-config", overwrite=True
        ))
    return ecfg


def update_base_config(name: str, b_type: str, active: bool = False, options: Dict[str, Any] = {}):
    aws_base = BaseConfig(name=name, type=b_type, active=active, options=options)
    ecfg: Any = None
    try:
        blocks: List[BaseConfig] = []
        current_config = asyncio.run(EchoflowConfig.load("echoflow-config", validate=False))

        if current_config.blocks is not None:
            blocks = current_config.blocks
            for b in blocks:
                if b.name == name:
                    blocks.remove(b)
        blocks.append(aws_base)
        ecfg = asyncio.run(EchoflowConfig(
            prefect_configs=current_config.prefect_configs, blocks=blocks
        ).save("echoflow-config", overwrite=True))
    except ValueError as e:
        ecfg = asyncio.run(EchoflowConfig(active=None, prefect_configs=[], blocks=[aws_base]).save(
            "echoflow-config", overwrite=True
        ))
    return ecfg


def echoflow_config_AWS(
    aws_key: str,
    aws_secret: str,
    token: str = None,
    name: str = "echoflow-aws-credentials",
    region: str = None,
    options: Dict[str, Any] = {},
    active: bool = False,
):
    coro = asyncio.run(AwsCredentials(
        aws_access_key_id=aws_key,
        aws_secret_access_key=aws_secret,
        aws_session_token=token,
        region_name=region,
    ).save(name, overwrite=True))

    update_base_config(name=name, active=active, options=options, b_type="AwsCredentials")

def echoflow_config_AZ_cosmos(
    name: str = "echoflow-az-credentials",
    connection_string: str = None,
    options: Dict[str, Any] = {},
    active: bool = False,
):
    if connection_string is None:
        raise ValueError("Connection string cannot be empty.")
    coro = asyncio.run(AzureCosmosDbCredentials(
        connection_string=connection_string
    ).save(name, overwrite=True))

    update_base_config(name=name, active=active, options=options, b_type="AzCredentials")
