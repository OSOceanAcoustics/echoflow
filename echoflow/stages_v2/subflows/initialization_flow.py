import logging
from typing import Any, Dict

import dask
from distributed import Client, LocalCluster

from echoflow.config.models.datastore import Dataset
from echoflow.config.models.pipeline import Recipe
from echoflow.stages_v2.aspects.echoflow_aspect import echoflow
from echoflow.stages_v2.utils.config_utils import club_raw_files, get_prefect_config_dict, glob_all_files, parse_raw_paths
from echoflow.stages_v2.utils.function_utils import dynamic_function_call

from prefect import flow
from prefect.task_runners import SequentialTaskRunner
from prefect.filesystems import *
from prefect_dask import DaskTaskRunner

@flow(name="Main-Flow", task_runner=SequentialTaskRunner())
@echoflow(type="FLOW")
def init_flow(
        pipeline: Recipe,
        dataset: Dataset
        ):
    prefect_config_dict = {}
    file_dicts = []

    if dataset.args.raw_json_path is None:
        total_files = glob_all_files(config=dataset)
        file_dicts = parse_raw_paths(all_raw_files=total_files, config=dataset)

    data = club_raw_files(
        config=dataset,
        raw_dicts=file_dicts,
        raw_url_file=dataset.args.raw_json_path,
        json_storage_options=dataset.output.storage_options_dict
    )

    process_list = pipeline.pipeline
    client: Client = None
    for process in process_list:
        for stage in process.stages:
            function = dynamic_function_call(stage.module, stage.name)
            prefect_config_dict = get_prefect_config_dict(stage, pipeline, prefect_config_dict)

            if pipeline.scheduler_address is not None and pipeline.use_local_dask == False:
                if client is None:
                    client = Client(pipeline.scheduler_address)
                prefect_config_dict["task_runner"] = DaskTaskRunner(address=client.scheduler.address)
            elif pipeline.use_local_dask == True and prefect_config_dict is not None and prefect_config_dict.get("task_runner") is None:
                if client is None:
                    cluster = LocalCluster(n_workers=3)
                    client = Client(cluster.scheduler_address)
                prefect_config_dict["task_runner"] = DaskTaskRunner(address=client.scheduler.address)
                
            function = function.with_options(**prefect_config_dict)
            print("Executing stage : ",stage)
            output = function(dataset, stage, data)
            data = output
            print(output)
            print("Completed stage", stage)

    # Close the local cluster but not the cluster hosted. 
    if pipeline.scheduler_address is None and pipeline.use_local_dask == True:
        client.close()
        print("Local Client has been closed")
    return output


