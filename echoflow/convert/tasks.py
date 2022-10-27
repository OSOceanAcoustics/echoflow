from typing import Dict, Any, List

import json
import itertools as it

from prefect import task
import dask
import dask.distributed
from dask import delayed

from ..utils import extract_fs
from .utils import (
    make_temp_folder,
    download_temp_file,
    open_and_save,
    combine_data,
)


@task
def data_convert(idx, raw_dicts, deployment, client=None, config={}):
    """
    Task for running the data conversion on a list of raw url
    dictionaries.

    Parameters
    ----------
    idx : int
        The week index
    raw_dicts : list
        The list of raw url dictionary
    client : dask.distributed.Client, optional
        The dask client to use for `echopype.combine_echodata`
    config : dict
        Pipeline configuration file
    deployment : str
        The deployment string to identify combined file

    Returns
    -------
    String path to the combined echodata file

    """
    zarr_path = f"combined-{deployment}-{idx}.zarr"
    # TODO: Allow for specifying output path
    temp_raw_dir = make_temp_folder()
    ed_tasks = []
    for raw in raw_dicts:
        raw = delayed(download_temp_file)(raw, temp_raw_dir)
        ed = delayed(open_and_save)(raw)
        ed_tasks.append(ed)
    ed_list = dask.compute(*ed_tasks)
    return combine_data(ed_list, zarr_path, client)


@task
def parse_raw_json(
    raw_url_file: str, json_storage_options: Dict[Any, Any] = {}
) -> List[List[Dict[str, Any]]]:
    """
    Task to parse raw urls json files and splits them into
    weekly list by utilizing julian days.

    This assumes the following raw url dictionary

    ```
    {'instrument': 'EK60',
    'file_path': 'https://example.com/some-file.raw',
    'month': 1,
    'year': 2017,
    'jday': 1,
    'datetime': '2017-01-01T00:00:00'}
    ```

    Parameters
    ----------
    raw_url_file : str
        raw urls file path string
    json_storage_options : dict
        storage options for reading raw urls file path

    Returns
    -------
    List of list of raw urls string,
    broken up to 7 julian days each chunk
    """
    file_system = extract_fs(
        raw_url_file, storage_options=json_storage_options
    )
    with file_system.open(raw_url_file) as f:
        raw_dicts = json.load(f)

    # Number of days for a week chunk
    n = 7

    all_jdays = sorted({r.get('jday') for r in raw_dicts})
    split_days = [
        all_jdays[i : i + n] for i in range(0, len(all_jdays), n)  # noqa
    ]

    day_dict = {}
    for r in raw_dicts:
        mint = r.get('jday')
        if mint not in day_dict:
            day_dict[mint] = []
        day_dict[mint].append(r)

    all_weeks = []
    for week in split_days:
        files = list(it.chain.from_iterable([day_dict[d] for d in week]))
        all_weeks.append(files)

    return all_weeks
