"""
This module provides utility functions related to working with files, directories, and data paths.

Module Functions:
    download_temp_file(raw: Dict[str, Any], working_dir: str, stage: Stage, config: Dataset) -> Dict[str, Any]:
        Downloads a temporary raw file from a URL path.

    extract_fs(url: str, storage_options: Dict[Any, Any] = {}, include_scheme: bool = False) -> Union[Tuple[Any, str], Any]:
        Extracts the fsspec file system from a URL path.

    make_temp_folder(folder_name: str, storage_options: Dict[str, Any]) -> str:
        Creates a temporary folder locally or remotely using fsspec.

    get_output_file_path(raw_dicts: List[Dict[str, Any]], config: Dataset) -> str:
        Generates the output file path based on the raw file dictionary's datetime key.

    isFile(file_path: str, storage_options: Dict[str, Any] = {}) -> bool:
        Checks if a file exists at the specified path using the fsspec file system.

    get_working_dir(stage: Stage, config: Dataset) -> str:
        Retrieves the working directory for a stage based on stage options and configuration.

    get_ed_list(config: Dataset, stage: Stage, transect_data: Union[Output, List[Dict[str, Any]], Dict[str, Any]]) -> List[open_converted]:
        Retrieves a list of open_converted objects for echopype data.

    get_zarr_list(config: Dataset, stage: Stage, transect_data: Union[Output, Dict[str, Any]]) -> List[xarray.Dataset]:
        Retrieves a list of xarray.Dataset objects for zarr data.

Author: Soham Butala
Email: sbutala@uw.edu
Date: August 22, 2023
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union
from urllib.parse import urlparse
from echopype import open_converted

import fsspec
from echoflow.config.models.datastore import Dataset
from echoflow.config.models.output_model import Output
from echoflow.config.models.pipeline import Stage
from dateutil import parser
from prefect import task
from fsspec.implementations.local import LocalFileSystem
import xarray as xr


def download_temp_file(raw, working_dir: str, stage: Stage, config: Dataset):
    """
    Downloads a temporary raw file from a URL path.

    Args:
        raw (Dict[str, Any]): Raw file dictionary containing file information.
        working_dir (str): Working directory where the file will be downloaded.
        stage (Stage): Current processing stage object.
        config (Dataset): Dataset configuration.

    Returns:
        Dict[str, Any]: Updated raw file dictionary with local file path.

    Example:
        raw_data = {'file_path': 'https://example.com/data.raw', ...}
        working_directory = '/path/to/working_dir'
        stage_object = ...
        dataset_config = ...
        updated_raw = download_temp_file(raw_data, working_directory, stage_object, dataset_config)
    """

    urlpath = raw.get("file_path")
    fname = os.path.basename(urlpath)
    out_path = working_dir+"/"+fname
    working_dir_fs = extract_fs(
        out_path, storage_options=config.output.storage_options_dict)

    if stage.options.get("use_raw_offline") == False or isFile(out_path, config.output.storage_options_dict) == False:

        print("Downloading ...", out_path)
        file_system = extract_fs(
            urlpath, storage_options=config.args.storage_options_dict)
        with file_system.open(urlpath, 'rb') as source_file:
            with working_dir_fs.open(out_path, mode="wb") as f:
                f.write(source_file.read())
    raw.update({"local_path": out_path})
    return raw


def extract_fs(
    url: str,
    storage_options: Dict[Any, Any] = {},
    include_scheme: bool = False,
) -> Union[Tuple[Any, str], Any]:
    """
    Extracts the fsspec file system from a URL path.

    Args:
        url (str): URL path string.
        storage_options (Dict[Any, Any]): Additional keywords to pass to the filesystem class.
        include_scheme (bool): Flag to include scheme in the output of the function.

    Returns:
        Union[Tuple[Any, str], Any]: Filesystem for the given protocol and arguments.

    Example:
        fs = extract_fs('s3://mybucket/data', storage_options={'anon': True})
    """
    parsed_path = urlparse(url)
    file_system = fsspec.filesystem(parsed_path.scheme, **storage_options)
    if include_scheme:
        return file_system, parsed_path.scheme
    return file_system


def make_temp_folder(folder_name: str, storage_options: Dict[str, Any]) -> str:
    """
    Creates a temporary folder locally or remotely using fsspec.

    Args:
        folder_name (str): Name of the folder.
        storage_options (Dict[str, Any]): Storage options for fsspec.

    Returns:
        str: Path to the created temporary folder.

    Example:
        temp_folder = make_temp_folder('temp_folder', storage_options={'anon': True})
    """

    fsmap = fsspec.get_mapper(folder_name, **storage_options)
    if fsmap.fs.isdir(fsmap.root) == False:
        fsmap.fs.mkdir(fsmap.root, exists_ok=True, create_parents=True)
    if isinstance(fsmap.fs, LocalFileSystem):
        return str(Path(folder_name).resolve())
    return folder_name


@task
def get_output_file_path(raw_dicts, config: Dataset):
    """
    Get the output file path based on the raw file dictionary datetime key.
    It will grab the first file and use that as the file name in the form of 'DYYYYmmdd-THHMMSS.zarr'.

    This method will also grab a value from the config.output.urlpath for where the file should go.

    Parameters:
        raw_dicts (List[Dict[str, Any]]): The list of raw URL dictionaries. Must have 'datetime' key!
        config (Dataset): The pydantic Dataset object that contains all the necessary configurations.

    Returns:
        str: The full path string to the zarr file.

    Example:
        raw_files = [{'datetime': '2023-08-15T12:34:56', ...}, ...]
        dataset_config = ...
        zarr_file_path = get_output_file_path(raw_files, dataset_config)
    """
    if len(raw_dicts) < 1:
        raise ValueError("There must be at least one raw file dictionary!")

    first_file = raw_dicts[0]
    datetime_obj = parser.parse(first_file.get("datetime"))
    if config.args.transect is None:
        # Only use datetime
        out_fname = datetime_obj.strftime("D%Y%m%d-T%H%M%S.zarr")
    else:
        # Use transect number
        transect_num = first_file.get("transect_num", None)
        date_name = datetime_obj.strftime("D%Y%m%d-T%H%M%S")
        out_fname = f"x{transect_num:04}-{date_name}.zarr"
    return "/".join([config.output.urlpath, out_fname])


def isFile(file_path: str, storage_options: Dict[str, Any] = {}):
    """
    Check if a file exists at the specified path using the fsspec file system.

    Parameters:
        file_path (str): The path to the file.
        storage_options (Dict[str, Any]): Storage options for fsspec.

    Returns:
        bool: True if the file exists, False otherwise.

    Example:
        exists = isFile('s3://mybucket/data.zarr', storage_options={'anon': True})
    """
    fs = extract_fs(file_path, storage_options=storage_options)
    if file_path.endswith(".zarr"):
        return fs.isdir(file_path)
    return fs.isfile(file_path)


def get_working_dir(stage: Stage, config: Dataset):
    """
    Get the working directory for a stage based on stage options and configuration.

    Parameters:
        stage (Stage): The current processing stage object.
        config (Dataset): The Dataset configuration.

    Returns:
        str: The path to the working directory.

    Example:
        stage_object = ...
        dataset_config = ...
        working_directory = get_working_dir(stage_object, dataset_config)
    """
    if stage.options is not None and stage.options.get("out_path") is not None:
        working_dir = make_temp_folder(stage.options.get(
            "out_path"), config.output.storage_options_dict)
    elif config.output.urlpath is not None:
        working_dir = make_temp_folder(
            config.output.urlpath+"/"+stage.name, config.output.storage_options_dict)
    else:
        working_dir = make_temp_folder(
            "Echoflow_working_dir"+"/"+stage.name, config.output.storage_options_dict)

    return working_dir


@task
def get_ed_list(config: Dataset, stage: Stage, transect_data: Union[Output, List[Dict], Dict]):
    """
    Get a list of open_converted objects for echopype data.

    Parameters:
        config (Dataset): The Dataset configuration.
        stage (Stage): The current processing stage object.
        transect_data (Union[Output, List[Dict[str, Any]], Dict[str, Any]]): The transect data or output.

    Returns:
        List[open_converted]: A list of open_converted objects.

    Example:
        dataset_config = ...
        stage_object = ...
        transect_output = ...
        echopype_list = get_ed_list(dataset_config, stage_object, transect_output)
    """
    ed_list = []
    if type(transect_data) == list:
        for zarr_path_data in transect_data:
            ed = open_converted(
                converted_raw_path=str(zarr_path_data.get("out_path")),
                storage_options=dict(config.output.storage_options_dict),
            )
            ed_list.append(ed)
    elif type(transect_data) == dict:
        ed = open_converted(
            converted_raw_path=str(transect_data.get("out_path")),
            storage_options=dict(config.output.storage_options_dict),
        )
        ed_list.append(ed)
    else:
        zarr_path_data = transect_data.data
        ed = open_converted(
            converted_raw_path=str(zarr_path_data.get("out_path")),
            storage_options=dict(config.output.storage_options_dict),
        )
        ed_list.append(ed)
    return ed_list


@task
def get_zarr_list(config: Dataset, stage: Stage, transect_data: Union[Output, Dict]):
    """
    Get a list of xarray.Dataset objects for zarr data.

    Parameters:
        config (Dataset): The Dataset configuration.
        stage (Stage): The current processing stage object.
        transect_data (Union[Output, Dict[str, Any]]): The transect data or output.

    Returns:
        List[xarray.Dataset]: A list of xarray.Dataset objects.

    Example:
        dataset_config = ...
        stage_object = ...
        transect_output = ...
        zarr_list = get_zarr_list(dataset_config, stage_object, transect_output)
    """
    zarr_list = []
    if type(transect_data) == dict:
        zarr = xr.open_zarr(transect_data.get("out_path"),
                            storage_options=config.output.storage_options_dict)
        zarr_list.append(zarr)
    else:
        zarr_path_data = transect_data.data
        zarr = xr.open_zarr(zarr_path_data.get("out_path"),
                            storage_options=config.output.storage_options_dict)
        zarr_list.append(zarr)

    return zarr_list

def process_output_transects(name: str, ed_list: List[Dict[str, Any]]) -> List[Output]:
    """
    Process and aggregate output transects.

    This function processes a list of echodata (ed) dictionaries and aggregates them based on transect numbers.
    It raises a ValueError if any of the echodata dictionaries have an error flag set to True.

    Parameters:
        name (str): The name of the process.
        ed_list (List[Dict[str, Any]]): A list of echodata dictionaries.

    Returns:
        List[Output]: A list of Output instances, each containing aggregated data for a transect.

    Raises:
        ValueError: If any echodata dictionary has an error flag set to True.

    Example:
        ed_list = [
            {"transect": 1, "data": {...}, "error": False},
            {"transect": 1, "data": {...}, "error": False},
            {"transect": 2, "data": {...}, "error": False},
            {"transect": 2, "data": {...}, "error": False},
            {"transect": 2, "data": {...}, "error": True}
        ]

        output_list = process_output_transects("Data Processing", ed_list)
        # Returns a list of Output instances with aggregated data per transect.

    """
    transect_dict = {}
    outputs: List[Output] = []
    for ed in ed_list:
        if ed["error"] == True:
            raise ValueError("Could not complete "+name+" successfully since 1 or more raw files" 
                                + "failed to convert. Try fixing or skipping the files from the process."
                                + "If `use_offline` flag is set to true, processed files will be skipped the next run.")
        transect = ed['transect']
        if transect in transect_dict:
            transect_dict[transect].append(ed)
        else:
            transect_dict[transect] = [ed]

    for transect in transect_dict.keys():
        output = Output()
        output.data = transect_dict[transect]
        outputs.append(output)
    return outputs