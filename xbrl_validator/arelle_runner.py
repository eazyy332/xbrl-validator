import shlex
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed


def _build_arelle_args(
    instance_path: str,
    packages: Optional[str] = None,
    validate: bool = True,
    additional_arelle_args: Optional[str] = None,
    additional_arelle_args_list: Optional[List[str]] = None,
    cache_dir: Optional[str] = None,
    log_format: Optional[str] = None,
) -> List[str]:
    args: List[str] = ["-m", "arelle.CntlrCmdLine", "--file", instance_path]
    if validate:
        args.append("--validate")
    if packages:
        args.extend(["--packages", packages])
    if cache_dir:
        args.extend(["--cacheDir", cache_dir])
    if log_format:
        args.extend(["--logFormat", log_format])
    if additional_arelle_args_list:
        args.extend(additional_arelle_args_list)
    if additional_arelle_args:
        # Allow users to pass a raw string of additional flags
        args.extend(shlex.split(additional_arelle_args))
    return args


def validate_with_arelle(
    instance_path: str,
    packages: Optional[str] = None,
    validate: bool = True,
    additional_arelle_args: Optional[str] = None,
    additional_arelle_args_list: Optional[List[str]] = None,
    cwd: Optional[str] = None,
    cache_dir: Optional[str] = None,
    log_format: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """
    Runs Arelle's command line controller via `python -m arelle.CntlrCmdLine`.

    Parameters
    ----------
    instance_path: path to the XBRL instance document.
    packages: path to a taxonomy package zip, or zip#entry.xsd syntax.
    validate: include --validate.
    additional_arelle_args: extra flags, e.g. "--disclosureSystem esef".
    cwd: working directory to run the process from.
    """
    python_exe = sys.executable
    args = [python_exe] + _build_arelle_args(
        instance_path=instance_path,
        packages=packages,
        validate=validate,
        additional_arelle_args=additional_arelle_args,
        additional_arelle_args_list=additional_arelle_args_list,
        cache_dir=cache_dir,
        log_format=log_format,
    )
    return subprocess.run(
        args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )


def validate_many_with_arelle(
    instance_paths: Iterable[str],
    packages: Optional[str] = None,
    validate: bool = True,
    additional_arelle_args: Optional[str] = None,
    additional_arelle_args_list: Optional[List[str]] = None,
    cwd: Optional[str] = None,
    cache_dir: Optional[str] = None,
    log_format: Optional[str] = None,
) -> List[subprocess.CompletedProcess]:
    results: List[subprocess.CompletedProcess] = []
    for p in instance_paths:
        results.append(
            validate_with_arelle(
                instance_path=p,
                packages=packages,
                validate=validate,
                additional_arelle_args=additional_arelle_args,
                additional_arelle_args_list=additional_arelle_args_list,
                cwd=cwd,
                cache_dir=cache_dir,
                log_format=log_format,
            )
        )
    return results


def validate_many_parallel_with_arelle(
    instance_paths: Iterable[str],
    packages: Optional[str] = None,
    validate: bool = True,
    additional_arelle_args: Optional[str] = None,
    additional_arelle_args_list: Optional[List[str]] = None,
    cwd: Optional[str] = None,
    cache_dir: Optional[str] = None,
    log_format: Optional[str] = None,
    max_workers: int = 4,
) -> List[subprocess.CompletedProcess]:
    futures = []
    results: List[subprocess.CompletedProcess] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for p in instance_paths:
            futures.append(
                executor.submit(
                    validate_with_arelle,
                    instance_path=p,
                    packages=packages,
                    validate=validate,
                    additional_arelle_args=additional_arelle_args,
                    additional_arelle_args_list=additional_arelle_args_list,
                    cwd=cwd,
                    cache_dir=cache_dir,
                    log_format=log_format,
                )
            )
        for fut in as_completed(futures):
            results.append(fut.result())
    return results


def validate_many_parallel_with_paths(
    instance_paths: Iterable[str],
    packages: Optional[str] = None,
    validate: bool = True,
    additional_arelle_args: Optional[str] = None,
    additional_arelle_args_list: Optional[List[str]] = None,
    cwd: Optional[str] = None,
    cache_dir: Optional[str] = None,
    log_format: Optional[str] = None,
    max_workers: int = 4,
) -> List[tuple[str, subprocess.CompletedProcess]]:
    futures = []
    results: List[tuple[str, subprocess.CompletedProcess]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for p in instance_paths:
            fut = executor.submit(
                validate_with_arelle,
                instance_path=p,
                packages=packages,
                validate=validate,
                additional_arelle_args=additional_arelle_args,
                additional_arelle_args_list=additional_arelle_args_list,
                cwd=cwd,
                cache_dir=cache_dir,
                log_format=log_format,
            )
            futures.append((p, fut))
        for path, fut in futures:
            results.append((path, fut.result()))
    return results


def path_exists(path_str: Optional[str]) -> bool:
    if not path_str:
        return False
    try:
        return Path(path_str.split("#", 1)[0]).exists()
    except Exception:
        return False

